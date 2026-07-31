"""core.py — Self-contained navigation module.

Consolidates A*, repulsor/attractor potential fields, configurable
spacing for teammates / strangers / obstacles, and a per-agent
decaying tabu trail. All knobs live on ``GridNavConfig``; per-agent
state lives on ``GridNavState``. The module is the dependency, not a
dependent — no other project files are imported, so the existing
policy stacks can later be converted to call into this without
introducing a circular import.

Origin: extracted from Ron Dahlgren's (swgy) agent libraries (sm-policies
Cogs-vs-Clips scripted stack; original module name ``swgy_nav.py``). The
lineage table below records where each feature originated *in that stack* —
those files are not part of this repository.

Lineage
-------
========================================  ===========================================
Feature                                   Source
----------------------------------------  -------------------------------------------
Direction tables, sidestep mechanics      ``scripted/policy_base.py:64-93,1745-1830``
Position tracking from move-success       ``scripted/policy_base.py:1041-1087``
Wall folding from observation window      ``scripted/policy_base.py:1109-1118``
Weighted A* with cost floor               ``scripted/mas_weighted_astar.py:66-190``
Falloff curves, sparse PF source list     ``scripted/mas_potential_field.py:60-73``
Tabu trail (linear/geometric/constant)    ``scripted/policy_mas.py:1099-1153``
========================================  ===========================================

Coordinate model
----------------
All coordinates are ``(row, col)``. The module operates entirely in the
caller's *local frame*: agent spawn = ``(0, 0)``, advanced only on
move-success accounting (see :func:`update_position`). ``observe()``
converts observation-window coords to local frame; after that, every
public API takes local-frame coords.

Cost-shaped A*
--------------
Edge cost into cell ``C`` is::

    cost(C) = clamp(
        cost_floor,
        max_repulsion_per_step,
        base_terrain_weight
        + repulsion(C)        # teammates, strangers, walls (soft buffer),
                              # tabu trail, caller repulsors
        - attraction(C),      # caller attractors
    )

Repulsion adds, attraction subtracts. The cost floor keeps A*
well-behaved; the per-step caps keep one mis-weighted source from
inflating the open set.

Heuristic admissibility
-----------------------
Three modes:

* ``"manhattan"`` — ``base_terrain_weight * manhattan(c, goal)``.
  Admissible iff no attractors are active. Fast.
* ``"zero"`` — Dijkstra. Always admissible. Slower.
* ``"weighted"`` — same as ``"manhattan"`` but always returned.
  Mildly inadmissible under attractors; matches
  ``mas_weighted_astar.py`` defaults. Documented trade-off.
* ``"auto"`` (default) — picks ``"manhattan"`` when no attractors are
  active in the current call, ``"zero"`` otherwise. Correct by default.

Caller contract
---------------
Per agent, per tick, in order:

1. ``update_position(nav_state, last_dir, succeeded, ...)``  — fold the
   previous move attempt into ``position``/``blocked``.
2. ``view = observe(nav_state, frozen_tags, obs_center)``     — fold
   visible walls into ``blocked``, classify visible entities.
3. ``direction = next_move(nav_state, view, target_local, ...)``
   — OR — ``direction = next_move_cached(nav_state, view, target,
   detour=..., max_detour_steps=..., replan_every=N, ...)`` when the
   caller wants opportunistic POI detours and/or a cached plan that
   replays across ticks (replans only on failed move, newly-blocked
   next cell, drift, target/detour change, or every ``N`` steps).
4. After issuing the chosen move (or any successful move), call
   ``record_step(nav_state)`` to push the new position onto the tabu
   trail.

Forgetting step (1) silently desyncs ``position`` from the world. The
module cannot detect this; callers must honor the contract.
"""

from __future__ import annotations

import heapq
from collections import deque
from dataclasses import dataclass, field
from typing import Callable, Iterable

from .distance import manhattan as _manhattan  # canonical metric (see distance.py)

Coordinate = tuple[int, int]

# ---------------------------------------------------------------------
# Direction constants (duplicated from policy_base.py:64-93 on purpose
# so this module has zero project-internal imports).
# ---------------------------------------------------------------------

MOVE_DELTAS: dict[str, Coordinate] = {
    "north": (-1, 0),
    "south": (1, 0),
    "west": (0, -1),
    "east": (0, 1),
}

WANDER_DIRECTIONS: tuple[str, ...] = ("east", "south", "west", "north")

RIGHT_OF: dict[str, str] = {
    "north": "east",
    "east": "south",
    "south": "west",
    "west": "north",
}

LEFT_OF: dict[str, str] = {
    "north": "west",
    "west": "south",
    "south": "east",
    "east": "north",
}

# ---------------------------------------------------------------------
# Falloff curves (mirrors mas_potential_field.py:60-73).
# Each takes (distance, radius) and returns a multiplier in [0, 1].
# ---------------------------------------------------------------------

_FALLOFFS: dict[str, Callable[[float, int], float]] = {
    "linear": lambda d, r: max(0.0, 1.0 - d / max(r, 1)),
    "inverse_square": lambda d, r: 1.0 / (1.0 + d * d),
    "step": lambda d, r: 1.0 if d <= r else 0.0,
    "triangle": lambda d, r: max(0.0, 1.0 - d / max(r, 1)),
}


def _falloff(name: str, d: float, r: int) -> float:
    fn = _FALLOFFS.get(name, _FALLOFFS["linear"])
    return fn(d, r)



# ---------------------------------------------------------------------
# Team-member position trails
# ---------------------------------------------------------------------
#
# Mirrors ``policy_base.TeamMemberTrack`` (deliberate duplication — this
# module has zero project-internal imports; see policy_base.py:64-93).
# Keyed by ``agent_id`` (proven runtime data); records (step, local_coord)
# pairs in chronological order.  Used by ``_build_repulsion_sources`` to
# emit predicted-cell and tail-cell repulsors for trail-based collision
# avoidance.

@dataclass
class TeamMemberTrack:
    """Recent observed positions of one team member, keyed by ``agent_id``."""
    agent_id: int
    is_owned: bool
    positions: deque[tuple[int, Coordinate]] = field(default_factory=deque)
    last_seen_step: int = -1

    def latest(self) -> tuple[int, Coordinate] | None:
        return self.positions[-1] if self.positions else None

    def velocity_estimate(self) -> tuple[float, float] | None:
        """Mean per-step displacement over up to the last 4 entries."""
        if len(self.positions) < 2:
            return None
        recent = list(self.positions)[-4:]
        first_step, first_pos = recent[0]
        last_step, last_pos = recent[-1]
        dt = last_step - first_step
        if dt <= 0:
            return None
        return (
            (last_pos[0] - first_pos[0]) / dt,
            (last_pos[1] - first_pos[1]) / dt,
        )

    def predict(self, future_steps: int) -> Coordinate | None:
        """Linear-extrapolate the next position; snap to integer cell."""
        v = self.velocity_estimate()
        if v is None:
            return None
        latest = self.latest()
        if latest is None:
            return None
        _, last_pos = latest
        return (
            int(round(last_pos[0] + v[0] * future_steps)),
            int(round(last_pos[1] + v[1] * future_steps)),
        )


# ---------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------

