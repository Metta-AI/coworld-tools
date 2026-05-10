"""Whisper lifecycle tasks."""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

from orpheus.task import ActCommand, Task
from orpheus.tasks._menu_nav import MenuNavigator
from orpheus.tasks.movement import _distance, _movement_command_to, _position2d
from orpheus.tasks.view_management import OPEN_VIEW_VIEWS
from orpheus.types import BUTTON_A, BUTTON_B, BUTTON_SELECT, View

ENTRY_DISTANCE_PX = 7.0
RECENT_WHISPER_TICKS = 60
_INITIATE_WHISPER_STATE_KEY = "_initiate_whisper_state"
_HOLD_TICKS = 2
_WAIT_TICKS = 5
_MAX_TICKS = _HOLD_TICKS + 1 + _WAIT_TICKS


@dataclass(frozen=True)
class CreateWhisperTask(Task):
    """Create a new whisper at the current position."""

    valid_views: ClassVar[frozenset[View]] = OPEN_VIEW_VIEWS

    def select_action(self, belief_state, action_memory) -> ActCommand:
        return ActCommand(buttons=action_memory.step_button_press(BUTTON_A))


@dataclass(frozen=True)
class InitiateWhisperTask(Task):
    target_index: int | None = None
    use_button_b: bool = False

    valid_views: ClassVar[frozenset[View]] = OPEN_VIEW_VIEWS

    def select_action(self, belief_state, action_memory) -> ActCommand:
        state = belief_state.extra.get(_INITIATE_WHISPER_STATE_KEY)
        if not isinstance(state, dict):
            state = {"ticks": 0}
            belief_state.extra[_INITIATE_WHISPER_STATE_KEY] = state

        state["ticks"] += 1
        ticks = state["ticks"]

        if ticks > _MAX_TICKS:
            state["failed"] = True
            return ActCommand()

        button = BUTTON_B if self.use_button_b else BUTTON_A
        if ticks <= _HOLD_TICKS:
            return ActCommand(buttons=button)
        return ActCommand(buttons=0)

    @staticmethod
    def has_failed(belief_state) -> bool:
        state = belief_state.extra.get(_INITIATE_WHISPER_STATE_KEY)
        return isinstance(state, dict) and state.get("failed", False)

    @staticmethod
    def clear_state(belief_state) -> None:
        belief_state.extra.pop(_INITIATE_WHISPER_STATE_KEY, None)


@dataclass(frozen=True)
class RequestEntryTask(Task):
    """Approach a player's whisper and request entry when close enough."""

    player_index: int

    valid_views: ClassVar[frozenset[View]] = OPEN_VIEW_VIEWS

    def select_action(self, belief_state, action_memory) -> ActCommand:
        player = getattr(belief_state, "players", {}).get(self.player_index)
        target_position = _position2d(getattr(player, "position", None))
        self_position = _position2d(getattr(belief_state, "position", None))
        if player is None or target_position is None or self_position is None:
            return ActCommand()

        if _distance(self_position, target_position) <= ENTRY_DISTANCE_PX:
            last_seen = getattr(player, "last_seen_in_whisper", None)
            if (
                last_seen is not None
                and getattr(belief_state, "tick", 0) - last_seen <= RECENT_WHISPER_TICKS
            ):
                return ActCommand(buttons=action_memory.step_button_press(BUTTON_A))
            return ActCommand()

        return _movement_command_to(
            belief_state,
            action_memory,
            target_position,
            goal_radius=ENTRY_DISTANCE_PX,
        )


@dataclass(frozen=True)
class CancelEntryTask(Task):
    """Cancel a pending whisper-entry request."""

    valid_views: ClassVar[frozenset[View]] = frozenset({View.WAITING_ENTRY})

    def select_action(self, belief_state, action_memory) -> ActCommand:
        return ActCommand(buttons=action_memory.step_button_press(BUTTON_B))


@dataclass(frozen=True)
class ExitWhisperTask(Task):
    """Exit the current whisper using the Select shortcut."""

    valid_views: ClassVar[frozenset[View]] = frozenset({View.WHISPER})

    def select_action(self, belief_state, action_memory) -> ActCommand:
        return ActCommand(buttons=action_memory.step_button_press(BUTTON_SELECT))


@dataclass(frozen=True)
class GrantEntryTask(Task):
    """Grant a pending entry request from the whisper menu."""

    valid_views: ClassVar[frozenset[View]] = frozenset({View.WHISPER})

    def select_action(self, belief_state, action_memory) -> ActCommand:
        return MenuNavigator(
            (
                ("category", "LEADER"),
                ("item", "GRANT"),
                ("confirm",),
            )
        ).next_command(belief_state, action_memory)


__all__ = [
    "CreateWhisperTask",
    "InitiateWhisperTask",
    "RequestEntryTask",
    "CancelEntryTask",
    "ExitWhisperTask",
    "GrantEntryTask",
]
