"""IdleMode unit tests."""

from __future__ import annotations

from agent_policies.policies.cyborg.bitworld.coborg_among_them.modes.idle import (
    IdleMode,
)
from agent_policies.policies.cyborg.bitworld.coborg_among_them.types import (
    ActionState,
    AmongThemBelief,
)


def test_idle_decide_returns_noop_intent() -> None:
    intent = IdleMode().decide(AmongThemBelief(), ActionState())
    assert intent.kind == "noop"
    assert intent.mask == 0


def test_idle_is_legal_always_true() -> None:
    assert IdleMode().is_legal(AmongThemBelief()) is True