@dataclass
class GridNavConfig:
    """All navigation knobs live here. Defaults match
    ``mas_weighted_astar.py`` production values; setting every weight
    to 0 and ``base_terrain_weight=1.0`` reproduces vanilla
    ``policy_base._navigate_to_local`` behavior.
    """

    # --- Spacing radii (manhattan, cells) and per-step repulsion ---
    teammate_spacing: int = 2
    teammate_repulsion: float = 0.0
    stranger_spacing: int = 3
    stranger_repulsion: float = 0.0
    obstacle_spacing: int = 1
    obstacle_repulsion: float = 0.0

    teammate_falloff: str = "linear"
    stranger_falloff: str = "linear"
    obstacle_falloff: str = "linear"

    # Enemy AoE soft repulsion. When >0, cells in
    # ``view.enemy_aoe_locals`` paint a repulsion field with the
    # given weight + spacing so A* skirts hostile territory rather
    # than marching straight through. Default off (0.0) so existing
    # callers keep neutral behavior unless they opt in.
    enemy_aoe_repulsion: float = 0.0
    enemy_aoe_spacing: int = 3
    enemy_aoe_falloff: str = "linear"

    # --- Attractors (caller passes cells per call) ---
    attractor_weight: float = 0.0
    attractor_radius: int = 3
    attractor_falloff: str = "linear"

    # --- Tabu trail (mirrors policy_mas.py:1099-1153) ---
    tabu_strength: float = 0.0
    tabu_length: int = 8
    tabu_radius: int = 0
    tabu_curve: str = "linear"
    tabu_falloff: str = "linear"

    # --- Cost-model floors and clamps ---
    base_terrain_weight: float = 50.0
    cost_floor: float = 1.0
    max_repulsion_per_step: float = 400.0
    max_attraction_per_step: float = 49.0

    max_expansions: int = 5000

    # --- Direct routing tabu. When True, ``next_move(direct
    # =True)`` consults the tabu trail in addition to walls/ships.
    # Without this, a dead/in-hurry cog walking back to the hub
    # follows the same Manhattan-shortest path tick after tick,
    # oscillating in dead-end peninsulas indefinitely. Other
    # repulsion sources (team-trail / strangers / obstacles) stay
    # disabled in direct mode — those are the soft costs we want to
    # bypass when an agent is in a hurry. Only tabu is preserved.
    direct_routing_uses_tabu: bool = True

    # --- Repulsion-grid precompute. When True the per-replan A* call
    # paints each repulsion + attractor source's contribution into a
    # sparse {cell: cost} grid once, and the inner cost_fn does an
    # O(1) dict lookup per neighbor expansion instead of iterating
    # every source. Worst-case per-replan cost drops from
    # O(expansions × 4 × sources) to roughly
    # O(sources × cells_in_radius + expansions × 4). The flag exists
    # so callers can compare the two implementations during
    # validation. ---
    use_repulsion_grid: bool = True

    # --- Soft-buffer wall window: only walls within
    # (obstacle_spacing + this) of obs_center contribute soft cost.
    # Far walls remain hard-blocked. ---
    obstacle_window_radius: int = 8

    # --- Tag classification (filled by caller from tag_name_to_id) ---
    wall_tag_ids: frozenset[int] = frozenset()
    teammate_tag_ids: frozenset[int] = frozenset()
    stranger_tag_ids: frozenset[int] = frozenset()
    extra_blocker_tag_ids: frozenset[int] = frozenset()
    # Cells carrying any of these tag ids are treated as enemy AoE.
    # They get a soft repulsion source so A* routes around hostile
    # zones instead of marching straight through them.
    # AntiClipsPolicy fills this with frozenset({team:clips}) so any
    # clip-aligned cell shows up as enemy territory.
    enemy_aoe_tag_ids: frozenset[int] = frozenset()
    # Cells bearing any of these tags are interactive bump-style objects
    # (hubs, junctions, extractors, stations). Moving INTO them fires
    # the bump handler instead of displacing the agent — so arrival for
    # such a target is at Chebyshev=1, not exact equality. Used by
    # ``is_bump_target`` / ``arrived``.
    bump_target_tag_ids: frozenset[int] = frozenset()

    # --- Heuristic mode: "auto" | "manhattan" | "weighted" | "zero" ---
    heuristic_mode: str = "auto"

    # --- Team-member trails (mirrors policy_base PolicyConfig.team_trail_*) ---
    # Trails are populated by ``record_team_observations``; the resulting
    # repulsors are added by ``_build_repulsion_sources`` whenever any of
    # the trail repulsion knobs is positive.  All defaults are 0 so trail
    # behavior is fully opt-in — setting only ``team_trail_*_repulsion``
    # values to non-zero (and tail counts) activates it.

    # Maximum (step, position) entries retained per track; deque maxlen.
    team_trail_max_length: int = 8

    # Step-based TTL: entries older than (current - this) are dropped on
    # each update; tracks whose latest observation is older than this are
    # removed entirely from ``team_trails``.
    team_trail_ttl: int = 30

    # How many steps ahead ``predict()`` extrapolates each track.  1 =
    # the cell most likely to collide on the next tick.
    team_trail_predict_horizon: int = 1

    # Repulsion at each track's predicted next cell.  Owned weight is
    # typically high (>= ``max_repulsion_per_step`` for an effective hard
    # block); stranger weight is typically lower (e.g. 80 — ~4 cells of
    # detour at base_terrain_weight ≈ 20).
    team_trail_owned_predicted_repulsion: float = 0.0
    team_trail_stranger_predicted_repulsion: float = 0.0

    # How many tail cells (positions[-2] back through positions[-(N+1)])
    # to repel against per track.  tail-1 is the most-recently-vacated
    # cell — the deadlock-fix.  tail-2..N are older.
    team_trail_avoid_tail_owned: int = 0
    team_trail_avoid_tail_stranger: int = 0

    # Repulsion at tail-1.  Set high (>= ``max_repulsion_per_step``) for
    # an effective hard block — the head-on oscillation pattern fix.
    # Per-side splits because owned cogs are predictable while strangers
    # are not, so callers may want different blocking strengths.
    team_trail_owned_tail_hard_repulsion: float = 0.0
    team_trail_stranger_tail_hard_repulsion: float = 0.0

    # Repulsion at tail-2..N (older tail cells).  Single shared weight
    # — these are softer hints, not hard blocks.
    team_trail_tail_soft_repulsion: float = 0.0

    # Spacing radius for trail-derived repulsors.  Default 0 = single-
    # cell sources; raise to 1+ to repel cells adjacent to predicted /
    # tail cells too.
    team_trail_radius: int = 0
    team_trail_falloff: str = "step"


@dataclass
class GridNavView:
    """Per-tick derived view; never persist across ticks."""

    obs_center: Coordinate
    teammate_locals: set[Coordinate] = field(default_factory=set)
    stranger_locals: set[Coordinate] = field(default_factory=set)
    blocker_locals: set[Coordinate] = field(default_factory=set)
    visible_tagged_locals: set[Coordinate] = field(default_factory=set)
    # Cells visible this tick that match config.bump_target_tag_ids —
    # consulted by ``is_bump_target`` / ``arrived``.
    bump_target_locals: set[Coordinate] = field(default_factory=set)
    # Cells visible this tick tagged with any enemy_aoe_tag_ids id.
    # Source for the enemy_aoe repulsion field. Lets the cost-graph
    # make hostile cells expensive to traverse without making them
    # hard-blocked (cogs may need to push through to reach a
    # contested target).
    enemy_aoe_locals: set[Coordinate] = field(default_factory=set)


