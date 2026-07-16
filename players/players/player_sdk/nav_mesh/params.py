"""Tunable knobs for routing and following: :class:`NavParams`.

Origin: extracted from Ron Dahlgren's (swgy) agent libraries
(swgy-crewrift; original module ``swgy_base.nav.params``). The never-read
``max_speed``/``slow_radius`` fields of the original were dropped here —
they described a velocity-error control law that was tried and removed
before the original shipped (see ``follow.py``).

A leaf value module -- imports nothing from ``nav`` -- so both the planner
(``astar``) and the follower (``follow``) can depend on it without cycles.

These are plain dataclass fields with defaults, not tuner objects: the
``# GA bounds`` comments are advisory metadata for a downstream tuner (see
``players.player_sdk.tuning.compose.genome_from_dataclass``, which builds a
genome from exactly these fields + your chosen bounds).
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class NavParams:
    """Knobs controlling A* routing and plan-following behaviour."""

    # --- planning (A*) ---
    heuristic_weight: float = 1.0
    """1.0 = admissible/optimal A*; >1 = weighted/greedy (fewer expansions,
    suboptimal). GA bounds [1.0, 4.0]."""

    avoid_tags: frozenset[str] = field(default_factory=frozenset)
    """Static map edge tags to steer around, e.g. ``{"vent", "hazard"}``."""

    avoid_penalty: float = 50.0
    """Additive cost per edge carrying an ``avoid_tags`` tag (soft avoidance).
    GA bounds [0.0, 500.0]."""

    allow_avoided: bool = True
    """When False, ``avoid_tags`` edges are pruned entirely (hard no-go)."""

    diagonal_bias: float = 0.0
    """How much A* costs edges by *travel time* vs *path length*, in ``[0, 1]``.

    The engine clamps velX/velY independently, so a diagonal covers both axes at
    once: an edge's true traversal time is its **Chebyshev** span
    (``max(|dx|, |dy|)``), not its Euclidean length. ``0`` = cost by Euclidean
    length (shortest path); ``1`` = cost by Chebyshev (favor diagonal-heavy
    routes); values between lerp the two. Applied to both edge cost and the
    heuristic, so A* stays admissible at ``heuristic_weight=1``.

    Default ``0``: the engine-faithful nav benchmark (``swgy-nav-bench``) found
    ``bias > 0`` does *not* speed up real traversal on Croatoan -- the
    acceleration follower keeps momentum on straighter (Euclidean) routes, and it
    already gets the +41% diagonal boost on the lattice's 45-deg edges where it
    actually helps. Kept as a knob for tuning/other maps. GA bounds [0.0, 1.0]."""

    # --- waypoint following ---
    arrival_radius: float = 12.0
    """px; a waypoint counts as reached -- and the cursor advances -- within
    this distance. GA bounds [2.0, 48.0]."""

    diagonal: bool = True
    """Allow two-button diagonals (UP|LEFT, ...). False = 4-way only."""

    axis_deadband: float = 5.0
    """px; hold-toward-waypoint ignores an axis whose offset to the target is
    below this, so the minor axis doesn't jitter on a near-aligned target (a true
    diagonal still drives both). Lower => press the minor axis sooner (more
    diagonal on shallow approaches). GA bounds [1.0, 12.0]."""

    # --- inertia (the engine integrates acceleration; movement coasts) ---
    inertia: bool = True
    """Inertia-aware hold-to-waypoint steering: press toward the current
    waypoint (beyond ``axis_deadband``) and release only within
    ``arrival_radius`` of the *final* goal, so residual velocity coasts to a
    stop on it. When False, steer on raw unit direction to the target (no
    momentum exploitation)."""

    # --- crew buffer (soft personal-space preference; OFF by default) ---
    # NB: CrewRift has *no* crew-to-crew collision, so this is never required for
    # correctness -- it is a pure preference a policy opts into (e.g. an imposter
    # keeping clear of witnesses, or crew spreading out for task coverage). It is
    # a soft steer that only nudges onto an axis not already driving toward the
    # goal, so it never stalls or slows the agent toward its waypoint.
    min_follow_distance: float = 0.0
    """px; radius of the soft personal-space buffer around other players. Within
    it the follower gently steers away (linear falloff); at/beyond it they exert
    no force. ``0`` (default) disables the buffer entirely -- max-speed travel,
    crew ignored. GA bounds [0.0, 64.0]."""

    avoidance_weight: float = 1.0
    """Strength of the buffer steer blended against goal-seek. Inert while
    ``min_follow_distance == 0``. 0 = ignore crew. GA bounds [0.0, 4.0]."""

    # --- stuck / cycle detection ---
    stuck_window: int = 12
    """Ticks of position history inspected for stuck/cycle detection.
    GA bounds [4, 48]."""

    stuck_epsilon: float = 6.0
    """px; if net travel across the window is below this, the follower is stuck.
    GA bounds [1.0, 32.0]."""

    replan_on_stuck: bool = True
    """Raise the replan signal when stuck is detected."""
