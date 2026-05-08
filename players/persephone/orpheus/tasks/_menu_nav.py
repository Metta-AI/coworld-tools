"""Approximate whisper-menu navigation for Stage 4 tasks.

The live menu is driven by rising-edge button presses and only partially
observable from pixels. This navigator trusts ``belief_state.menu_state`` when
available and otherwise tracks coarse progress on ``ActionMemory``. It uses a
small step grammar:

- ``("category", "ROLE")``
- ``("item", "R.OFFER")``
- ``("confirm",)``
- ``("target", player_index)``
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from orpheus.perception.types import ChatroomBarState
from orpheus.task import ActCommand
from orpheus.types import (
    BUTTON_A,
    BUTTON_B,
    BUTTON_DOWN,
    BUTTON_LEFT,
    BUTTON_RIGHT,
    BUTTON_UP,
)

MenuStep = tuple[Any, ...]

CATEGORY_ORDER = ["EXIT", "COLOR", "ROLE", "LEADER"]

ITEM_ORDER_BY_CATEGORY: dict[str, tuple[tuple[str, ...], ...]] = {
    "EXIT": (("EXIT",),),
    "COLOR": (
        ("C.OFFER", "C.UNOFFR", "OFFER", "UNOFFR"),
        ("C.ACCPT", "ACCPT"),
    ),
    "ROLE": (
        ("ROLE",),
        ("R.OFFER", "R.UNOFFR", "OFFER", "UNOFFR"),
        ("R.ACCPT", "ACCPT"),
    ),
    "LEADER": (
        ("PASS",),
        ("TAKE",),
        ("GRANT",),
    ),
}


@dataclass(frozen=True)
class MenuNavigator:
    """State-light menu sequencer backed by ActionMemory ad-hoc fields."""

    steps: tuple[MenuStep, ...]

    def __init__(self, steps: Sequence[MenuStep]):
        object.__setattr__(self, "steps", tuple(steps))

    def next_command(self, belief_state, action_memory) -> ActCommand:
        """Return the next menu-navigation command for this tick."""
        if not hasattr(action_memory, "menu_step"):
            action_memory.menu_step = 0

        while action_memory.menu_step < len(self.steps):
            step = self.steps[action_memory.menu_step]
            kind = step[0]

            if kind == "category":
                command = self._handle_category(
                    belief_state,
                    action_memory,
                    str(step[1]),
                )
            elif kind == "item":
                command = self._handle_item(
                    belief_state,
                    action_memory,
                    str(step[1]),
                )
            elif kind == "confirm":
                return self._press_and_advance(action_memory, BUTTON_A)
            elif kind == "target":
                command = self._handle_target(
                    belief_state,
                    action_memory,
                    int(step[1]),
                )
            else:
                raise ValueError(f"unknown menu step: {kind!r}")

            if command is None:
                action_memory.menu_step += 1
                action_memory.sequence_step = action_memory.menu_step
                continue
            return command

        action_memory.sequence_step = action_memory.menu_step
        return _release_or_noop(action_memory)

    def _handle_category(
        self,
        belief_state,
        action_memory,
        expected: str,
    ) -> ActCommand | None:
        state = _menu_state(belief_state)
        if _bar_is_default(_state_value(state, "bar", "bottom_bar")):
            return _button_command(action_memory, BUTTON_B)

        current = _state_value(state, "category", "menu_category")
        if _matches(current, expected):
            return None

        button = _shortest_cycle_button(
            current,
            expected,
            CATEGORY_ORDER,
            forward_button=BUTTON_RIGHT,
            backward_button=BUTTON_LEFT,
        )
        return _button_command(action_memory, button or BUTTON_RIGHT)

    def _handle_item(
        self,
        belief_state,
        action_memory,
        expected: str,
    ) -> ActCommand | None:
        state = _menu_state(belief_state)
        if _bar_is_default(_state_value(state, "bar", "bottom_bar")):
            return _button_command(action_memory, BUTTON_B)

        current = _state_value(state, "item", "menu_item")
        if _matches(current, expected):
            return None

        category = _state_value(state, "category", "menu_category")
        item_order = _item_order_for_category(category)
        button = (
            _shortest_cycle_button(
                current,
                expected,
                item_order,
                forward_button=BUTTON_DOWN,
                backward_button=BUTTON_UP,
            )
            if item_order is not None
            else None
        )
        return _button_command(action_memory, button or BUTTON_DOWN)

    def _handle_target(
        self,
        belief_state,
        action_memory,
        target_index: int,
    ) -> ActCommand | None:
        state = _menu_state(belief_state)
        bar = _state_value(state, "bar", "bottom_bar")
        if not _bar_is_target_picker(bar):
            return _release_or_noop(action_memory)

        current_index = _current_target_index(state, action_memory)
        if current_index == target_index:
            if self._next_step_is_confirm(action_memory):
                return None
            return self._press_and_advance(action_memory, BUTTON_A)

        target_count = max(
            len(_state_value(state, "target_colors", default=[]) or []),
            target_index + 1,
            current_index + 1,
            1,
        )
        if target_index > current_index:
            button = BUTTON_RIGHT
            next_index = (current_index + 1) % target_count
        else:
            button = BUTTON_LEFT
            next_index = (current_index - 1) % target_count

        command = action_memory.step_button_press(button)
        if command:
            action_memory.menu_target_index = next_index
        return ActCommand(buttons=command)

    def _press_and_advance(self, action_memory, button: int) -> ActCommand:
        command = action_memory.step_button_press(button)
        if command:
            action_memory.menu_step += 1
            action_memory.sequence_step = action_memory.menu_step
        return ActCommand(buttons=command)

    def _next_step_is_confirm(self, action_memory) -> bool:
        next_index = action_memory.menu_step + 1
        return next_index < len(self.steps) and self.steps[next_index][0] == "confirm"


def _button_command(action_memory, button: int) -> ActCommand:
    return ActCommand(buttons=action_memory.step_button_press(button))


def _release_or_noop(action_memory) -> ActCommand:
    if action_memory.pressed_last_tick:
        action_memory.pressed_last_tick = False
    return ActCommand()


def _menu_state(belief_state) -> Any:
    return getattr(belief_state, "menu_state", None) or {}


def _state_value(state, *names: str, default=None):
    for name in names:
        if isinstance(state, dict) and name in state:
            return state[name]
        if hasattr(state, name):
            return getattr(state, name)
    return default


def _bar_is_default(value) -> bool:
    return _enumish_name(value) in {"", "DEFAULT", "NONE"}


def _bar_is_target_picker(value) -> bool:
    return _enumish_name(value) in {"TARGET", "TARGET_PICKER"}


def _enumish_name(value) -> str:
    if value is None:
        return ""
    if isinstance(value, ChatroomBarState):
        return value.name
    text = str(value)
    if "." in text:
        text = text.rsplit(".", 1)[-1]
    return text.upper()


def _matches(current, expected: str) -> bool:
    current_norm = _normalize_label(current)
    expected_norm = _normalize_label(expected)
    if current_norm == expected_norm:
        return True
    if "." in expected_norm:
        return current_norm == expected_norm.split(".", 1)[1]
    return False


def _normalize_label(value) -> str:
    if value is None:
        return ""
    return str(value).upper().replace(" ", "")


def _current_target_index(state, action_memory) -> int:
    for name in (
        "target_cursor_index",
        "target_index",
        "selected_target_index",
        "selected_index",
        "cursor_index",
    ):
        value = _state_value(state, name)
        if value is not None:
            action_memory.menu_target_index = int(value)
            return int(value)

    if not hasattr(action_memory, "menu_target_index"):
        action_memory.menu_target_index = 0
    return int(action_memory.menu_target_index)


def _item_order_for_category(category) -> tuple[tuple[str, ...], ...] | None:
    normalized = _normalize_label(category)
    return ITEM_ORDER_BY_CATEGORY.get(normalized)


def _shortest_cycle_button(
    current,
    expected,
    order: Sequence[str | Sequence[str]],
    *,
    forward_button: int,
    backward_button: int,
) -> int | None:
    current_index = _cycle_index(current, order)
    expected_index = _cycle_index(expected, order)
    if current_index is None or expected_index is None or current_index == expected_index:
        return None

    count = len(order)
    forward_distance = (expected_index - current_index) % count
    backward_distance = (current_index - expected_index) % count
    if forward_distance <= backward_distance:
        return forward_button
    return backward_button


def _cycle_index(value, order: Sequence[str | Sequence[str]]) -> int | None:
    for index, entry in enumerate(order):
        labels = (entry,) if isinstance(entry, str) else entry
        if any(_label_matches(value, label) for label in labels):
            return index
    return None


def _label_matches(value, expected: str) -> bool:
    return _matches(value, expected) or _matches(expected, value)


__all__ = ["CATEGORY_ORDER", "MenuNavigator", "MenuStep"]
