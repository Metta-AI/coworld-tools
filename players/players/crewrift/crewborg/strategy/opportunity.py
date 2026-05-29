"""Shared imposter kill-opportunity logic (design §10).

A single source of truth for "is there a subtle kill available right now, and if
so against whom" — used both by the selector (to choose Hunt over Pretend) and by
Hunt itself (to pick the target), so the two can never disagree.

An opportunity is a currently-visible, reachable, non-teammate crewmate that is
*isolated* enough that the kill would go unwitnessed. The isolation bar is not
fixed: the longer the imposter has been able to kill without doing so, the more it
relaxes, so a cautious imposter that never finds a perfect opening still escalates
to a riskier kill rather than stalling forever (design §10 "act with urgency").
"""

from __future__ import annotations

from players.crewrift.crewborg.nav import plan_route
from players.crewrift.crewborg.types import Belief, RosterEntry

# Clearance (world px) required around a target at zero urgency: no other crewmate
# may be within this distance for the kill to count as unwitnessed. Matches the old
# Hunt isolation radius.
BASE_ISOLATION_RADIUS = 48

# At zero urgency, another crewmate seen within this many ticks still counts as a
# potential witness; the window shrinks with urgency so stale sightings stop vetoing.
WITNESS_WINDOW_TICKS = 72

# Ticks of being able-to-kill-without-killing at which the isolation bar reaches
# zero — i.e. the imposter will take any reachable visible target (~10s at 24 Hz).
URGENCY_FULL_TICKS = 240


def kill_urgency_ticks(belief: Belief) -> int:
    """How long we have been able to kill without doing so (0 if not kill-ready)."""

    if not belief.self_kill_ready or belief.kill_ready_since_tick is None:
        return 0
    return max(0, belief.last_tick - belief.kill_ready_since_tick)


def kill_opportunity(belief: Belief) -> RosterEntry | None:
    """The best currently-killable, isolated, reachable target, or ``None``.

    Returns the nearest qualifying target; ``None`` means "keep blending in" — no
    subtle chance exists yet (and we are not urgent enough to force a risky one).
    """

    self_xy = _self_xy(belief)
    if self_xy is None:
        return None

    # Killable = a non-teammate player seen this very tick (we need a live position
    # to navigate onto and a fresh target the server won't skip).
    crew = [
        entry
        for entry in belief.roster.values()
        if entry.last_seen_tick == belief.last_tick and entry.color not in belief.teammate_colors
    ]
    if not crew:
        return None

    # Reachability: an unreachable target would only strand the action layer.
    candidates = crew
    if belief.nav is not None:
        candidates = [t for t in crew if plan_route(belief.nav, self_xy, (t.world_x, t.world_y))]
        if not candidates:
            return None

    frac = min(1.0, kill_urgency_ticks(belief) / URGENCY_FULL_TICKS)
    required_radius_sq = (BASE_ISOLATION_RADIUS * (1.0 - frac)) ** 2
    witness_window = int(WITNESS_WINDOW_TICKS * (1.0 - frac))

    isolated = [t for t in candidates if _is_unwitnessed(t, belief, required_radius_sq, witness_window)]
    if not isolated:
        return None
    return min(isolated, key=lambda t: _dist2(self_xy, (t.world_x, t.world_y)))


def _is_unwitnessed(target: RosterEntry, belief: Belief, radius_sq: float, window: int) -> bool:
    """Whether no non-teammate crewmate is close enough (and recent enough) to see the kill."""

    target_xy = (target.world_x, target.world_y)
    for other in belief.roster.values():
        if other.object_id == target.object_id or other.color in belief.teammate_colors:
            continue  # the victim itself and fellow imposters are never witnesses
        if belief.last_tick - other.last_seen_tick > window:
            continue  # last seen too long ago to credibly still be watching
        if _dist2(target_xy, (other.world_x, other.world_y)) <= radius_sq:
            return False
    return True


def _self_xy(belief: Belief) -> tuple[int, int] | None:
    if belief.self_world_x is None or belief.self_world_y is None:
        return None
    return belief.self_world_x, belief.self_world_y


def _dist2(a: tuple[int, int], b: tuple[int, int]) -> int:
    return (a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2
