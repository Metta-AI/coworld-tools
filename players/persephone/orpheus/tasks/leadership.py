"""Leadership and usurpation tasks."""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

from orpheus.task import ActCommand, Task
from orpheus.tasks._menu_nav import MenuNavigator
from orpheus.types import BUTTON_A, View


@dataclass(frozen=True)
class PassLeadershipTask(Task):
    """Offer leadership to another whisper occupant."""

    valid_views: ClassVar[frozenset[View]] = frozenset({View.WHISPER})

    def select_action(self, belief_state, action_memory) -> ActCommand:
        return MenuNavigator(
            (
                ("category", "LEADER"),
                ("item", "PASS"),
                ("confirm",),
            )
        ).next_command(belief_state, action_memory)


@dataclass(frozen=True)
class TakeLeadershipTask(Task):
    """Accept a pending leadership transfer."""

    valid_views: ClassVar[frozenset[View]] = frozenset({View.WHISPER})

    def select_action(self, belief_state, action_memory) -> ActCommand:
        return MenuNavigator(
            (
                ("category", "LEADER"),
                ("item", "TAKE"),
                ("confirm",),
            )
        ).next_command(belief_state, action_memory)


@dataclass(frozen=True)
class VoteUsurpTask(Task):
    """Vote for a usurp candidate from the global chat selector."""

    candidate: int

    valid_views: ClassVar[frozenset[View]] = frozenset({View.GLOBAL_CHAT})

    def select_action(self, belief_state, action_memory) -> ActCommand:
        # TODO Stage 4 follow-up: navigate the visible candidate selector with
        # L/R once perception exposes a stable candidate cursor/index. Modes
        # must open GLOBAL_CHAT before selecting this task.
        return ActCommand(buttons=action_memory.step_button_press(BUTTON_A))


__all__ = [
    "PassLeadershipTask",
    "TakeLeadershipTask",
    "VoteUsurpTask",
]
