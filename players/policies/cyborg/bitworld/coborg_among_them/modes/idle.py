"""Idle mode: emit a noop input every tick.

P0's only mode. It exists so the runtime always has a registered mode whose
``decide`` produces a legal intent, satisfying the framework invariant that
exactly one mode is active at all times.
"""

from __future__ import annotations

from agent_policies.frameworks.coborg import EmptyModeParams, Mode

from policies.cyborg.bitworld.coborg_among_them.types import (
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
