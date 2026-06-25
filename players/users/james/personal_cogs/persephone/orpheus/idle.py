"""Idle task and mode: built-in defaults that no-op every tick."""

from __future__ import annotations

from orpheus.mode import Mode, ModeDirective, ModeParams
from orpheus.task import ActCommand, Task
from orpheus.types import View


class IdleTask(Task):
    """Built-in default task. Emits noop ActCommand in any view."""

    valid_views: set[View] = set(View)

    def select_action(self, belief_state, action_memory) -> ActCommand:
        """Return a noop ActCommand."""
        return ActCommand()


class IdleMode(Mode):
    """Built-in default mode. Always returns IdleTask."""

    params_type = ModeParams

    def select_task(self, belief_state, action_memory) -> Task | None:
        """Return a fresh IdleTask for this tick."""
        return IdleTask()

    def mode_enter(self, belief_state, action_memory) -> None:
        """Perform no setup when entering idle mode."""
        pass

    def mode_switch_cleanup(
        self,
        belief_state,
        action_memory,
        new_mode_directive: ModeDirective,
    ) -> None:
        """Perform no cleanup when leaving idle mode."""
        pass


__all__ = [
    "IdleTask",
    "IdleMode",
]
