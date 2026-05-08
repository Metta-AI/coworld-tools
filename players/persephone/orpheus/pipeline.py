"""Inner-loop pipeline for Orpheus perception, belief, decide, and act phases."""

from __future__ import annotations

import dataclasses
from collections import deque
from collections.abc import Callable
from enum import Enum
import zlib

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
        verbose_logging = self._verbose_logging_enabled()

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

        belief_snapshot_before = None
        cooldowns_before_belief_update = None
        minimap_sighting_count_before = None
        occupancy_grid_before = None
        if verbose_logging:
            belief_snapshot_before = _snapshot_belief_state(self.belief_state)
            cooldowns_before_belief_update = dict(self.belief_state.cooldowns)
            minimap_sighting_count_before = len(self.belief_state.minimap_sightings)
            occupancy_grid_before = _snapshot_occupancy_grid(
                self.belief_state.occupancy_grid
            )

        self._belief_update(perception)
        self._refresh_logger_metadata()
        self._log_event(
            "perception",
            {"perception": repr(perception)},
            level=LogLevel.VERBOSE,
        )
        if verbose_logging:
            assert belief_snapshot_before is not None
            assert cooldowns_before_belief_update is not None
            assert minimap_sighting_count_before is not None
            self._emit_belief_diff(belief_snapshot_before)
            self._emit_cooldown_changes(
                cooldowns_before_belief_update,
                self.belief_state.cooldowns,
                phase="belief_update",
            )
            self._emit_minimap_sightings(minimap_sighting_count_before)
            self._emit_grid_change(
                occupancy_grid_before,
                self.belief_state.occupancy_grid,
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

        action_memory_before_act = None
        cooldowns_before_act = None
        if verbose_logging:
            action_memory_before_act = _snapshot_action_memory(self.action_memory)
            cooldowns_before_act = dict(self.belief_state.cooldowns)

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
        if verbose_logging:
            assert cooldowns_before_act is not None
            self._emit_cooldown_changes(
                cooldowns_before_act,
                self.belief_state.cooldowns,
                phase="act",
            )

        # Action memory is updated before POST_ACT so hooks see post-tick state.
        self.action_memory.ticks_active += 1
        self.action_memory.last_command = command
        self.action_memory.command_history.append(command)
        if _command_is_non_noop(command):
            self.action_memory.commands_sent += 1

        if verbose_logging:
            assert action_memory_before_act is not None
            self._emit_action_memory_mutation(action_memory_before_act)

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

    def _verbose_logging_enabled(self) -> bool:
        return isinstance(self.logger, Logger) and self.logger.level >= LogLevel.VERBOSE

    def _emit_belief_diff(self, before: dict[str, object]) -> None:
        after = _snapshot_belief_state(self.belief_state)
        diff = _diff_snapshots(before, after, large_fields={"players"})
        for list_field in ("chat_history", "minimap_sightings"):
            if list_field in diff:
                diff[list_field] = _summarize_list_diff(
                    before.get(list_field),
                    after.get(list_field),
                )
        if diff:
            self._log_event(
                "belief_diff",
                {"diff": diff},
                level=LogLevel.VERBOSE,
            )

    def _emit_cooldown_changes(
        self,
        before: dict[str, int],
        after: dict[str, int],
        *,
        phase: str,
    ) -> None:
        changes = _dict_value_changes(before, after)
        if changes:
            self._log_event(
                "cooldown_change",
                {"phase": phase, "changes": changes},
                level=LogLevel.VERBOSE,
            )

    def _emit_minimap_sightings(self, previous_count: int) -> None:
        new_sightings = self.belief_state.minimap_sightings[previous_count:]
        if new_sightings:
            self._log_event(
                "minimap_sighting",
                {
                    "count": len(new_sightings),
                    "sightings": [_snapshot_value(s) for s in new_sightings],
                },
                level=LogLevel.VERBOSE,
            )

    def _emit_grid_change(
        self,
        before: dict[str, object] | None,
        after_grid: object | None,
    ) -> None:
        after = _snapshot_occupancy_grid(after_grid)
        if before != after:
            self._log_event(
                "grid_change",
                {"changed": True, "old": before, "new": after},
                level=LogLevel.VERBOSE,
            )

    def _emit_action_memory_mutation(self, before: dict[str, object]) -> None:
        after = _snapshot_action_memory(self.action_memory)
        diff = _diff_snapshots(before, after)
        if diff:
            self._log_event(
                "action_memory_mutation",
                {"diff": diff, "changes": diff},
                level=LogLevel.VERBOSE,
            )

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


def _snapshot_belief_state(belief_state: BeliefState) -> dict[str, object]:
    """Return a JSON-safe, mutation-isolated snapshot of dataclass fields."""
    return {
        field.name: _snapshot_belief_field(
            field.name,
            getattr(belief_state, field.name),
        )
        for field in dataclasses.fields(belief_state)
    }


def _snapshot_belief_field(name: str, value: object) -> object:
    if name == "occupancy_grid":
        return _snapshot_occupancy_grid(value)
    return _snapshot_value(value)


def _snapshot_action_memory(action_memory: ActionMemory) -> dict[str, object]:
    return {
        name: _snapshot_value(value)
        for name, value in vars(action_memory).items()
        if not name.startswith("_")
    }


def _snapshot_value(value: object) -> object:
    if dataclasses.is_dataclass(value):
        return {
            field.name: _snapshot_value(getattr(value, field.name))
            for field in dataclasses.fields(value)
        }
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict):
        return {
            _snapshot_key(key): _snapshot_value(item)
            for key, item in value.items()
        }
    if isinstance(value, deque):
        return [_snapshot_value(item) for item in value]
    if isinstance(value, list):
        return [_snapshot_value(item) for item in value]
    if isinstance(value, tuple):
        return [_snapshot_value(item) for item in value]
    if isinstance(value, set | frozenset):
        return sorted(_snapshot_value(item) for item in value)
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, np.ndarray):
        return {
            "shape": list(value.shape),
            "dtype": str(value.dtype),
            "checksum": _array_checksum(value),
        }
    if isinstance(value, str | int | float | bool | type(None)):
        return value
    return repr(value)


