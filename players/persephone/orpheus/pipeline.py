"""Inner-loop pipeline for Orpheus perception, belief, decide, and act phases."""

from __future__ import annotations

import dataclasses
from collections.abc import Callable

import numpy as np

from orpheus import belief_update
from orpheus.action_memory import ActionMemory
from orpheus.belief_state import BeliefState
from orpheus.buffers import BeliefBuffer
from orpheus.hooks import HookPoint, HookRegistry
from orpheus.logging import LogLevel, Logger
from orpheus.mode import Mode, ModeDirective, ModeRegistry
from orpheus.mode_buffer import ModeBuffer
from orpheus.perception import parse_frame
from orpheus.perception.types import FramePerception
from orpheus.task import ActCommand, Task
from orpheus.types import RESET_MASK


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
        hook_registry: HookRegistry | None = None,
        current_mode_name: str = "idle",
        logger: Callable[[str], None] | None = None,
        mode_buffer: ModeBuffer | None = None,
        belief_buffer: BeliefBuffer | None = None,
        fallback_directive: ModeDirective | None = None,
        watchdog_threshold: int = 120,
    ) -> None:
        """Create an inner-loop pipeline with fresh owned runtime state."""
        self.belief_state: BeliefState = BeliefState()
        self.action_memory: ActionMemory = ActionMemory()
        self.current_mode: Mode = initial_mode
        self.current_task: Task | None = None
        self.mode_registry: ModeRegistry = mode_registry
        self.send_input: Callable[[int], None] = send_input
        self.send_chat: Callable[[str], None] = send_chat
        self.hook_registry: HookRegistry = (
            hook_registry if hook_registry is not None else HookRegistry()
        )
        self.current_mode_name: str = current_mode_name
        self.mode_buffer: ModeBuffer = (
            mode_buffer if mode_buffer is not None else ModeBuffer()
        )
        self.belief_buffer: BeliefBuffer = (
            belief_buffer if belief_buffer is not None else BeliefBuffer()
        )
        self.fallback_directive: ModeDirective | None = fallback_directive
        self.watchdog_threshold: int = watchdog_threshold
        self.ticks_since_last_mode_directive: int = 0
        self._watchdog_fired: bool = False
        self.logger: Callable[[str], None] | None = logger

    def tick(self, frame: bytes | bytearray | np.ndarray) -> ActCommand:
        """Run one inner-loop tick for `frame` and return the emitted command."""
        self._attach_logger_to_belief_state()
        self._refresh_logger_metadata()

        frame = self.hook_registry.dispatch(
            HookPoint.PRE_PERCEPTION,
            self.current_mode_name,
            self.belief_state,
            frame,
            logger=self.logger,
        )

        perception = parse_frame(frame)
        previous_view = self.belief_state.view

        self.hook_registry.dispatch(
            HookPoint.POST_PERCEPTION,
            self.current_mode_name,
            self.belief_state,
            frame,
            perception,
            logger=self.logger,
        )

        self.hook_registry.dispatch(
            HookPoint.PRE_BELIEF_UPDATE,
            self.current_mode_name,
            self.belief_state,
            perception,
            logger=self.logger,
        )

        self._belief_update(perception)
        self._refresh_logger_metadata()
        self._log_event(
            "perception",
            {"perception": repr(perception)},
            level=LogLevel.VERBOSE,
        )
        if self.belief_state.view != previous_view:
            self._log_event(
                "view_transition",
                {
                    "old": _view_name(previous_view),
                    "new": _view_name(self.belief_state.view),
                },
            )

        self.hook_registry.dispatch(
            HookPoint.POST_BELIEF_UPDATE,
            self.current_mode_name,
            self.belief_state,
            logger=self.logger,
        )

        # The async outer loop consumes deep-copied snapshots from this buffer.
        # BeliefBuffer owns the copy so the inner loop stays non-blocking here.
        self.belief_buffer.push(self.belief_state, self.action_memory)

        consumed = self._consume_mode_buffer()
        if consumed:
            # Any consumed directive, including reaffirmations and invalid
            # directives, proves the outer loop is still producing output.
            self.ticks_since_last_mode_directive = 0
            self._watchdog_fired = False
        else:
            self.ticks_since_last_mode_directive += 1
            if (
                not self._watchdog_fired
                and self.ticks_since_last_mode_directive >= self.watchdog_threshold
            ):
                fallback = self.fallback_directive or ModeDirective(
                    mode=self.current_mode_name,
                    params=self.current_mode.params,
                )
                tick = getattr(self.belief_state, "tick", None)
                legacy = (
                    f"watchdog_fired: fallback={fallback.mode}"
                    if tick is None
                    else f"watchdog_fired: tick={tick} fallback={fallback.mode}"
                )
                self._emit(
                    "watchdog_activation",
                    {
                        "fallback_mode": fallback.mode,
                        "reason": "directive_timeout",
                    },
                    legacy,
                )
                self.mode_buffer.push(fallback, None)
                # Apply the fallback immediately; _consume_mode_buffer mutates
                # mode state only, leaving watchdog accounting centralized here.
                self._consume_mode_buffer()
                self.ticks_since_last_mode_directive = 0
                self._watchdog_fired = True

        self.hook_registry.dispatch(
            HookPoint.PRE_DECIDE,
            self.current_mode_name,
            self.belief_state,
            self.action_memory,
            logger=self.logger,
        )

        task = self.current_mode.select_task(
            self.belief_state,
            self.action_memory,
        )
        self._log_event(
            "select_task",
            _task_event_data(task),
            level=LogLevel.DECISIONS,
        )
        if task is not None:
            if self.current_task is None:
                old_task = self.current_task
                self.current_task = task
                self._log_event(
                    "task_change",
                    {"old": _task_name(old_task), "new": _task_name(self.current_task)},
                )
            elif not _tasks_equivalent(task, self.current_task):
                old_task = self.current_task
                self.action_memory.clear()
                self.current_task = task
                self._log_event(
                    "task_change",
                    {"old": _task_name(old_task), "new": _task_name(self.current_task)},
                )

        self.belief_state.current_task = self.current_task
        self._refresh_logger_metadata()

        self.hook_registry.dispatch(
            HookPoint.POST_DECIDE,
            self.current_mode_name,
            self.belief_state,
            self.action_memory,
            logger=self.logger,
        )

        self.hook_registry.dispatch(
            HookPoint.PRE_ACT,
            self.current_mode_name,
            self.belief_state,
            self.action_memory,
            logger=self.logger,
        )

        if self.current_task is None:
            command = ActCommand()
        elif self.belief_state.view not in self.current_task.valid_views:
            self._log_event(
                "valid_views_mismatch",
                {
                    "view": _view_name(self.belief_state.view),
                    "valid_views": [
                        _view_name(view) for view in self.current_task.valid_views
                    ],
                    "task_type": _task_name(self.current_task),
                },
                level=LogLevel.DECISIONS,
            )
            command = ActCommand()
        else:
            command = self.current_task.select_action(
                self.belief_state,
                self.action_memory,
            )
        self._log_event(
            "act_command",
            {"command": str(command)},
            level=LogLevel.VERBOSE,
        )
        # TODO Stage 8 follow-up: add verbose belief_diff, cooldown_change,
        # minimap_sighting, grid_change, and action_memory_mutation events
        # once those mutation paths have stable diff hooks.

        # Action memory is updated before POST_ACT so hooks see post-tick state.
        self.action_memory.ticks_active += 1
        self.action_memory.last_command = command
        self.action_memory.command_history.append(command)
        if _command_is_non_noop(command):
            self.action_memory.commands_sent += 1

        self._send_act_command(command)

        self.hook_registry.dispatch(
            HookPoint.POST_ACT,
            self.current_mode_name,
            self.belief_state,
            self.action_memory,
            command,
            logger=self.logger,
        )

        return command

    def _belief_update(self, perception: FramePerception) -> None:
        """Integrate perception output into the persistent belief state."""
        previous_view = self.belief_state.view
        belief_update.apply(self.belief_state, perception, previous_view)

    def _consume_mode_buffer(self) -> bool:
        """Consume a pending outer-loop mode directive, if one is available.

        Returns True iff an entry was consumed, even when that directive is a
        reaffirmation or is rejected as invalid. The watchdog uses this as an
        outer-loop liveness signal.
        """
        entry = self.mode_buffer.consume()
        if entry is None:
            return False

        directive, inferences = entry
        if inferences is not None:
            self.belief_state.inferences = inferences

        if not self._is_directive_valid(directive):
            self._emit(
                "invalid_directive",
                {
                    "directive": repr(directive),
                    "reason": self._directive_invalid_reason(directive),
                },
                f"invalid_directive: {directive!r}",
            )
            return True

        directive = self.hook_registry.dispatch_mode_switch(
            current_mode_name=self.current_mode_name,
            belief_state=self.belief_state,
            action_memory=self.action_memory,
            directive=directive,
            mode_registry=self.mode_registry,
            logger=self.logger,
        )

        current_directive = ModeDirective(
            mode=self.current_mode_name,
            params=self.current_mode.params,
        )
        if directive == current_directive:
            return True

        old_mode_name = self.current_mode_name
        self._log_event(
            "mode_switch_cleanup",
            {"old_mode": old_mode_name},
            level=LogLevel.DECISIONS,
        )
        self.current_mode.mode_switch_cleanup(
            self.belief_state,
            self.action_memory,
            directive,
        )

        new_mode_cls = self.mode_registry.get(directive.mode)
        assert new_mode_cls is not None
        new_mode = new_mode_cls()
        new_mode.params = directive.params
        self.current_mode = new_mode
        self.current_mode_name = directive.mode
        self._refresh_logger_metadata()

        self._log_event(
            "mode_enter",
            {"mode": self.current_mode_name, "directive": repr(directive)},
            level=LogLevel.DECISIONS,
        )
        self.current_mode.mode_enter(self.belief_state, self.action_memory)
        self._refresh_logger_metadata()
        self._log_event(
            "mode_transition",
            {
                "old": old_mode_name,
                "new": self.current_mode_name,
                "directive": repr(directive) if directive is not None else None,
            },
        )
        return True

    def _is_directive_valid(self, directive: ModeDirective) -> bool:
        """Return True when a directive targets a registered mode with valid params."""
        mode_cls = self.mode_registry.get(directive.mode)
        return mode_cls is not None and isinstance(
            directive.params,
            mode_cls.params_type,
        )

    def _directive_invalid_reason(self, directive: ModeDirective) -> str:
        mode_cls = self.mode_registry.get(directive.mode)
        if mode_cls is None:
            return "mode_not_registered"
        if not isinstance(directive.params, mode_cls.params_type):
            return "params_wrong_type"
        return "unknown"

    def _emit(
        self,
        category: str,
        data: dict,
        legacy_msg: str,
        level: LogLevel = LogLevel.EVENTS,
    ) -> None:
        if isinstance(self.logger, Logger):
            self.logger.event(category, data, level)
        elif self.logger is not None:
            self.logger(legacy_msg)

    def _log_event(
        self,
        category: str,
        data: dict,
        level: LogLevel = LogLevel.EVENTS,
    ) -> None:
        if isinstance(self.logger, Logger):
            self.logger.event(category, data, level)

    def _refresh_logger_metadata(self) -> None:
        if not isinstance(self.logger, Logger):
            return
        self.logger.update_metadata(
            tick=getattr(self.belief_state, "tick", None),
            view=_view_name(getattr(self.belief_state, "view", None)),
            mode=self.current_mode_name,
            task=_task_name(self.current_task),
        )

    def _attach_logger_to_belief_state(self) -> None:
        # Agent hooks/modes can use log_event(belief_state._logger, ...).
        setattr(
            self.belief_state,
            "_logger",
            self.logger if isinstance(self.logger, Logger) else None,
        )

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


def _task_name(task: Task | None) -> str | None:
    if task is None:
        return None
    return type(task).__name__


def _task_event_data(task: Task | None) -> dict:
    if task is None:
        return {"task": None}
    return {"task_type": type(task).__name__, "params": _task_params(task)}


def _task_params(task: Task) -> dict:
    if dataclasses.is_dataclass(task):
        return dataclasses.asdict(task)
    if hasattr(task, "__dict__"):
        return {
            key: value
            for key, value in vars(task).items()
            if not key.startswith("_")
        }
    return {}


def _view_name(view: object) -> str | None:
    if view is None:
        return None
    value = getattr(view, "value", None)
    if isinstance(value, str):
        return value
    return str(view)


__all__ = [
    "Pipeline",
]
