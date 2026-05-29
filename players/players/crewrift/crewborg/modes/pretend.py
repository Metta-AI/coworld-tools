"""Pretend mode: blend in while the kill is on cooldown (imposter; design §7.2).

Loiters near task stations to look busy: navigate to the nearest baked station and
idle there (a fake task stop). Richer blending — matching crew movement, faking
the task hold timing — is a later refinement.
"""

from __future__ import annotations

from players.crewrift.crewborg.types import ActionState, Belief, Intent
from players.player_sdk import EmptyModeParams, Mode

LOITER_RADIUS_SQ = 24**2


class PretendMode(Mode[Belief, ActionState, Intent]):
    name = "pretend"
    params_type = EmptyModeParams

    def decide(self, belief: Belief, action_state: ActionState) -> Intent:
        del action_state
        tasks = belief.map.tasks if belief.map is not None else ()
        self_xy = _self_xy(belief)
        if not tasks or self_xy is None:
            return Intent(kind="idle", reason="loitering")

        nearest = min(tasks, key=lambda t: _dist2(self_xy, (t.center.x, t.center.y)))
        target = (nearest.center.x, nearest.center.y)
        if _dist2(self_xy, target) <= LOITER_RADIUS_SQ:
            return Intent(kind="idle", reason="faking a task at a station")
        return Intent(kind="navigate_to", point=target, reason="loitering near a task station")


def _self_xy(belief: Belief) -> tuple[int, int] | None:
    if belief.self_world_x is None or belief.self_world_y is None:
        return None
    return belief.self_world_x, belief.self_world_y


def _dist2(a: tuple[int, int], b: tuple[int, int]) -> int:
    return (a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2