@dataclass
class GridNavState:
    """Per-agent persistent navigation state. Caller owns one per agent
    for the lifetime of the episode."""

    config: GridNavConfig = field(default_factory=GridNavConfig)

    position: Coordinate = (0, 0)
    blocked: set[Coordinate] = field(default_factory=set)
    visited: set[Coordinate] = field(default_factory=lambda: {(0, 0)})

    position_history: list[Coordinate] = field(default_factory=list)

    last_move_direction: str | None = None
    last_move_succeeded: bool = False
    pending_collision_direction: str | None = None
    step_counter: int = 0

    # Team-member position trails, keyed by agent_id.  Populated by
    # ``record_team_observations`` once per tick.  Consumed by
    # ``_build_repulsion_sources`` to emit predicted-cell and tail-cell
    # repulsors for collision avoidance against teammates and strangers.
    team_trails: dict[int, TeamMemberTrack] = field(default_factory=dict)

    # Cached plan from ``plan_path`` / ``next_move_cached``.  ``cells[0]``
    # is the next cell to enter (i.e. cell *after* current ``position``).
    # ``cached_path_target`` / ``cached_path_detour`` identify the goal +
    # opportunistic POI the cache was planned for; mismatches with the
    # caller-passed values force a replan.  ``cached_path_planned_step``
    # is the value of ``step_counter`` at plan time; the N-step replan
    # timer compares against this.
    cached_path_cells: list[Coordinate] = field(default_factory=list)
    cached_path_target: Coordinate | None = None
    cached_path_detour: Coordinate | None = None
    cached_path_planned_step: int = -1


# ---------------------------------------------------------------------
# Source-list builders
# ---------------------------------------------------------------------

# A source tuple: (center, weight, radius, falloff_name).
_Source = tuple[Coordinate, float, int, str]


def _build_repulsion_sources(
    nav_state: GridNavState,
    view: GridNavView,
    extra_repulsors: Iterable[tuple[Coordinate, float, int]],
) -> list[_Source]:
    cfg = nav_state.config
    sources: list[_Source] = []

    if cfg.teammate_repulsion > 0.0:
        for cell in view.teammate_locals:
            sources.append(
                (cell, cfg.teammate_repulsion, cfg.teammate_spacing, cfg.teammate_falloff)
            )

    if cfg.stranger_repulsion > 0.0:
        for cell in view.stranger_locals:
            sources.append(
                (cell, cfg.stranger_repulsion, cfg.stranger_spacing, cfg.stranger_falloff)
            )

    if cfg.enemy_aoe_repulsion > 0.0:
        for cell in view.enemy_aoe_locals:
            sources.append(
                (cell, cfg.enemy_aoe_repulsion, cfg.enemy_aoe_spacing, cfg.enemy_aoe_falloff)
            )

    if cfg.obstacle_repulsion > 0.0 and cfg.obstacle_spacing > 0:
        # Map obs_center back to local frame of the agent so we can
        # window the wall set.
        delta_r = nav_state.position[0] - view.obs_center[0]
        delta_c = nav_state.position[1] - view.obs_center[1]
        # In local frame, the agent is at ``nav_state.position``; the
        # obs window covers cells within obs_window_radius of it
        # (cheap upper bound for a small obs window).
        win = cfg.obstacle_window_radius + cfg.obstacle_spacing
        ar, ac = nav_state.position
        for wall in nav_state.blocked:
            if abs(wall[0] - ar) > win or abs(wall[1] - ac) > win:
                continue
            sources.append(
                (wall, cfg.obstacle_repulsion, cfg.obstacle_spacing, cfg.obstacle_falloff)
            )
        # delta_r/delta_c silence: kept above to make the local-frame
        # contract explicit, but the windowing uses position directly.
        del delta_r, delta_c

    # Tabu trail: head = newest, decay over index.
    if cfg.tabu_strength > 0.0 and cfg.tabu_length > 0 and nav_state.position_history:
        for i, pos in enumerate(nav_state.position_history[: cfg.tabu_length]):
            decay = _tabu_decay_factor(cfg.tabu_curve, i, cfg.tabu_length)
            w = cfg.tabu_strength * decay
            if w <= 0.0:
                continue
            sources.append((pos, w, cfg.tabu_radius, cfg.tabu_falloff))

    # Team-member trails: predicted next cells + recently-vacated tail
    # cells.  Each track contributes up to (1 + N) repulsors per tick
    # where N is the per-side tail count.  Owned tracks carry a
    # potentially higher weight than strangers (typically a near-hard
    # block; the owned-trail planner is more predictable).  Tail-1 is
    # the head-on-deadlock fix; tail-2..N are softer hints.
    _trail_active = (
        cfg.team_trail_owned_predicted_repulsion > 0.0
        or cfg.team_trail_stranger_predicted_repulsion > 0.0
        or cfg.team_trail_owned_tail_hard_repulsion > 0.0
        or cfg.team_trail_stranger_tail_hard_repulsion > 0.0
        or cfg.team_trail_tail_soft_repulsion > 0.0
    )
    if _trail_active and nav_state.team_trails:
        radius = max(0, cfg.team_trail_radius)
        falloff = cfg.team_trail_falloff
        horizon = max(1, cfg.team_trail_predict_horizon)
        for track in nav_state.team_trails.values():
            # --- Predicted cell ---
            predicted = track.predict(horizon)
            if predicted is not None:
                w = (
                    cfg.team_trail_owned_predicted_repulsion
                    if track.is_owned
                    else cfg.team_trail_stranger_predicted_repulsion
                )
                if w > 0.0:
                    sources.append((predicted, w, radius, falloff))

            # --- Tail cells: positions[-2], positions[-3], ... ---
            n_tail = (
                cfg.team_trail_avoid_tail_owned
                if track.is_owned
                else cfg.team_trail_avoid_tail_stranger
            )
            tail_hard = (
                cfg.team_trail_owned_tail_hard_repulsion
                if track.is_owned
                else cfg.team_trail_stranger_tail_hard_repulsion
            )
            n_positions = len(track.positions)
            # i = 2 -> tail-1, i = 3 -> tail-2, ..., i = n_tail+1 -> tail-N.
            for i in range(2, n_tail + 2):
                if i > n_positions:
                    break
                _, cell = track.positions[-i]
                if i == 2:
                    if tail_hard > 0.0:
                        sources.append((cell, tail_hard, radius, falloff))
                else:
                    soft = cfg.team_trail_tail_soft_repulsion
                    if soft > 0.0:
                        sources.append((cell, soft, radius, falloff))

    for cell, weight, radius in extra_repulsors:
        if weight <= 0.0 or radius < 0:
            continue
        sources.append((cell, float(weight), int(radius), "linear"))

    return sources


