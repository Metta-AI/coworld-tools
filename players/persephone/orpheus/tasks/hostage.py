"""Hostage-selection task."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, ClassVar

from orpheus.task import ActCommand, Task
from orpheus.types import (
    BUTTON_A,
    BUTTON_B,
    BUTTON_DOWN,
    BUTTON_LEFT,
    BUTTON_RIGHT,
    BUTTON_UP,
    View,
)


HOSTAGE_GRID_COLS = 4


@dataclass(frozen=True)
class SelectHostagesTask(Task):
    """Toggle the requested hostage indices in the hostage-selection UI."""

    player_indices: tuple[int, ...]

    valid_views: ClassVar[frozenset[View]] = frozenset(
        {View.HOSTAGE_SELECT, View.GLOBAL_CHAT}
    )

    def select_action(self, belief_state, action_memory) -> ActCommand:
        if not hasattr(action_memory, "hostage_remaining"):
            action_memory.hostage_remaining = list(self.player_indices)
            action_memory.hostage_committed = False
            action_memory.hostage_cursor = (0, 0)

        if action_memory.hostage_remaining:
            target_index = max(0, int(action_memory.hostage_remaining[0]))
            player_count = _hostage_player_count(
                belief_state,
                action_memory,
                target_index,
            )
            current = _current_hostage_cursor(belief_state, action_memory)
            current = _normalize_cursor(current, player_count)
            target = _cursor_for_index(target_index)

            if current != target:
                button, next_cursor = _next_hostage_step(
                    current,
                    target,
                    player_count,
                )
                command = action_memory.step_button_press(button)
                if command:
                    action_memory.hostage_cursor = next_cursor
                return ActCommand(buttons=command)

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


def _current_hostage_cursor(belief_state, action_memory) -> tuple[int, int]:
    cursor_index = _perceived_hostage_cursor_index(belief_state)
    if cursor_index is not None:
        cursor = _cursor_for_index(cursor_index)
        action_memory.hostage_cursor = cursor
        return cursor

    if not hasattr(action_memory, "hostage_cursor"):
        action_memory.hostage_cursor = (0, 0)
    row, col = action_memory.hostage_cursor
    return (max(0, int(row)), max(0, int(col)))


def _perceived_hostage_cursor_index(belief_state) -> int | None:
    for source in _hostage_grid_sources(belief_state):
        value = _state_value(source, "cursor_index", "hostage_cursor_index")
        if value is not None:
            try:
                return max(0, int(value))
            except (TypeError, ValueError):
                return None
    return None


def _hostage_player_count(
    belief_state,
    action_memory,
    target_index: int,
) -> int:
    player_count = _positive_int(_state_value(belief_state, "player_count"))
    if player_count is not None:
        return max(player_count, target_index + 1, 1)

    for source in _hostage_grid_sources(belief_state):
        for name in ("eligible_colors", "candidates", "target_colors"):
            values = _state_value(source, name)
            if values is not None:
                try:
                    count = len(values)
                except TypeError:
                    continue
                if count > 0:
                    return max(count, target_index + 1, 1)

    cursor = getattr(action_memory, "hostage_cursor", (0, 0))
    cursor_index = int(cursor[0]) * HOSTAGE_GRID_COLS + int(cursor[1])
    return max(target_index + 1, cursor_index + 1, 1)


def _next_hostage_step(
    current: tuple[int, int],
    target: tuple[int, int],
    player_count: int,
) -> tuple[int, tuple[int, int]]:
    row, col = current
    target_row, target_col = target

    if row != target_row and _cell_exists(row + _sign(target_row - row), col, player_count):
        next_row = row + _sign(target_row - row)
        button = BUTTON_DOWN if next_row > row else BUTTON_UP
        return (button, (next_row, col))

    if col != target_col:
        next_col = col + _sign(target_col - col)
        button = BUTTON_RIGHT if next_col > col else BUTTON_LEFT
        return (button, (row, next_col))

    next_row = row + _sign(target_row - row)
    button = BUTTON_DOWN if next_row > row else BUTTON_UP
    return (button, (next_row, col))


def _normalize_cursor(cursor: tuple[int, int], player_count: int) -> tuple[int, int]:
    row, col = cursor
    max_row = (player_count - 1) // HOSTAGE_GRID_COLS
    row = min(max(0, int(row)), max_row)
    max_col = min(HOSTAGE_GRID_COLS - 1, player_count - 1 - row * HOSTAGE_GRID_COLS)
    col = min(max(0, int(col)), max_col)
    return (row, col)


def _cursor_for_index(index: int) -> tuple[int, int]:
    return (index // HOSTAGE_GRID_COLS, index % HOSTAGE_GRID_COLS)


def _cell_exists(row: int, col: int, player_count: int) -> bool:
    if row < 0 or col < 0 or col >= HOSTAGE_GRID_COLS:
        return False
    return row * HOSTAGE_GRID_COLS + col < player_count


def _sign(value: int) -> int:
    if value > 0:
        return 1
    if value < 0:
        return -1
    return 0


def _hostage_grid_sources(belief_state):
    hostage_selections = _state_value(belief_state, "hostage_selections")
    if hostage_selections is not None:
        yield hostage_selections

    hostage_grid = _state_value(belief_state, "hostage_grid")
    if hostage_grid is not None:
        yield hostage_grid

    global_chat = _state_value(belief_state, "global_chat")
    if global_chat is not None:
        hostage_grid = _state_value(global_chat, "hostage_grid")
        if hostage_grid is not None:
            yield hostage_grid

    extra = _state_value(belief_state, "extra")
    if isinstance(extra, dict):
        hostage_grid = _state_value(extra, "hostage_grid", "hostage_selections")
        if hostage_grid is not None:
            yield hostage_grid


def _positive_int(value) -> int | None:
    if value is None:
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    if parsed <= 0:
        return None
    return parsed


def _state_value(source: Any, *names: str):
    for name in names:
        if isinstance(source, dict) and name in source:
            return source[name]
        if hasattr(source, name):
            return getattr(source, name)
    return None


__all__ = ["SelectHostagesTask"]
