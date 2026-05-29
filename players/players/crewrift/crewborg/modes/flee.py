"""Flee mode: keep away from a believed imposter (design §7.1).

Emits ``flee_from`` for the nearest believed imposter currently in the roster;
the action layer maximizes distance from it. ``flee_from`` is the simple keep-away
primitive — situational fleeing (toward a trusted player, the button, or around a
corner) is a later refinement that emits ``navigate_to`` instead (design §8).

In P3 the evidence ledger (``belief.believed_imposters``) is an empty stub, so
this mode is wired but dormant until suspicion reasoning fills it.
"""

from __future__ import annotations

from players.crewrift.crewborg.types import ActionState, Belief, Intent
from players.player_sdk import EmptyModeParams, Mode


class FleeMode(Mode[Belief, ActionState, Intent]):
    name = "flee"
    params_type = EmptyModeParams

    def decide(self, belief: Belief, action_state: ActionState) -> Intent:
        del action_state
        threats = [pid for pid in belief.believed_imposters if pid in belief.roster]
        if not threats:
            return Intent(kind="idle", reason="no believed threat present")
        if belief.self_world_x is None or belief.self_world_y is None:
            target = min(threats)
        else:
            self_xy = (belief.self_world_x, belief.self_world_y)
            target = min(threats, key=lambda p: _dist2(self_xy, _player_xy(belief, p)))
        return Intent(kind="flee_from", target_id=target, reason="fleeing believed imposter")


def _player_xy(belief: Belief, player_id: int) -> tuple[int, int]:
    entry = belief.roster[player_id]
    return entry.world_x, entry.world_y


def _dist2(a: tuple[int, int], b: tuple[int, int]) -> int:
    return (a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2
