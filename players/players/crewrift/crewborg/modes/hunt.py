"""Hunt mode: kill an isolated crewmate (imposter, kill ready; design §7.2).

Picks the nearest currently-visible other player, preferring one that is
*isolated* (no other visible player nearby, so the kill goes unseen) and reachable
over the nav graph, and emits ``kill``; the action layer navigates to it and
edge-presses A in range. Idles when no target is in view.
"""

from __future__ import annotations

from players.crewrift.crewborg.nav import plan_route
from players.crewrift.crewborg.types import ActionState, Belief, Intent, RosterEntry
from players.player_sdk import EmptyModeParams, Mode

ISOLATION_RADIUS_SQ = 48**2


class HuntMode(Mode[Belief, ActionState, Intent]):
    name = "hunt"
    params_type = EmptyModeParams

    def decide(self, belief: Belief, action_state: ActionState) -> Intent:
        del action_state
        self_xy = _self_xy(belief)
        if self_xy is None:
            return Intent(kind="idle", reason="no self position")

        # Currently-visible other players (roster refreshed this tick).
        visible = [e for e in belief.roster.values() if e.last_seen_tick == belief.last_tick]
        if not visible:
            return Intent(kind="idle", reason="no target in view")

        isolated = [t for t in visible if _is_isolated(t, visible)]
        pool = isolated or visible
        if belief.nav is not None:
            reachable = [t for t in pool if plan_route(belief.nav, self_xy, (t.world_x, t.world_y))]
            if reachable:
                pool = reachable

        target = min(pool, key=lambda t: _dist2(self_xy, (t.world_x, t.world_y)))
        return Intent(kind="kill", target_id=target.object_id, reason="hunting isolated crewmate")


def _is_isolated(target: RosterEntry, visible: list[RosterEntry]) -> bool:
    target_xy = (target.world_x, target.world_y)
    return all(
        other.object_id == target.object_id
        or _dist2(target_xy, (other.world_x, other.world_y)) > ISOLATION_RADIUS_SQ
        for other in visible
    )


def _self_xy(belief: Belief) -> tuple[int, int] | None:
    if belief.self_world_x is None or belief.self_world_y is None:
        return None
    return belief.self_world_x, belief.self_world_y


def _dist2(a: tuple[int, int], b: tuple[int, int]) -> int:
    return (a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2
