"""Opt-in grid navigation for discrete 4-way-movement worlds.

A self-contained, stdlib-only navigation toolkit for grid games under
partial observability:

- :mod:`.core` — cost-shaped A* with repulsor/attractor potential fields,
  per-agent decaying tabu trail, teammate-trajectory collision prediction,
  plan caching with opportunistic detours, sidestep/bump handling, and
  dead-reckoned position tracking. Knobs on :class:`GridNavConfig`;
  per-agent state on :class:`GridNavState`.
- :mod:`.distance` — canonical metrics (``manhattan``/``chebyshev``/
  ``euclidean``/``euclidean_sq``) so call sites name the metric explicitly.
- :mod:`.explore` — exploration *target selection*: frontier BFS, sector
  assignment, spiral, POI patrol, biased wander. Decides *where*, not *how*.
- :mod:`.stuck` — position/axial/pacing stuck detectors + tabu-backed
  resolution.
- :mod:`.tabu` — TTL'd blacklist with failure-strike promotion, keyed by
  any hashable.
- :mod:`.deadlock` — convergence-resource pile-up detection + deterministic
  backoff scatter.

Per-tick caller contract (see :mod:`.core` for details)::

    update_position(nav, last_dir, succeeded, ...)   # fold last move result
    view = observe(nav, frozen_tags, obs_center)     # classify visible cells
    direction = next_move(nav, view, target_local)   # or next_move_cached(...)
    record_step(nav)                                 # push tabu trail

All game semantics enter through caller-supplied tag-id frozensets on
:class:`GridNavConfig` — nothing here imports a game engine.

This subpackage is not re-exported from ``players.player_sdk``; import it
explicitly. Origin: extracted from Ron Dahlgren's (swgy) agent libraries
(sm-policies Cogs-vs-Clips scripted stack, the ``SWGY-Nav`` bundle).
"""

from .core import (
    LEFT_OF,
    MOVE_DELTAS,
    RIGHT_OF,
    WANDER_DIRECTIONS,
    Coordinate,
    GridNavConfig,
    GridNavState,
    GridNavView,
    TeamMemberTrack,
    arrived,
    is_bump_target,
    next_move,
    next_move_cached,
    observe,
    plan_path,
    record_step,
    record_team_observations,
    try_sidestep,
    update_position,
)
from .deadlock import DeadlockConfig, DeadlockState, pick_backoff_cell, update_deadlock_state
from .distance import chebyshev, euclidean, euclidean_sq, manhattan
from .explore import (
    ExploreConfig,
    ExploreState,
    biased_wander,
    frontier_bfs,
    is_stuck,
    note_observed,
    poi_patrol,
    sector_assignment,
    spiral,
)
from .stuck import (
    StuckConfig,
    StuckOutcome,
    StuckState,
    axial_stuck,
    check_and_resolve,
    pacing_stuck,
    position_stuck,
)
from .tabu import TabuConfig, TabuState, add_tabu, gc, is_tabu, record_failure, record_success

__all__ = [
    "LEFT_OF",
    "MOVE_DELTAS",
    "RIGHT_OF",
    "WANDER_DIRECTIONS",
    "Coordinate",
    "DeadlockConfig",
    "DeadlockState",
    "ExploreConfig",
    "ExploreState",
    "GridNavConfig",
    "GridNavState",
    "GridNavView",
    "StuckConfig",
    "StuckOutcome",
    "StuckState",
    "TabuConfig",
    "TabuState",
    "TeamMemberTrack",
    "add_tabu",
    "arrived",
    "axial_stuck",
    "biased_wander",
    "chebyshev",
    "check_and_resolve",
    "euclidean",
    "euclidean_sq",
    "frontier_bfs",
    "gc",
    "is_bump_target",
    "is_stuck",
    "is_tabu",
    "manhattan",
    "next_move",
    "next_move_cached",
    "note_observed",
    "observe",
    "pacing_stuck",
    "pick_backoff_cell",
    "plan_path",
    "poi_patrol",
    "position_stuck",
    "record_failure",
    "record_step",
    "record_success",
    "record_team_observations",
    "sector_assignment",
    "spiral",
    "try_sidestep",
    "update_deadlock_state",
    "update_position",
]
