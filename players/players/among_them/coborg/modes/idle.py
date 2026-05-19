"""Idle mode: emit a noop input every tick.

P0's only mode. It exists so the runtime always has a registered mode whose
``decide`` produces a legal intent, satisfying the framework invariant that
exactly one mode is active at all times.
"""

from __future__ import annotations

from players.player_sdk import EmptyModeParams, Mode

from players.among_them.coborg.types import (
    ActionState,
    AmongThemBelief,
    AmongThemIntent,
)


class IdleMode(Mode[AmongThemBelief, ActionState, AmongThemIntent]):
    name = "idle"
    params_type = EmptyModeParams

    def decide(
        self, belief: AmongThemBelief, action_state: ActionState
    ) -> AmongThemIntent:
        del belief, action_state
        return AmongThemIntent(kind="noop", reason="P0 idle")