def _build_attractor_sources(
    nav_state: GridNavState,
    attractors: Iterable[Coordinate],
) -> list[_Source]:
    cfg = nav_state.config
    if cfg.attractor_weight <= 0.0 or cfg.attractor_radius < 0:
        return []
    sources: list[_Source] = []
    for cell in attractors:
        sources.append(
            (cell, cfg.attractor_weight, cfg.attractor_radius, cfg.attractor_falloff)
        )
    return sources


def _tabu_decay_factor(curve: str, index: int, length: int) -> float:
    if curve == "geometric":
        return 0.5 ** index
    if curve == "constant":
        return 1.0
    # "linear" (default): index 0 -> 1.0, index length-1 -> ~0.
    if length <= 1:
        return 1.0 if index == 0 else 0.0
    return max(0.0, 1.0 - index / float(length))


def _step_cost(
    cell: Coordinate,
    repulsion_sources: list[_Source],
    attractor_sources: list[_Source],
    cfg: GridNavConfig,
) -> float:
    cost = cfg.base_terrain_weight

    rep = 0.0
    for center, weight, radius, falloff_name in repulsion_sources:
        d = _manhattan(cell, center)
        if d > radius:
            continue
        rep += weight * _falloff(falloff_name, float(d), radius)
    if rep > cfg.max_repulsion_per_step:
        rep = cfg.max_repulsion_per_step
    cost += rep

    attr = 0.0
    for center, weight, radius, falloff_name in attractor_sources:
        d = _manhattan(cell, center)
        if d > radius:
            continue
        attr += weight * _falloff(falloff_name, float(d), radius)
    if attr > cfg.max_attraction_per_step:
        attr = cfg.max_attraction_per_step
    cost -= attr

    if cost < cfg.cost_floor:
        cost = cfg.cost_floor
    return cost


def _build_cost_grid(
    repulsion_sources: list[_Source],
    attractor_sources: list[_Source],
    cfg: GridNavConfig,
) -> tuple[dict[Coordinate, float], float]:
    """Paint every source's contribution into a sparse {cell: cost} dict.

    Cells that fall outside every source's radius do not appear in the
    returned dict; they cost ``base_cost`` (the second return value).
    Per-cell ``max_repulsion_per_step`` / ``max_attraction_per_step``
    caps and ``cost_floor`` are applied at grid build time so the
    A*-side ``cost_fn`` becomes an O(1) dict lookup.

    Cost analysis: per source, we paint a
    Manhattan-ball of radius ``r`` (a diamond of ``2r²+2r+1`` cells).
    With ~50 default sources at r ≤ 8, that's ~5 k writes — same scale
    as a single A* expansion under the previous implementation. The
    inner A* loop then drops from O(expansions × 4 × sources) to
    O(expansions × 4) on the cost-evaluation axis.
    """
    rep_grid: dict[Coordinate, float] = {}
    for center, weight, radius, falloff_name in repulsion_sources:
        if weight <= 0.0 or radius < 0:
            continue
        sr, sc = center
        for dr in range(-radius, radius + 1):
            adr = abs(dr)
            row_inner_cap = radius - adr
            for dc in range(-row_inner_cap, row_inner_cap + 1):
                d = adr + abs(dc)
                contribution = weight * _falloff(falloff_name, float(d), radius)
                if contribution <= 0.0:
                    continue
                cell = (sr + dr, sc + dc)
                rep_grid[cell] = rep_grid.get(cell, 0.0) + contribution

    attr_grid: dict[Coordinate, float] = {}
    for center, weight, radius, falloff_name in attractor_sources:
        if weight <= 0.0 or radius < 0:
            continue
        sr, sc = center
        for dr in range(-radius, radius + 1):
            adr = abs(dr)
            row_inner_cap = radius - adr
            for dc in range(-row_inner_cap, row_inner_cap + 1):
                d = adr + abs(dc)
                contribution = weight * _falloff(falloff_name, float(d), radius)
                if contribution <= 0.0:
                    continue
                cell = (sr + dr, sc + dc)
                attr_grid[cell] = attr_grid.get(cell, 0.0) + contribution

    base = cfg.base_terrain_weight
    floor = cfg.cost_floor
    rep_cap = cfg.max_repulsion_per_step
    attr_cap = cfg.max_attraction_per_step
    base_cost = base if base >= floor else floor

    cost_grid: dict[Coordinate, float] = {}
    affected = set(rep_grid)
    affected.update(attr_grid)
    for cell in affected:
        rep = rep_grid.get(cell, 0.0)
        if rep > rep_cap:
            rep = rep_cap
        attr = attr_grid.get(cell, 0.0)
        if attr > attr_cap:
            attr = attr_cap
        cost = base + rep - attr
        if cost < floor:
            cost = floor
        if cost != base_cost:
            cost_grid[cell] = cost
    return cost_grid, base_cost


# ---------------------------------------------------------------------
# A*  (control flow ported from mas_weighted_astar.py:66-190)
# ---------------------------------------------------------------------

def _astar_first_step(
    start: Coordinate,
    goal: Coordinate,
    blocked: set[Coordinate] | frozenset[Coordinate],
    cost_fn: Callable[[Coordinate], float],
    h_fn: Callable[[Coordinate], float],
    max_expansions: int,
    direction_rotation: int = 0,
) -> str | None:
    """A* first-step with optional direction-iteration rotation.

    ``direction_rotation`` (default 0 = legacy N/S/W/E order) rotates
    the MOVE_DELTAS iteration order per agent so multiple agents resolve
    tied-cost path-direction choices to different first-moves. Without
    rotation, N (counter=1) wins ties over S/W/E, propagating into a
    systematic NW pull when summed across the team over an episode.
    """
    if start == goal:
        return None

    if goal in blocked:
        blocked = set(blocked)
        blocked.discard(goal)

    # Compute rotated direction order once per call. Cheap (4-element list).
    _dirs = list(MOVE_DELTAS.items())
    if direction_rotation:
        k = direction_rotation % len(_dirs)
        _dirs = _dirs[k:] + _dirs[:k]

    open_heap: list[tuple[float, int, Coordinate, str | None]] = []
    heapq.heappush(open_heap, (h_fn(start), 0, start, None))
    best_g: dict[Coordinate, float] = {start: 0.0}
    counter = 0
    expansions = 0

    while open_heap and expansions < max_expansions:
        _, _, current, first_dir = heapq.heappop(open_heap)
        expansions += 1

        if current == goal:
            return first_dir

        g_current = best_g.get(current)
        if g_current is None:
            continue

        for direction, (dr, dc) in _dirs:
            nxt: Coordinate = (current[0] + dr, current[1] + dc)
            if nxt in blocked:
                continue

            edge = cost_fn(nxt)
            g_next = g_current + edge
            existing = best_g.get(nxt)
            if existing is not None and existing <= g_next:
                continue
            best_g[nxt] = g_next

            chosen_first = first_dir if first_dir is not None else direction
            counter += 1
            heapq.heappush(
                open_heap,
                (g_next + h_fn(nxt), counter, nxt, chosen_first),
            )

    return None


