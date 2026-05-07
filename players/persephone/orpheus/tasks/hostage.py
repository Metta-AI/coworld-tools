"""Hostage-selection task."""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

from orpheus.task import ActCommand, Task
from orpheus.types import BUTTON_A, BUTTON_B, View


@dataclass(frozen=True)
class SelectHostagesTask(Task):
    """Toggle the requested hostage indices in global chat."""

    player_indices: tuple[int, ...]

    valid_views: ClassVar[frozenset[View]] = frozenset({View.GLOBAL_CHAT})

    def select_action(self, belief_state, action_memory) -> ActCommand:
        if not hasattr(action_memory, "hostage_remaining"):
            action_memory.hostage_remaining = list(self.player_indices)
            action_memory.hostage_committed = False

        # TODO Stage 4 follow-up: use HostageGrid.cursor_index and grid layout
        # to navigate with U/D/L/R before toggling each requested player. Stage
        # 4 only provides structural completeness and a rising-edge toggle.
        if action_memory.hostage_remaining:
            command = action_memory.step_button_press(BUTTON_A)
            if command:
                action_memory.hostage_remaining.pop(0)
            return ActCommand(buttons=command)

        if not action_memory.hostage_committed:
            command = action_memory.step_button_press(BUTTON_B)
            if command:
                action_memory.hostage_committed = True
            return ActCommand(buttons=command)

        if action_memory.pressed_last_tick:
            action_memory.pressed_last_tick = False
        return ActCommand()


__all__ = ["SelectHostagesTask"]
