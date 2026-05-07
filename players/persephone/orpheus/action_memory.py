"""Per-task control memory for Orpheus tasks."""

from __future__ import annotations

import collections

from orpheus.task import ActCommand


# ---------------------------------------------------------------------------
# Action memory
# ---------------------------------------------------------------------------


class ActionMemory:
    """Per-task control-level state. Cleared on task change."""

    HISTORY_SIZE: int = 16

    def __init__(self) -> None:
        self.ticks_active: int = 0
        self.commands_sent: int = 0
        self.last_command: ActCommand | None = None
        self.command_history: collections.deque[ActCommand] = collections.deque(
            maxlen=self.HISTORY_SIZE
        )
        # Rising-edge sequencing infrastructure (shared by all
        # button-sequencing tasks). 2-tick minimum cycle.
        self.pressed_last_tick: bool = False
        self.sequence_step: int = 0
        # Snapshot the standard-field names so clear() can remove any
        # task-specific ad-hoc attributes set later.
        self._standard_fields: frozenset[str] = frozenset(
            set(self.__dict__.keys()) | {"_standard_fields"}
        )

    def clear(self) -> None:
        """Reset to initial values and remove any task-specific attributes.

        Called by the framework when the active task changes (different
        task type or different parameters).
        """
        # Remove ad-hoc attributes set by tasks (anything not standard).
        for name in list(self.__dict__.keys()):
            if name not in self._standard_fields:
                delattr(self, name)
        # Reset standard fields.
        self.ticks_active = 0
        self.commands_sent = 0
        self.last_command = None
        self.command_history.clear()
        self.pressed_last_tick = False
        self.sequence_step = 0

    def step_button_press(self, button: int) -> int:
        """Return ``button`` on a press tick or ``0`` on a release tick.

        Rising-edge sequencing alternates press/release based on
        ``pressed_last_tick``. Tasks call this each tick they want to press a
        button; the helper emits the required release tick automatically.
        """
        if self.pressed_last_tick:
            self.pressed_last_tick = False
            return 0

        self.pressed_last_tick = True
        return button


__all__ = [
    "ActionMemory",
]