def _snapshot_key(key: object) -> str | int | float | bool | None:
    if isinstance(key, str | int | float | bool | type(None)):
        return key
    if isinstance(key, Enum):
        return str(key.value)
    return repr(key)


def _snapshot_occupancy_grid(grid: object | None) -> dict[str, object] | None:
    if grid is None:
        return None

    cells = getattr(grid, "cells", None)
    viewport_confirmed = getattr(grid, "viewport_confirmed", None)
    snapshot: dict[str, object] = {
        "room_size": _snapshot_value(getattr(grid, "room_size", None)),
        "resolution": getattr(grid, "resolution", None),
        "grid_w": getattr(grid, "grid_w", None),
        "grid_h": getattr(grid, "grid_h", None),
    }
    if isinstance(cells, np.ndarray):
        counts = np.bincount(cells.ravel().astype(np.int64), minlength=3)
        other_count = int(counts[3:].sum()) if len(counts) > 3 else 0
        snapshot.update(
            {
                "shape": list(cells.shape),
                "cell_counts": {
                    "unknown": int(counts[0]),
                    "free": int(counts[1]),
                    "wall": int(counts[2]),
                    "other": other_count,
                },
                "cells_checksum": _array_checksum(cells),
            }
        )
    if isinstance(viewport_confirmed, np.ndarray):
        snapshot.update(
            {
                "viewport_confirmed_count": int(np.count_nonzero(viewport_confirmed)),
                "viewport_confirmed_checksum": _array_checksum(viewport_confirmed),
            }
        )
    return snapshot


def _array_checksum(array: np.ndarray) -> str:
    data = np.ascontiguousarray(array).tobytes()
    return f"{zlib.crc32(data) & 0xFFFFFFFF:08x}"


def _diff_snapshots(
    before: dict[str, object],
    after: dict[str, object],
    large_fields: set[str] | None = None,
) -> dict[str, dict[str, object]]:
    large_fields = large_fields or set()
    diff: dict[str, dict[str, object]] = {}
    for name in sorted(set(before) | set(after)):
        old = before.get(name)
        new = after.get(name)
        if old == new:
            continue
        if name in large_fields and isinstance(old, dict) and isinstance(new, dict):
            diff[name] = _summarize_dict_diff(old, new)
        else:
            diff[name] = {"old": old, "new": new}
    return diff


def _summarize_dict_diff(
    before: dict[object, object],
    after: dict[object, object],
) -> dict[str, object]:
    before_keys = set(before)
    after_keys = set(after)
    common_keys = before_keys & after_keys
    return {
        "old": {"count": len(before), "keys": _sorted_snapshot_keys(before_keys)},
        "new": {"count": len(after), "keys": _sorted_snapshot_keys(after_keys)},
        "added_keys": _sorted_snapshot_keys(after_keys - before_keys),
        "removed_keys": _sorted_snapshot_keys(before_keys - after_keys),
        "changed_keys": _sorted_snapshot_keys(
            key for key in common_keys if before[key] != after[key]
        ),
    }


def _summarize_list_diff(old: object, new: object) -> dict[str, object]:
    old_list = old if isinstance(old, list) else []
    new_list = new if isinstance(new, list) else []
    summary: dict[str, object] = {
        "old": {"len": len(old_list)},
        "new": {"len": len(new_list)},
    }
    if len(new_list) >= len(old_list) and new_list[: len(old_list)] == old_list:
        appended = new_list[len(old_list) :]
        summary["appended_count"] = len(appended)
        if appended:
            summary["appended"] = appended
    else:
        summary["changed"] = True
    return summary


def _dict_value_changes(
    before: dict[object, object],
    after: dict[object, object],
) -> dict[str, dict[str, object]]:
    changes: dict[str, dict[str, object]] = {}
    for key in sorted(set(before) | set(after), key=lambda item: str(item)):
        old = before.get(key)
        new = after.get(key)
        if old == new:
            continue
        changes[str(key)] = {
            "old": _snapshot_value(old),
            "new": _snapshot_value(new),
            "change": _change_type(old, new),
        }
    return changes


def _change_type(old: object, new: object) -> str:
    if old is None:
        return "added"
    if new is None:
        return "expired"
    if isinstance(old, int) and isinstance(new, int):
        if new < old:
            return "decremented"
        if new > old:
            return "increased"
    return "changed"


def _sorted_snapshot_keys(keys) -> list[object]:
    return sorted((_snapshot_key(key) for key in keys), key=lambda item: str(item))


__all__ = [
    "Pipeline",
]