def _astar_full_path(
    start: Coordinate,
    goal: Coordinate,
    blocked: set[Coordinate] | frozenset[Coordinate],
    cost_fn: Callable[[Coordinate], float],
    h_fn: Callable[[Coordinate], float],
    max_expansions: int,
    direction_rotation: int = 0,
) -> list[Coordinate] | None:
    """Same A* as ``_astar_first_step`` but reconstructs the full path.

    Returns the cell sequence **excluding ``start`` and including ``goal``**.
    Empty list iff ``start == goal``. ``None`` iff unreachable within
    ``max_expansions``. ``direction_rotation`` rotates the neighbor-
    iteration order (see ``_astar_first_step``).
    """
    if start == goal:
        return []

    if goal in blocked:
        blocked = set(blocked)
        blocked.discard(goal)

    _dirs = list(MOVE_DELTAS.items())
    if direction_rotation:
        k = direction_rotation % len(_dirs)
        _dirs = _dirs[k:] + _dirs[:k]

    open_heap: list[tuple[float, int, Coordinate]] = []
    heapq.heappush(open_heap, (h_fn(start), 0, start))
    best_g: dict[Coordinate, float] = {start: 0.0}
    parent: dict[Coordinate, Coordinate] = {}
    counter = 0
    expansions = 0

    while open_heap and expansions < max_expansions:
        _, _, current = heapq.heappop(open_heap)
        expansions += 1

        if current == goal:
            path: list[Coordinate] = []
            node = current
            while node != start:
                path.append(node)
                node = parent[node]
            path.reverse()
            return path

        g_current = best_g.get(current)
        if g_current is None:
            continue

        for _direction, (dr, dc) in _dirs:
            nxt: Coordinate = (current[0] + dr, current[1] + dc)
            if nxt in blocked:
                continue

            edge = cost_fn(nxt)
            g_next = g_current + edge
            existing = best_g.get(nxt)
            if existing is not None and existing <= g_next:
                continue
            best_g[nxt] = g_next
            parent[nxt] = current

            counter += 1
            heapq.heappush(
                open_heap,
                (g_next + h_fn(nxt), counter, nxt),
            )

    return None


# ---------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------

def update_position(
    nav_state: GridNavState,
    last_move_direction: str | None,
    last_move_succeeded: bool,
    failed_into_wall: bool = False,
    failed_into_agent: bool = False,
) -> None:
    """Fold the previous move attempt into ``position``/``blocked``.

    The caller is responsible for resolving ``last_move_succeeded``
    (typically from a ``last_action_move`` token) and ``failed_into_*``
    (typically from inspecting the tag set at the attempted destination).
    """
    nav_state.last_move_direction = last_move_direction
    nav_state.last_move_succeeded = last_move_succeeded

    if last_move_direction is None:
        return
    if last_move_direction not in MOVE_DELTAS:
        return

    dr, dc = MOVE_DELTAS[last_move_direction]
    attempted_local: Coordinate = (
        nav_state.position[0] + dr,
        nav_state.position[1] + dc,
    )
    if last_move_succeeded:
        nav_state.position = attempted_local
        nav_state.visited.add(attempted_local)
        nav_state.pending_collision_direction = None
    else:
        if failed_into_wall:
            nav_state.blocked.add(attempted_local)
        elif failed_into_agent:
            nav_state.pending_collision_direction = last_move_direction


def observe(
    nav_state: GridNavState,
    frozen_tags: dict[Coordinate, frozenset[int]],
    obs_center: Coordinate,
) -> GridNavView:
    """Fold visible walls into ``nav_state.blocked`` and classify
    visible entities into the per-tick view.

    All output coords are in the agent's local frame.
    """
    cfg = nav_state.config
    view = GridNavView(obs_center=obs_center)

    pos = nav_state.position
    cr, cc = obs_center
    for obs_loc, tag_ids in frozen_tags.items():
        local: Coordinate = (
            pos[0] + obs_loc[0] - cr,
            pos[1] + obs_loc[1] - cc,
        )

        if obs_loc == obs_center:
            # Agent's own cell — never marked blocked.
            continue

        if tag_ids:
            view.visible_tagged_locals.add(local)

        if cfg.wall_tag_ids and (tag_ids & cfg.wall_tag_ids):
            nav_state.blocked.add(local)
            view.blocker_locals.add(local)
            continue

        if cfg.teammate_tag_ids and (tag_ids & cfg.teammate_tag_ids):
            view.teammate_locals.add(local)
        if cfg.stranger_tag_ids and (tag_ids & cfg.stranger_tag_ids):
            view.stranger_locals.add(local)
        if cfg.extra_blocker_tag_ids and (tag_ids & cfg.extra_blocker_tag_ids):
            view.blocker_locals.add(local)
        if cfg.bump_target_tag_ids and (tag_ids & cfg.bump_target_tag_ids):
            view.bump_target_locals.add(local)
        if cfg.enemy_aoe_tag_ids and (tag_ids & cfg.enemy_aoe_tag_ids):
            view.enemy_aoe_locals.add(local)

    return view


def record_team_observations(
    nav_state: GridNavState,
    frozen_tags: dict[Coordinate, frozenset[int]],
    agent_id_at: dict[Coordinate, int],
    own_team_tag_ids: frozenset[int],
    agent_tag_id: int | None,
    owned_agent_ids: frozenset[int],
    step: int,
    obs_center: Coordinate,
    self_agent_id: int | None = None,
) -> None:
    """Append this tick's observed team-member positions to the trails on
    ``nav_state.team_trails``.  Sibling of :func:`observe`; call once per
    tick after :func:`update_position` and :func:`observe`.

    For every cell in ``frozen_tags`` whose tag set contains
    ``agent_tag_id`` and intersects ``own_team_tag_ids``, looks up the
    cell's ``agent_id`` from ``agent_id_at`` (typically built by the caller
    with a one-line scan over ``obs.tokens`` filtering on
    ``feature.name == "agent_id"`` — same extraction pattern as
    ``policy_stranger.py:150-151``), converts obs-window coords to local
    frame, and updates the corresponding ``TeamMemberTrack``.

    Pass ``self_agent_id`` to skip the calling agent's own track —
    typically the goal is to avoid teammates, not yourself.

    No-op when none of the trail repulsion knobs is positive.  Honors
    ``team_trail_max_length`` and ``team_trail_ttl``.
    """
    cfg = nav_state.config
    if agent_tag_id is None:
        return
    # Cheap early-out: if no trail repulsion is active, skip recording.
    if (
        cfg.team_trail_owned_predicted_repulsion <= 0.0
        and cfg.team_trail_stranger_predicted_repulsion <= 0.0
        and cfg.team_trail_owned_tail_hard_repulsion <= 0.0
        and cfg.team_trail_stranger_tail_hard_repulsion <= 0.0
        and cfg.team_trail_tail_soft_repulsion <= 0.0
    ):
        return

    max_len = max(1, cfg.team_trail_max_length)
    ttl = max(1, cfg.team_trail_ttl)
    cutoff = step - ttl

    pos = nav_state.position
    cr, cc = obs_center
    for obs_loc, tag_ids in frozen_tags.items():
        if agent_tag_id not in tag_ids:
            continue
        if not (tag_ids & own_team_tag_ids):
            continue
        aid = agent_id_at.get(obs_loc)
        if aid is None:
            continue
        if self_agent_id is not None and aid == self_agent_id:
            continue
        local: Coordinate = (
            pos[0] + obs_loc[0] - cr,
            pos[1] + obs_loc[1] - cc,
        )

        track = nav_state.team_trails.get(aid)
        is_owned = aid in owned_agent_ids
        if track is None or track.positions.maxlen != max_len:
            old = list(track.positions) if track is not None else []
            new_positions: deque[tuple[int, Coordinate]] = deque(
                old, maxlen=max_len
            )
            if track is None:
                track = TeamMemberTrack(
                    agent_id=aid,
                    is_owned=is_owned,
                    positions=new_positions,
                    last_seen_step=step,
                )
                nav_state.team_trails[aid] = track
            else:
                track.positions = new_positions
                track.is_owned = is_owned
        else:
            track.is_owned = is_owned

        # Avoid double-append within a single step.
        if track.positions and track.positions[-1][0] == step:
            track.positions[-1] = (step, local)
        else:
            track.positions.append((step, local))
        track.last_seen_step = step

        # Step-TTL trim within this track.
        while track.positions and track.positions[0][0] < cutoff:
            track.positions.popleft()

    # Drop tracks whose latest observation is older than the TTL.
    stale = [
        aid for aid, track in nav_state.team_trails.items()
        if (step - track.last_seen_step) > ttl
    ]
    for aid in stale:
        del nav_state.team_trails[aid]


