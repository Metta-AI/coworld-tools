"""IdleMode unit tests."""

from __future__ import annotations

from players.among_them.coborg.modes.idle import (
    IdleMode,
)
from players.among_them.coborg.types import (
    ActionState,
    AmongThemBelief,
)


def test_idle_decide_returns_noop_intent() -> None:
    intent = IdleMode().decide(AmongThemBelief(), ActionState())
    assert intent.kind == "noop"
    assert intent.mask == 0


def test_idle_is_legal_always_true() -> None:
    assert IdleMode().is_legal(AmongThemBelief()) is True
