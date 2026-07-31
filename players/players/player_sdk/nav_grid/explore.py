"""explore.py — Reusable exploration strategies.

Origin: extracted from Ron Dahlgren's (swgy) agent libraries
(sm-policies scripted stack; original module name ``swgy_explore.py``).

Each strategy is a pure function with signature::

    (explore_state, view, cfg, **strategy_kwargs) -> Coordinate | None

The returned local-frame coordinate is a *target* the caller hands to
``core.next_move``. ``None`` means the strategy declined (caller
falls back to another strategy or to a safe noop). Strategies do not
call ``next_move`` themselves — they decide *where*, not *how*. Cost
shaping (repulsion / attraction / tabu) stays in ``core``.

Strategies provided
-------------------
* :func:`frontier_bfs`      — nearest unobserved-or-stale cell.
* :func:`sector_assignment` — pick a frontier inside the agent's
  assigned sector; recall toward sector if too far out.
* :func:`spiral`             — deterministic outward spiral from anchor.
* :func:`poi_patrol`         — oldest stale POI, capped by chase
  distance.
* :func:`biased_wander`      — adjacent step in the configured wander
  rotation, optionally biased by a direction vector. Returns the
  *adjacent* cell, not a far target — caller will move one step.

Map memory contract
-------------------
Strategies read ``core.GridNavState.blocked`` and ``visited`` for
walls/coverage. Per-cell staleness lives on the per-agent
``ExploreState.cell_last_seen`` dict, fed by :func:`note_observed`
once per tick (typically right after ``core.observe``). POIs are
caller-supplied — this module does not re-implement ``MapMemory``.

Coordinate frame: same local frame as ``GridNavState`` (agent spawn =
``(0, 0)``). Sector partitioning may use a hub-relative anchor when
the caller provides one; otherwise it falls back to spawn-relative.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Iterable

from .distance import manhattan as _manhattan  # canonical metric

from .core import (
    MOVE_DELTAS,
    WANDER_DIRECTIONS,
    Coordinate,
    GridNavState,
    GridNavView,
)

# ---------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------

@dataclass
class ExploreConfig:
    """All knobs for every strategy. Strategy-specific fields are
    grouped; defaults make each strategy individually usable.
    """

    # ----- Frontier BFS -----
    revisit_after_steps: int = 60      # cell counted as unseen if older than this
    frontier_max_distance: int = 40    # ignore frontier cells farther than this
    frontier_max_candidates: int = 32  # cap on candidates evaluated
    frontier_max_bfs_expansions: int = 4096

    # ----- Sector assignment -----
    sector_count: int = 0              # 0 disables sector logic
    sector_anchor: str = "hub"         # "hub" or "spawn"
    sector_return_threshold: int = 8   # how far outside sector before recall

    # ----- Spiral -----
    spiral_anchor: str = "spawn"       # "hub" or "spawn"
    spiral_max_radius: int = 30
    spiral_clockwise: bool = True

    # ----- POI patrol -----
    poi_stale_threshold: int = 50      # min age before a POI is "stale"
    poi_max_chase_distance: int = 48   # mirrors policy_base.MAX_POI_CHASE_DISTANCE

    # ----- Biased wander -----
    wander_bias_vector: tuple[int, int] | None = None
    wander_bias_strength: float = 0.0  # 0 = pure rotation, 1 = always bias

    # ----- Generic -----
    stuck_threshold: int = 8


# ---------------------------------------------------------------------
# Per-agent state
# ---------------------------------------------------------------------

@dataclass
class ExploreState:
    """Per-agent persistent exploration state. One per agent for the
    episode lifetime."""

    # Step at which each cell was last observed (caller fills via
    # ``note_observed``). Used by frontier and sector strategies to
    # decide when a cell is stale enough to count as "unseen".
    cell_last_seen: dict[Coordinate, int] = field(default_factory=dict)

    # Sector index assigned to this agent (0..sector_count-1), or None.
    sector_index: int | None = None

    # Spiral cursor: (radius, side, step) — see :func:`spiral`.
    spiral_cursor: tuple[int, int, int] = (1, 0, 0)
    spiral_anchor_local: Coordinate | None = None

    # Stuck detection: position the last time progress was made and
    # the step at which it was recorded.
    last_progress_position: Coordinate | None = None
    last_progress_step: int = 0

    # Optional cached frontier target so consecutive ticks don't
    # recompute from scratch (caller invalidates by clearing it).
    cached_frontier_target: Coordinate | None = None
    cached_frontier_step: int = -1


# ---------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------



def note_observed(
    explore_state: ExploreState,
    view: GridNavView,
    nav_state: GridNavState,
    step: int,
) -> None:
    """Record every visible cell as observed at ``step``.

    Call once per tick after ``core.observe``. Cells not in
    ``cell_last_seen`` are unseen; cells whose last-seen step is older
    than ``cfg.revisit_after_steps`` are treated as stale by the
    frontier strategy.

    Visibility is the obs window (13x13 in CvC); we approximate by
    enumerating a 13x13 square around ``view.obs_center`` mapped back
    to local frame. A tighter Chebyshev disk could be used but the
    extra cells just record sooner.
    """
    cr, cc = view.obs_center
    pr, pc = nav_state.position
    half = 6  # 13x13 window
    for dr in range(-half, half + 1):
        for dc in range(-half, half + 1):
            local = (pr + dr, pc + dc)
            explore_state.cell_last_seen[local] = step
    # cr/cc retained for documentation; obs_center could differ from
    # the agent's center if the caller passes a non-centered window.
    del cr, cc


def _is_stale(
    cell: Coordinate,
    explore_state: ExploreState,
    step: int,
    cfg: ExploreConfig,
) -> bool:
    last = explore_state.cell_last_seen.get(cell)
    if last is None:
        return True
    return (step - last) >= cfg.revisit_after_steps


def _sector_of(
    cell: Coordinate,
    anchor: Coordinate,
    sector_count: int,
) -> int:
    """Bearing-based sector. Sectors are equal angular wedges around
    ``anchor``, starting east and going clockwise (matches screen
    coords: row+ is south)."""
    if sector_count <= 1:
        return 0
    dr = cell[0] - anchor[0]
    dc = cell[1] - anchor[1]
    if dr == 0 and dc == 0:
        return 0
    # Atan2-free integer sector via cross/dot signs is fragile for
    # arbitrary sector_count; use float atan2 for simplicity. Maps
    # rarely have >8 sectors anyway.
    import math
    angle = math.atan2(dr, dc)  # -pi..pi, 0 = east
    if angle < 0:
        angle += 2 * math.pi
    sector = int(angle / (2 * math.pi) * sector_count)
    if sector >= sector_count:
        sector = sector_count - 1
    return sector


# ---------------------------------------------------------------------
# Strategy: frontier BFS
# ---------------------------------------------------------------------

def frontier_bfs(
    explore_state: ExploreState,
    view: GridNavView,
    nav_state: GridNavState,
    cfg: ExploreConfig,
    step: int,
) -> Coordinate | None:
    """BFS outward from agent position; return the nearest cell that
    is unobserved or stale, an observed neighbor of which is reachable.

    A "frontier cell" is an unseen-or-stale cell adjacent to a known
    passable cell. We pick the closest one in BFS order, which on a
    4-connected grid is also the closest in Manhattan distance.
    """
    start = nav_state.position
    blocked = nav_state.blocked

    # Cheap reject: agent's own cell counts as observed by definition.
    queue: deque[tuple[Coordinate, int]] = deque([(start, 0)])
    seen: set[Coordinate] = {start}
    candidates: list[tuple[int, Coordinate]] = []

    expansions = 0
    while queue and expansions < cfg.frontier_max_bfs_expansions:
        cell, dist = queue.popleft()
        expansions += 1
        if dist > cfg.frontier_max_distance:
            continue
        for dr, dc in MOVE_DELTAS.values():
            nxt = (cell[0] + dr, cell[1] + dc)
            if nxt in seen:
                continue
            seen.add(nxt)
            if nxt in blocked:
                continue
            if _is_stale(nxt, explore_state, step, cfg):
                candidates.append((dist + 1, nxt))
                if len(candidates) >= cfg.frontier_max_candidates:
                    break
                continue
            queue.append((nxt, dist + 1))
        if len(candidates) >= cfg.frontier_max_candidates:
            break

    if not candidates:
        return None

    candidates.sort(key=lambda x: (x[0], x[1][0], x[1][1]))
    return candidates[0][1]


# ---------------------------------------------------------------------
# Strategy: sector assignment
# ---------------------------------------------------------------------

def sector_assignment(
    explore_state: ExploreState,
    view: GridNavView,
    nav_state: GridNavState,
    cfg: ExploreConfig,
    step: int,
    *,
    agent_id: int,
    hub_local: Coordinate | None = None,
) -> Coordinate | None:
    """Frontier exploration restricted to the agent's assigned sector.

    Sector index = ``agent_id mod cfg.sector_count``. Anchor is
    ``hub_local`` if provided and ``cfg.sector_anchor == "hub"``,
    otherwise spawn ``(0, 0)``.

    If the agent is more than ``cfg.sector_return_threshold`` cells
    outside its sector, we recall it: target the anchor itself so the
    caller routes back through friendly territory.
    """
    if cfg.sector_count <= 0:
        return frontier_bfs(explore_state, view, nav_state, cfg, step)

    if cfg.sector_anchor == "hub" and hub_local is not None:
        anchor = hub_local
    else:
        anchor = (0, 0)

    if explore_state.sector_index is None:
        explore_state.sector_index = agent_id % cfg.sector_count
    my_sector = explore_state.sector_index

    pos = nav_state.position
    pos_sector = _sector_of(pos, anchor, cfg.sector_count)
    if pos_sector != my_sector:
        # Out of sector — walk back to anchor.
        if _manhattan(pos, anchor) > cfg.sector_return_threshold:
            return anchor
        # Close enough: try sector-restricted frontier; if none, recall.

    # Run BFS like frontier_bfs but reject candidates outside our sector.
    start = pos
    blocked = nav_state.blocked
    queue: deque[tuple[Coordinate, int]] = deque([(start, 0)])
    seen: set[Coordinate] = {start}
    candidates: list[tuple[int, Coordinate]] = []
    expansions = 0
    while queue and expansions < cfg.frontier_max_bfs_expansions:
        cell, dist = queue.popleft()
        expansions += 1
        if dist > cfg.frontier_max_distance:
            continue
        for dr, dc in MOVE_DELTAS.values():
            nxt = (cell[0] + dr, cell[1] + dc)
            if nxt in seen:
                continue
            seen.add(nxt)
            if nxt in blocked:
                continue
            if _is_stale(nxt, explore_state, step, cfg):
                if _sector_of(nxt, anchor, cfg.sector_count) == my_sector:
                    candidates.append((dist + 1, nxt))
                    if len(candidates) >= cfg.frontier_max_candidates:
                        break
                continue
            queue.append((nxt, dist + 1))
        if len(candidates) >= cfg.frontier_max_candidates:
            break

    if candidates:
        candidates.sort(key=lambda x: (x[0], x[1][0], x[1][1]))
        return candidates[0][1]

    # No frontier in own sector; recall to anchor so we don't drift.
    return anchor if anchor != pos else None


# ---------------------------------------------------------------------
# Strategy: spiral
# ---------------------------------------------------------------------

def spiral(
    explore_state: ExploreState,
    view: GridNavView,
    nav_state: GridNavState,
    cfg: ExploreConfig,
    step: int,
    *,
    hub_local: Coordinate | None = None,
) -> Coordinate | None:
    """Deterministic outward spiral from anchor.

    Returns the next anchor-relative ring cell that is not blocked.
    The cursor advances regardless of whether the caller actually
    reaches the target — so a heavily-walled spiral just visits the
    cells that *are* reachable on each ring before moving outward.
    """
    if cfg.spiral_anchor == "hub" and hub_local is not None:
        anchor = hub_local
    else:
        anchor = (0, 0)
    explore_state.spiral_anchor_local = anchor

    radius, side, idx = explore_state.spiral_cursor
    if radius < 1:
        radius = 1
    sign = 1 if cfg.spiral_clockwise else -1

    # 4 sides per ring; each side has 2*radius cells. Direction order
    # for clockwise (screen coords, row+ = south): east, south, west,
    # north. For counter-clockwise: east, north, west, south.
    if cfg.spiral_clockwise:
        side_dirs = ("east", "south", "west", "north")
    else:
        side_dirs = ("east", "north", "west", "south")

    # Try up to 4 * 2r + a small slack steps to find a non-blocked cell.
    attempts = 0
    max_attempts = 4 * (2 * cfg.spiral_max_radius + 1)
    while attempts < max_attempts:
        attempts += 1
        side_len = 2 * radius
        if idx >= side_len:
            idx = 0
            side = (side + 1) % 4
            if side == 0:
                radius += 1
                if radius > cfg.spiral_max_radius:
                    # Spiral exhausted; reset to inside.
                    radius = 1
                    side = 0
                    idx = 0
            continue

        # Compute the target cell using a simple parametric walk around
        # the current ring. This avoids carrying a more error-prone
        # corner-by-corner derivation in the code comments.
        ar, ac = anchor
        if side_dirs[side] == "east":
            # Walking east along the top of the ring (most-north row).
            cell = (ar - radius, ac - radius + idx + 1) if cfg.spiral_clockwise \
                   else (ar + radius, ac - radius + idx + 1)
            # Map "east" side: top row, walking east. dr=0, dc=+1.
            cell = (ar - radius * sign, ac - radius + idx + 1)
        elif side_dirs[side] == "south":
            cell = (ar - radius + idx + 1, ac + radius)
        elif side_dirs[side] == "west":
            cell = (ar + radius, ac + radius - idx - 1)
        else:  # north
            cell = (ar + radius - idx - 1, ac - radius)

        idx += 1
        explore_state.spiral_cursor = (radius, side, idx)

        if cell == nav_state.position:
            continue
        if cell in nav_state.blocked:
            continue
        return cell

    return None


# ---------------------------------------------------------------------
# Strategy: POI patrol
# ---------------------------------------------------------------------

def poi_patrol(
    explore_state: ExploreState,
    view: GridNavView,
    nav_state: GridNavState,
    cfg: ExploreConfig,
    step: int,
    *,
    pois: Iterable[tuple[Coordinate, int]],
) -> Coordinate | None:
    """Pick the oldest stale POI within ``poi_max_chase_distance``.

    ``pois`` is an iterable of ``(local_coord, last_seen_step)``;
    the caller is responsible for converting from any POI taxonomy.
    Ties broken by closer first, then row/col.
    """
    pos = nav_state.position
    best: tuple[int, int, Coordinate] | None = None  # (-age, dist, cell)
    for cell, last_seen in pois:
        age = step - last_seen
        if age < cfg.poi_stale_threshold:
            continue
        dist = _manhattan(pos, cell)
        if dist > cfg.poi_max_chase_distance:
            continue
        if cell in nav_state.blocked:
            continue
        key = (-age, dist, cell)
        if best is None or key < best:
            best = key
    return best[2] if best else None


# ---------------------------------------------------------------------
# Strategy: biased wander
# ---------------------------------------------------------------------

def biased_wander(
    explore_state: ExploreState,
    view: GridNavView,
    nav_state: GridNavState,
    cfg: ExploreConfig,
    step: int,
    *,
    direction_offset: int = 0,
) -> Coordinate | None:
    """One-step wander, optionally biased by ``cfg.wander_bias_vector``.

    Returns the *adjacent* target cell (not a far waypoint) so the
    caller's ``next_move`` will either pick that direction directly or
    sidestep around any transient blocker. Returns ``None`` if every
    direction is blocked.
    """
    pos = nav_state.position
    blocked = nav_state.blocked | view.visible_tagged_locals | view.blocker_locals

    # Scoring: lower is better. Base = WANDER_DIRECTIONS rotation order
    # (rotated by direction_offset). Bias adds a penalty proportional to
    # how off-axis the direction is from cfg.wander_bias_vector.
    bias = cfg.wander_bias_vector
    bias_strength = max(0.0, min(1.0, cfg.wander_bias_strength))

    rotated = [
        WANDER_DIRECTIONS[(direction_offset + i) % len(WANDER_DIRECTIONS)]
        for i in range(len(WANDER_DIRECTIONS))
    ]

    def score(direction: str, base_idx: int) -> float:
        s = float(base_idx)  # rotation preference
        if bias is not None and bias_strength > 0.0:
            dr, dc = MOVE_DELTAS[direction]
            # Cosine-similarity-ish: higher when direction aligns with bias.
            br, bc = bias
            mag = (br * br + bc * bc) ** 0.5
            if mag > 0:
                align = (dr * br + dc * bc) / mag
                # Penalize misalignment: -align in [-1, 1] → [0, 2]
                s += bias_strength * (1.0 - align)
        return s

    candidates: list[tuple[float, str, Coordinate]] = []
    for i, direction in enumerate(rotated):
        dr, dc = MOVE_DELTAS[direction]
        nxt = (pos[0] + dr, pos[1] + dc)
        if nxt in blocked:
            continue
        candidates.append((score(direction, i), direction, nxt))

    if not candidates:
        return None
    # Prefer unvisited.
    visited = nav_state.visited
    candidates.sort(key=lambda c: (c[2] in visited, c[0]))
    return candidates[0][2]


# ---------------------------------------------------------------------
# Stuck detection (utility, optional)
# ---------------------------------------------------------------------

def is_stuck(
    explore_state: ExploreState,
    nav_state: GridNavState,
    cfg: ExploreConfig,
    step: int,
) -> bool:
    """True if position hasn't advanced for ``cfg.stuck_threshold`` ticks."""
    pos = nav_state.position
    if explore_state.last_progress_position != pos:
        explore_state.last_progress_position = pos
        explore_state.last_progress_step = step
        return False
    return (step - explore_state.last_progress_step) >= cfg.stuck_threshold
