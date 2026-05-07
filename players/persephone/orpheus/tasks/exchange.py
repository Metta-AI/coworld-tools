"""Whisper information-exchange tasks."""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

from orpheus.task import ActCommand, Task
from orpheus.tasks._menu_nav import MenuNavigator, MenuStep
from orpheus.types import View

WHISPER_ONLY: frozenset[View] = frozenset({View.WHISPER})


@dataclass(frozen=True)
class OfferColorExchangeTask(Task):
    """Offer a color/team exchange in the current whisper."""

    valid_views: ClassVar[frozenset[View]] = WHISPER_ONLY

    def select_action(self, belief_state, action_memory) -> ActCommand:
        return _navigate(
            belief_state,
            action_memory,
            ("category", "COLOR"),
            ("item", "C.OFFER"),
            ("confirm",),
        )


@dataclass(frozen=True)
class AcceptColorExchangeTask(Task):
    """Accept a color/team exchange from a target player."""

    player_index: int

    valid_views: ClassVar[frozenset[View]] = WHISPER_ONLY

    def select_action(self, belief_state, action_memory) -> ActCommand:
        return _navigate(
            belief_state,
            action_memory,
            ("category", "COLOR"),
            ("item", "C.ACCPT"),
            ("confirm",),
            ("target", self.player_index),
            ("confirm",),
        )


@dataclass(frozen=True)
class WithdrawColorOfferTask(Task):
    """Withdraw a pending color/team exchange offer."""

    valid_views: ClassVar[frozenset[View]] = WHISPER_ONLY

    def select_action(self, belief_state, action_memory) -> ActCommand:
        return _navigate(
            belief_state,
            action_memory,
            ("category", "COLOR"),
            ("item", "C.UNOFFR"),
            ("confirm",),
        )


@dataclass(frozen=True)
class OfferRoleExchangeTask(Task):
    """Offer a mutual role exchange in the current whisper."""

    valid_views: ClassVar[frozenset[View]] = WHISPER_ONLY

    def select_action(self, belief_state, action_memory) -> ActCommand:
        return _navigate(
            belief_state,
            action_memory,
            ("category", "ROLE"),
            ("item", "R.OFFER"),
            ("confirm",),
        )


@dataclass(frozen=True)
class AcceptRoleExchangeTask(Task):
    """Accept a mutual role exchange from a target player."""

    player_index: int

    valid_views: ClassVar[frozenset[View]] = WHISPER_ONLY

    def select_action(self, belief_state, action_memory) -> ActCommand:
        return _navigate(
            belief_state,
            action_memory,
            ("category", "ROLE"),
            ("item", "R.ACCPT"),
            ("confirm",),
            ("target", self.player_index),
            ("confirm",),
        )


@dataclass(frozen=True)
class WithdrawRoleOfferTask(Task):
    """Withdraw a pending role exchange offer."""

    valid_views: ClassVar[frozenset[View]] = WHISPER_ONLY

    def select_action(self, belief_state, action_memory) -> ActCommand:
        return _navigate(
            belief_state,
            action_memory,
            ("category", "ROLE"),
            ("item", "R.UNOFFR"),
            ("confirm",),
        )


@dataclass(frozen=True)
class RevealRoleTask(Task):
    """Reveal the agent's role in the current whisper."""

    valid_views: ClassVar[frozenset[View]] = WHISPER_ONLY

    def select_action(self, belief_state, action_memory) -> ActCommand:
        return _navigate(
            belief_state,
            action_memory,
            ("category", "ROLE"),
            ("item", "ROLE"),
            ("confirm",),
        )


def _navigate(belief_state, action_memory, *steps: MenuStep) -> ActCommand:
    return MenuNavigator(steps).next_command(belief_state, action_memory)


__all__ = [
    "WHISPER_ONLY",
    "OfferColorExchangeTask",
    "AcceptColorExchangeTask",
    "WithdrawColorOfferTask",
    "OfferRoleExchangeTask",
    "AcceptRoleExchangeTask",
    "WithdrawRoleOfferTask",
    "RevealRoleTask",
]
