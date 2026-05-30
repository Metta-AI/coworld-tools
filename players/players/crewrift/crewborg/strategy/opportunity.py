"""Shared imposter victim-selection and witness logic (design §7.2, §10).

Hunt commits to a *victim* and stalks it, striking only when the kill would go
**unwitnessed**. This module is the single source of truth for: which crewmate to
commit to (``select_victim`` — the most-isolated straggler, easiest to finish off
unseen), whether a kill on a given target is currently unwitnessed (``unwitnessed``),
and whether any victim is even trackable right now (``has_trackable_victim``, which
gates Hunt vs. Pretend in the selector).

The witness bar is not fixed: the longer the imposter has been *able* to kill
without doing so, the more it relaxes (``kill_urgency_ticks``), so a cautious
imposter that never finds a clean opening still escalates rather than stalling
forever (design §10 "act with urgency").
"""

from __future__ import annotations

from players.crewrift.crewborg.nav import plan_route
from players.crewrift.crewborg.types import Belief, RosterEntry

# Clearance (world px) required around a target at zero urgency: no other crewmate
# may be within this distance for the kill to count as unwitnessed.
BASE_ISOLATION_RADIUS = 48

# At zero urgency, another crewmate seen within this many ticks still counts as a
# potential witness; the window shrinks with urgency so stale sightings stop vetoing.
WITNESS_WINDOW_TICKS = 72

# Ticks of being able-to-kill-without-killing at which the witness bar reaches zero —
# i.e. the imposter will strike any victim regardless of witnesses (~10s at 24 Hz).
URGENCY_FULL_TICKS = 240

# A non-teammate seen within this many ticks is still "trackable" — Hunt can stalk it
# (to its last-known / predicted position) even while it is briefly out of view.
TRACK_WINDOW_TICKS = 120


def kill_urgency_ticks(belief: Belief) -> int:
    """How long we have been able to kill without doing so (0 if not kill-ready)."""

    if not belief.self_kill_ready or belief.kill_ready_since_tick is None:
        return 0
    return max(0, belief.last_tick - belief.kill_ready_since_tick)


def has_trackable_victim(belief: Belief) -> bool:
    """Whether any non-teammate has been seen recently enough for Hunt to stalk.

    Gates the selector: kill-ready + a trackable victim → Hunt (stalk); otherwise the
    imposter blends/wanders via Pretend (and so goes looking for crew when it has none).
    """

    return any(
        entry.color not in belief.teammate_colors and belief.last_tick - entry.last_seen_tick <= TRACK_WINDOW_TICKS
        for entry in belief.roster.values()
    )


def select_victim(belief: Belief) -> RosterEntry | None:
    """The crewmate to commit to hunting: the most-isolated reachable crewmate in
    view (a straggler — easiest to finish off unwitnessed), tie-broken by nearest to
    us. ``None`` when no non-teammate is currently visible/reachable to commit to."""

    self_xy = _self_xy(belief)
    if self_xy is None:
        return None
    crew = [
        entry
        for entry in belief.roster.values()
        if entry.last_seen_tick == belief.last_tick and entry.color not in belief.teammate_colors
    ]
    if not crew:
        return None
    candidates = crew
    if belief.nav is not None:
        candidates = [t for t in crew if plan_route(belief.nav, self_xy, (t.world_x, t.world_y))]
        if not candidates:
            return None
    # Prefer the most isolated (largest gap to its nearest other crewmate), then nearest.
    return max(candidates, key=lambda t: (_isolation(t, belief), -_dist2(self_xy, (t.world_x, t.world_y))))


def unwitnessed(belief: Belief, target: RosterEntry) -> bool:
    """Whether killing ``target`` now would go unseen, at the current urgency level."""

    frac = min(1.0, kill_urgency_ticks(belief) / URGENCY_FULL_TICKS)
    radius_sq = (BASE_ISOLATION_RADIUS * (1.0 - frac)) ** 2
    window = int(WITNESS_WINDOW_TICKS * (1.0 - frac))
    return _is_unwitnessed(target, belief, radius_sq, window)


def _isolation(target: RosterEntry, belief: Belief) -> float:
    """Distance² to the nearest *other* non-teammate — higher means more isolated."""

    target_xy = (target.world_x, target.world_y)
    gaps = [
        _dist2(target_xy, (o.world_x, o.world_y))
        for o in belief.roster.values()
        if o.object_id != target.object_id and o.color not in belief.teammate_colors
    ]
    return min(gaps) if gaps else float("inf")


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
