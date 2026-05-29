"""Evade mode: leave the scene right after a kill (imposter Flee; design §7.2).

Prefers to vanish through a vent (emit ``vent`` — the action layer routes to the
nearest vent and presses B); failing that, moves away from the freshest body
(``navigate_to`` a point reflected through self). Idles if there is nothing to
flee from.
"""

from __future__ import annotations

from players.crewrift.crewborg.types import ActionState, Belief, Intent
from players.player_sdk import EmptyModeParams, Mode


class EvadeMode(Mode[Belief, ActionState, Intent]):
    name = "evade"
    params_type = EmptyModeParams

    def decide(self, belief: Belief, action_state: ActionState) -> Intent:
        del action_state
        # Vanish via a vent when the map has them (action layer picks the nearest).
        if belief.map is not None and belief.map.vents:
            return Intent(kind="vent", reason="evading via vent")

        self_xy = _self_xy(belief)
        if self_xy is not None and belief.bodies:
            body = min(belief.bodies.values(), key=lambda b: _dist2(self_xy, (b.world_x, b.world_y)))
            away = (2 * self_xy[0] - body.world_x, 2 * self_xy[1] - body.world_y)
            return Intent(kind="navigate_to", point=away, reason="moving away from the body")

        return Intent(kind="idle", reason="nothing to evade")


def _self_xy(belief: Belief) -> tuple[int, int] | None:
    if belief.self_world_x is None or belief.self_world_y is None:
        return None
    return belief.self_world_x, belief.self_world_y


def _dist2(a: tuple[int, int], b: tuple[int, int]) -> int:
    return (a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2
