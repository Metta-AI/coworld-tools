"""Inner-loop pipeline for Orpheus perception, belief, decide, and act phases."""

from __future__ import annotations

from collections.abc import Callable

import numpy as np

from orpheus.action_memory import ActionMemory
from orpheus.belief_state import BeliefState
from orpheus.mode import Mode, ModeRegistry
from orpheus.perception import parse_frame
from orpheus.perception.types import FramePerception
from orpheus.task import ActCommand, Task
from orpheus.types import RESET_MASK, View


def _tasks_equivalent(a: Task, b: Task) -> bool:
    """Stage 1 task-equality approximation.

    Returns True iff `a` and `b` are the same concrete Task type with the
    same instance state (`vars(a) == vars(b)`). Stage 4 will move tasks to
    frozen dataclasses where `==` works directly; this helper avoids
    treating every fresh `IdleTask()` as a task change in Stage 1.
    """
    return type(a) is type(b) and vars(a) == vars(b)


class Pipeline:
    """Per-tick inner loop that turns frames into protocol commands."""

    def __init__(
        self,
        initial_mode: Mode,
        mode_registry: ModeRegistry,
        send_input: Callable[[int], None],
        send_chat: Callable[[str], None],
    ) -> None:
        """Create an inner-loop pipeline with fresh owned runtime state."""
        self.belief_state: BeliefState = BeliefState()
        self.action_memory: ActionMemory = ActionMemory()
        self.current_mode: Mode = initial_mode
        self.current_task: Task | None = None
        self.mode_registry: ModeRegistry = mode_registry
        self.send_input: Callable[[int], None] = send_input
        self.send_chat: Callable[[str], None] = send_chat

    def tick(self, frame: bytes | bytearray | np.ndarray) -> ActCommand:
        """Run one inner-loop tick for `frame` and return the emitted command."""
        perception = parse_frame(frame)
        self._belief_update(perception)

        # TODO Stage 6: consume the outer-loop mode buffer before decide.

        task = self.current_mode.select_task(
            self.belief_state,
            self.action_memory,
        )
        if task is not None:
            if self.current_task is None:
                self.current_task = task
            elif not _tasks_equivalent(task, self.current_task):
                self.action_memory.clear()
                self.current_task = task

        self.belief_state.current_task = self.current_task

        if self.current_task is None:
            command = ActCommand()
        elif self.belief_state.view not in self.current_task.valid_views:
            command = ActCommand()
        else:
            command = self.current_task.select_action(
                self.belief_state,
                self.action_memory,
            )

        self.action_memory.ticks_active += 1
        self.action_memory.last_command = command
        self.action_memory.command_history.append(command)
        if _command_is_non_noop(command):
            self.action_memory.commands_sent += 1

        self._send_act_command(command)
        return command

    def _belief_update(self, perception: FramePerception) -> None:
        """Apply Stage 1 universal belief updates from perception."""
        bs = self.belief_state
        prev_in_whisper = bs.in_whisper

        bs.tick += 1
        bs.view = perception.view
        bs.in_whisper = perception.view == View.WHISPER

        if prev_in_whisper and not bs.in_whisper:
            bs.whisper_occupants = []
            bs.pending_offers = {"role": False, "color": False}
            bs.pending_entry = None
            bs.menu_state = None

        expired: list[str] = []
        for key, value in list(bs.cooldowns.items()):
            if value > 0:
                bs.cooldowns[key] = value - 1
            if bs.cooldowns[key] <= 0:
                expired.append(key)
        for key in expired:
            del bs.cooldowns[key]

        # TODO Stage 2: per-view updates (lobby, role_reveal, overworld,
        # whisper, etc.).

    def _send_act_command(self, command: ActCommand) -> None:
        """Lower an ActCommand into the transport callables."""
        if command.reset_input:
            self.send_input(RESET_MASK)
            return
        self.send_input(command.buttons & 0x7F)
        if command.chat_text is not None:
            self.send_chat(command.chat_text)


def _command_is_non_noop(command: ActCommand) -> bool:
    """Return True when `command` has any externally visible effect."""
    return (
        command.reset_input
        or command.buttons != 0
        or command.chat_text is not None
    )


__all__ = [
    "Pipeline",
]
