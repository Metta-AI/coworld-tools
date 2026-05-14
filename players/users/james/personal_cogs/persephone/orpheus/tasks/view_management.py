"""Tasks that open or close non-overworld views."""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

from orpheus.task import ActCommand, Task
from orpheus.types import BUTTON_B, BUTTON_SELECT, View

OPEN_VIEW_VIEWS: frozenset[View] = frozenset(
    {View.PLAYING, View.HOSTAGE_SELECT, View.LEADER_SUMMIT}
)


@dataclass(frozen=True)
class OpenGlobalChatTask(Task):
    """Open the room-wide global chat surface."""

    valid_views: ClassVar[frozenset[View]] = OPEN_VIEW_VIEWS

    def select_action(self, belief_state, action_memory) -> ActCommand:
        return ActCommand(buttons=action_memory.step_button_press(BUTTON_SELECT))


@dataclass(frozen=True)
class OpenInfoScreenTask(Task):
    """Open the info screen from an overworld view."""

    valid_views: ClassVar[frozenset[View]] = OPEN_VIEW_VIEWS

    def select_action(self, belief_state, action_memory) -> ActCommand:
        return ActCommand(buttons=action_memory.step_button_press(BUTTON_B))


@dataclass(frozen=True)
class CloseViewTask(Task):
    """Close a chat/info surface back toward the overworld."""

    valid_views: ClassVar[frozenset[View]] = frozenset(
        {View.GLOBAL_CHAT, View.INFO_SCREEN, View.WHISPER}
    )

    def select_action(self, belief_state, action_memory) -> ActCommand:
        return ActCommand(buttons=action_memory.step_button_press(BUTTON_SELECT))


__all__ = [
    "OPEN_VIEW_VIEWS",
    "OpenGlobalChatTask",
    "OpenInfoScreenTask",
    "CloseViewTask",
]