def next_move(
    nav_state: GridNavState,
    view: GridNavView,
    target_local: Coordinate,
    *,
    attractors: Iterable[Coordinate] = (),
    repulsors: Iterable[tuple[Coordinate, float, int]] = (),
    direct: bool = False,
    use_tabu: bool = True,
    respects_enemy_aoe: bool = False,
    direction_rotation: int = 0,
) -> str | None:
    """Return a direction name from ``MOVE_DELTAS`` toward
    ``target_local``, or ``None`` if no path is found within budget.

    Callers wrap the result in ``Action(name=f"move_{direction}")``.
    A return of ``None`` means: caller should noop, wander, or pick a
    different goal — wander policy is intentionally NOT in this module.

    When ``direct=True``, switch to geometry-only routing: walls and
    extra-blockers (ships) are unwalkable; everything else is walkable.
    No potential fields, no team-trail, no ``nav.blocked``. Used for
    in-a-hurry paths (retreat, regear_retreat) where soft fields waste
    ticks and accumulated blocked cells lock the agent.

    When both ``direct=True`` and ``cfg.direct_routing_uses_tabu``
    (default True) are set, the trail tabu is still consulted. Pass
    ``use_tabu=False`` to bypass that —
    callers running long-distance return-to-hub paths typically want
    this off, since accumulated trail cells form a wall behind the
    agent and can trap them in circles in neutral / enemy space when
    they need to backtrack.
    """
    cfg = nav_state.config
    start = nav_state.position
    goal = target_local

    if start == goal:
        return None

    if direct:
        # Geometry-only: only walls + ships (view.blocker_locals)
        # block. Drop nav.blocked, soft fields, attractors. Uniform
        # cost, pure Manhattan heuristic.
        direct_blocked: set[Coordinate] = set(view.blocker_locals)
        direct_blocked.discard(start)

        # When ``direct_routing_uses_tabu`` is enabled, build a
        # minimal repulsion grid containing only tabu sources. This
        # keeps the in-hurry path geometry-only for teammate / stranger
        # / obstacle / team-trail (those soft costs are exactly what
        # ``direct=True`` is meant to bypass) while still letting the
        # cog avoid cells it just oscillated through. Without tabu the
        # in-hurry path picks the same Manhattan-shortest first step
        # every tick, which traps dead cogs in dead-end peninsulas.
        # Build a minimal soft-cost grid for the direct path:
        #   - tabu sources, gated on direct_routing_uses_tabu +
        #     use_tabu + tabu_strength.
        #   - enemy_aoe sources, gated on respects_enemy_aoe +
        #     enemy_aoe_repulsion. Lets a retreating cog detour around
        #     clip-aligned cells (-2 HP/tick in clip territory) instead
        #     of taking the geodesically-shortest path through them.
        #     Other soft costs (teammate / stranger / obstacle / team-
        #     trail) stay disabled per the existing direct-mode rationale.
        soft_sources: list[_Source] = []
        if cfg.direct_routing_uses_tabu and use_tabu and cfg.tabu_strength > 0.0:
            if cfg.tabu_length > 0 and nav_state.position_history:
                for i, p in enumerate(nav_state.position_history[: cfg.tabu_length]):
                    decay = _tabu_decay_factor(cfg.tabu_curve, i, cfg.tabu_length)
                    w = cfg.tabu_strength * decay
                    if w <= 0.0:
                        continue
                    soft_sources.append((p, w, cfg.tabu_radius, cfg.tabu_falloff))
        if respects_enemy_aoe and cfg.enemy_aoe_repulsion > 0.0:
            for cell in view.enemy_aoe_locals:
                soft_sources.append(
                    (cell, cfg.enemy_aoe_repulsion, cfg.enemy_aoe_spacing, cfg.enemy_aoe_falloff)
                )
        if soft_sources:
            soft_grid, soft_base = _build_cost_grid(soft_sources, [], cfg)
            def direct_cost_fn(c: Coordinate, _g=soft_grid, _b=soft_base) -> float:
                return _g.get(c, _b)
        else:
            def direct_cost_fn(_c: Coordinate) -> float:
                return 1.0

        def direct_h_fn(c: Coordinate, _g=goal) -> float:
            return float(abs(c[0] - _g[0]) + abs(c[1] - _g[1]))

        return _astar_first_step(
            start=start,
            goal=goal,
            blocked=direct_blocked,
            cost_fn=direct_cost_fn,
            h_fn=direct_h_fn,
            max_expansions=cfg.max_expansions,
            direction_rotation=direction_rotation,
        )

    # Hard-blocked cells: persistent walls + every visible tagged cell
    # this tick (mirroring policy_base._navigate_to_local). Goal is
    # exempted by _astar_first_step.
    blocked: set[Coordinate] = set(nav_state.blocked)
    blocked.update(view.visible_tagged_locals)
    blocked.update(view.blocker_locals)
    blocked.discard(start)  # never block our own cell

    attractors_list = list(attractors)
    repulsion_sources = _build_repulsion_sources(nav_state, view, repulsors)
    attractor_sources = _build_attractor_sources(nav_state, attractors_list)

    has_attractors = bool(attractor_sources)

    if cfg.use_repulsion_grid:
        cost_grid, base_cost = _build_cost_grid(
            repulsion_sources, attractor_sources, cfg,
        )
        def cost_fn(c: Coordinate, _g=cost_grid, _b=base_cost) -> float:
            return _g.get(c, _b)
    else:
        def cost_fn(c: Coordinate) -> float:
            return _step_cost(c, repulsion_sources, attractor_sources, cfg)

    mode = cfg.heuristic_mode
    if mode == "auto":
        mode = "zero" if has_attractors else "manhattan"

    base = cfg.base_terrain_weight
    if mode == "zero":
        def h_fn(_: Coordinate) -> float:
            return 0.0
    elif mode in ("manhattan", "weighted"):
        def h_fn(c: Coordinate, _g=goal, _b=base) -> float:
            return _b * (abs(c[0] - _g[0]) + abs(c[1] - _g[1]))
    else:
        # Unknown mode: behave like "auto" -> safe choice.
        if has_attractors:
            def h_fn(_: Coordinate) -> float:
                return 0.0
        else:
            def h_fn(c: Coordinate, _g=goal, _b=base) -> float:
                return _b * (abs(c[0] - _g[0]) + abs(c[1] - _g[1]))

    return _astar_first_step(
        start=start,
        goal=goal,
        blocked=blocked,
        cost_fn=cost_fn,
        h_fn=h_fn,
        max_expansions=cfg.max_expansions,
        direction_rotation=direction_rotation,
    )


# ---------------------------------------------------------------------
# Detour-aware planning + plan caching (sibling of ``next_move``)
# ---------------------------------------------------------------------
#
# ``plan_path`` returns the full cell sequence for a route, optionally
# routing via a one-shot detour POI when the via-detour path adds at
# most ``max_detour_steps`` extra steps over the direct path.  The
# step count is ``len(path)`` — actual cells, not cost-shaped g-values.
#
# ``next_move_cached`` rides that plan across ticks: callers can issue
# one move per tick from a single plan, replanning only when the plan
# is invalidated (failed move, newly-blocked next cell, drift, target
# or detour change, or every N successful steps via ``replan_every``).
#
# Neither function mutates the existing ``next_move`` code path; the
# vanilla-A*-identity smoke test (scenario 11) is unaffected.

def _build_search_blocked_and_cost(
    nav_state: GridNavState,
    view: GridNavView,
    attractors: Iterable[Coordinate],
    repulsors: Iterable[tuple[Coordinate, float, int]],
) -> tuple[set[Coordinate], Callable[[Coordinate], float], float, bool, str]:
    """Shared setup for full-path planners.  Returns
    ``(blocked, cost_fn, base_terrain_weight, has_attractors, resolved_heuristic_mode)``.

    The blocked set already excludes ``nav_state.position``.  The mode
    string is one of ``"manhattan"``, ``"zero"``, ``"weighted"`` (i.e.
    ``"auto"`` is resolved to one of the others based on attractor
    presence).
    """
    cfg = nav_state.config
    start = nav_state.position

    blocked: set[Coordinate] = set(nav_state.blocked)
    blocked.update(view.visible_tagged_locals)
    blocked.update(view.blocker_locals)
    blocked.discard(start)

    attractors_list = list(attractors)
    repulsion_sources = _build_repulsion_sources(nav_state, view, repulsors)
    attractor_sources = _build_attractor_sources(nav_state, attractors_list)
    has_attractors = bool(attractor_sources)

    if cfg.use_repulsion_grid:
        cost_grid, base_cost = _build_cost_grid(
            repulsion_sources, attractor_sources, cfg,
        )
        def cost_fn(c: Coordinate, _g=cost_grid, _b=base_cost) -> float:
            return _g.get(c, _b)
    else:
        def cost_fn(c: Coordinate) -> float:
            return _step_cost(c, repulsion_sources, attractor_sources, cfg)

    mode = cfg.heuristic_mode
    if mode == "auto":
        mode = "zero" if has_attractors else "manhattan"
    elif mode not in ("manhattan", "weighted", "zero"):
        # Unknown mode: behave like "auto".
        mode = "zero" if has_attractors else "manhattan"

    return blocked, cost_fn, cfg.base_terrain_weight, has_attractors, mode


def _make_h_fn(
    goal: Coordinate, base: float, mode: str
) -> Callable[[Coordinate], float]:
    if mode == "zero":
        def h_zero(_: Coordinate) -> float:
            return 0.0
        return h_zero
    # "manhattan" or "weighted" — both Manhattan times base.
    def h_manhattan(c: Coordinate, _g=goal, _b=base) -> float:
        return _b * (abs(c[0] - _g[0]) + abs(c[1] - _g[1]))
    return h_manhattan


def plan_path(
    nav_state: GridNavState,
    view: GridNavView,
    target_local: Coordinate,
    *,
    detour: Coordinate | None = None,
    max_detour_steps: int = 0,
    attractors: Iterable[Coordinate] = (),
    repulsors: Iterable[tuple[Coordinate, float, int]] = (),
    direction_rotation: int = 0,
) -> list[Coordinate] | None:
    """Plan a full path from ``nav_state.position`` to ``target_local``.

    If ``detour`` is given and the via-detour path adds at most
    ``max_detour_steps`` steps over the direct path
    (``len(via) - len(direct) <= max_detour_steps``), the returned path
    routes through ``detour``.  Otherwise the direct path is returned.

    Returns the cell sequence **excluding the start, including the goal**.
    Empty list iff already at the target.  ``None`` iff no path is found
    within ``cfg.max_expansions`` (per-leg budget).

    Step counts use ``len(path)`` — actual cells walked, not the
    cost-shaped g-value.  This matches the user-facing "in steps"
    contract.
    """
    cfg = nav_state.config
    start = nav_state.position

    if start == target_local:
        return []

    blocked, cost_fn, base, _has_attr, mode = _build_search_blocked_and_cost(
        nav_state, view, attractors, repulsors
    )

    direct = _astar_full_path(
        start=start,
        goal=target_local,
        blocked=blocked,
        cost_fn=cost_fn,
        h_fn=_make_h_fn(target_local, base, mode),
        max_expansions=cfg.max_expansions,
        direction_rotation=direction_rotation,
    )

    if detour is None:
        return direct

    # Detour-on-self collapses to direct.
    if detour == start or detour == target_local:
        return direct

    leg_a = _astar_full_path(
        start=start,
        goal=detour,
        blocked=blocked,
        cost_fn=cost_fn,
        h_fn=_make_h_fn(detour, base, mode),
        max_expansions=cfg.max_expansions,
        direction_rotation=direction_rotation,
    )
    if leg_a is None:
        return direct

    leg_b = _astar_full_path(
        start=detour,
        goal=target_local,
        blocked=blocked,
        cost_fn=cost_fn,
        h_fn=_make_h_fn(target_local, base, mode),
        max_expansions=cfg.max_expansions,
        direction_rotation=direction_rotation,
    )
    if leg_b is None:
        return direct

    via_steps = len(leg_a) + len(leg_b)
    if direct is None:
        # No direct path but a via-detour path exists — take it.  (Caller
        # asked for a budget, but absent a baseline it cannot be
        # exceeded.)
        return leg_a + leg_b

    if via_steps - len(direct) <= max_detour_steps:
        return leg_a + leg_b
    return direct


def _direction_from_delta(delta: Coordinate) -> str | None:
    for name, d in MOVE_DELTAS.items():
        if d == delta:
            return name
    return None


def next_move_cached(
    nav_state: GridNavState,
    view: GridNavView,
    target_local: Coordinate,
    *,
    detour: Coordinate | None = None,
    max_detour_steps: int = 0,
    replan_every: int = 10,
    attractors: Iterable[Coordinate] = (),
    repulsors: Iterable[tuple[Coordinate, float, int]] = (),
    direction_rotation: int = 0,
) -> str | None:
    """Return the next direction along a cached plan, replanning when
    the plan is invalidated.

    Replans iff any of:
      * cache is empty,
      * ``target_local`` differs from ``cached_path_target`` or
        ``detour`` differs from ``cached_path_detour``,
      * the previous attempted move failed
        (``last_move_succeeded is False`` and ``last_move_direction``
        is not None — standing-noop ticks don't trigger replan),
      * the next cached cell is now in the blocked set
        (``nav_state.blocked`` ∪ ``view.visible_tagged_locals`` ∪
        ``view.blocker_locals``),
      * the agent has drifted off plan (the cached cell isn't
        cardinally adjacent to ``nav_state.position``),
      * ``step_counter - cached_path_planned_step >= replan_every``.

    Otherwise pops one cell off the cache and returns the corresponding
    direction.  Returns ``None`` if no path exists within the planner
    budget — caller falls back to wander/sidestep.

    This function does NOT call ``update_position`` or ``record_step``;
    the per-tick caller contract documented at the module level still
    applies.  ``next_move_cached`` substitutes for step 3 only.
    """
    start = nav_state.position

    if start == target_local:
        # Trivially at the goal: clear cache so that next call with a
        # different target replans cleanly.
        nav_state.cached_path_cells = []
        nav_state.cached_path_target = target_local
        nav_state.cached_path_detour = detour
        return None

    must_replan = False

    if not nav_state.cached_path_cells:
        must_replan = True
    elif (
        nav_state.cached_path_target != target_local
        or nav_state.cached_path_detour != detour
    ):
        must_replan = True
    elif (
        nav_state.last_move_direction is not None
        and not nav_state.last_move_succeeded
    ):
        must_replan = True
    elif (nav_state.step_counter - nav_state.cached_path_planned_step) >= max(
        1, replan_every
    ):
        must_replan = True
    else:
        next_cell = nav_state.cached_path_cells[0]
        # Drift check: next cached cell must be cardinally adjacent to
        # current position (i.e. position is the planned predecessor).
        delta = (next_cell[0] - start[0], next_cell[1] - start[1])
        if _direction_from_delta(delta) is None:
            must_replan = True
        else:
            # Newly-blocked next cell.
            if (
                next_cell in nav_state.blocked
                or next_cell in view.visible_tagged_locals
                or next_cell in view.blocker_locals
            ):
                must_replan = True

    if must_replan:
        plan = plan_path(
            nav_state,
            view,
            target_local,
            detour=detour,
            max_detour_steps=max_detour_steps,
            attractors=attractors,
            repulsors=repulsors,
            direction_rotation=direction_rotation,
        )
        if not plan:
            # Either unreachable (None) or already at target ([]).
            nav_state.cached_path_cells = []
            nav_state.cached_path_target = target_local
            nav_state.cached_path_detour = detour
            nav_state.cached_path_planned_step = nav_state.step_counter
            return None
        nav_state.cached_path_cells = list(plan)
        nav_state.cached_path_target = target_local
        nav_state.cached_path_detour = detour
        nav_state.cached_path_planned_step = nav_state.step_counter

    next_cell = nav_state.cached_path_cells[0]
    delta = (next_cell[0] - start[0], next_cell[1] - start[1])
    direction = _direction_from_delta(delta)
    if direction is None:
        # Cache corrupt vs. position.  Replan once and retry.
        plan = plan_path(
            nav_state,
            view,
            target_local,
            detour=detour,
            max_detour_steps=max_detour_steps,
            attractors=attractors,
            repulsors=repulsors,
            direction_rotation=direction_rotation,
        )
        if not plan:
            nav_state.cached_path_cells = []
            nav_state.cached_path_target = target_local
            nav_state.cached_path_detour = detour
            nav_state.cached_path_planned_step = nav_state.step_counter
            return None
        nav_state.cached_path_cells = list(plan)
        nav_state.cached_path_target = target_local
        nav_state.cached_path_detour = detour
        nav_state.cached_path_planned_step = nav_state.step_counter
        next_cell = nav_state.cached_path_cells[0]
        delta = (next_cell[0] - start[0], next_cell[1] - start[1])
        direction = _direction_from_delta(delta)
        if direction is None:
            return None

    # Pop the consumed cell.  If the move succeeds, the next tick's
    # ``update_position`` advances ``position`` to ``next_cell``, and
    # the new ``cached_path_cells[0]`` will again be cardinally
    # adjacent.  If it fails, the failed-move replan trigger fires.
    nav_state.cached_path_cells.pop(0)
    return direction


def record_step(nav_state: GridNavState) -> None:
    """Push the current position onto the tabu trail. Idempotent under
    standing still: only inserts when ``position`` changed since the
    last record (mirrors ``policy_mas.py:1139``).
    """
    cfg = nav_state.config
    nav_state.step_counter += 1

    if cfg.tabu_strength <= 0.0 and cfg.tabu_length <= 0:
        return

    history = nav_state.position_history
    cur = nav_state.position
    if not history or history[0] != cur:
        history.insert(0, cur)
    # Truncate to configured length.
    del history[cfg.tabu_length:]


def try_sidestep(
    nav_state: GridNavState,
    view: GridNavView,
    failed_direction: str,
    *,
    direct: bool = False,
) -> str | None:
    """Right-of, then left-of the failed direction. Returns the chosen
    direction or ``None`` if both perpendiculars are blocked.

    When ``direct=True``, only walls + ships block — ignore
    ``nav.blocked`` and soft visible-tagged repulsion, matching
    ``next_move(direct=True)``.
    """
    if failed_direction not in RIGHT_OF:
        return None

    pos = nav_state.position
    if direct:
        blocked = set(view.blocker_locals)
    else:
        blocked = nav_state.blocked | view.visible_tagged_locals | view.blocker_locals

    for cand in (RIGHT_OF[failed_direction], LEFT_OF[failed_direction]):
        dr, dc = MOVE_DELTAS[cand]
        nxt = (pos[0] + dr, pos[1] + dc)
        if nxt in blocked:
            continue
        return cand
    return None


def is_bump_target(
    target: Coordinate,
    view: GridNavView,
) -> bool:
    """True iff the target is an interactive bump-style object
    (hub, junction, extractor, station). Such cells block displacement
    so the policy 'arrives' at Chebyshev=1, not exact equality.

    Returns False for cells outside the current observation window —
    targets observed long ago aren't classifiable from the per-tick
    view. Callers can rely on the bump-target tags being repopulated
    when the agent walks within view of the target again, well before
    arrival becomes a question (Chebyshev<=1 puts the target inside
    a 3x3 around the agent, comfortably inside the obs window).
    """
    return target in view.bump_target_locals


def arrived(
    nav_state: GridNavState,
    target: Coordinate,
    view: GridNavView,
) -> bool:
    """Has the agent reached ``target``?

    For bump-style cells (interactive objects that block displacement),
    Manhattan<=1 counts as arrival — env movement is 4-connected, so
    only orthogonal neighbors can fire the bump on this tick.
    Diagonals (Cheb=1, Manhattan=2) need one more step first. For
    walkable cells, requires exact position equality.
    """
    pos = nav_state.position
    if pos == target:
        return True
    if is_bump_target(target, view):
        return abs(target[0] - pos[0]) + abs(target[1] - pos[1]) <= 1
    return False
