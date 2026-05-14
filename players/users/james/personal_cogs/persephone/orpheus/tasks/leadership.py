"""Leadership and usurpation tasks."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, ClassVar

from orpheus.task import ActCommand, Task
from orpheus.tasks._menu_nav import MenuNavigator
from orpheus.types import BUTTON_A, BUTTON_LEFT, BUTTON_RIGHT, View


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
        target = max(0, int(self.candidate))
        current = _current_usurp_cursor_index(belief_state, action_memory)
        candidate_count, count_is_known = _candidate_count(
            belief_state,
            target,
            current,
        )

        if count_is_known:
            current %= candidate_count
            target %= candidate_count

        if current == target:
            return ActCommand(buttons=action_memory.step_button_press(BUTTON_A))

        if count_is_known:
            right_distance = (target - current) % candidate_count
            left_distance = (current - target) % candidate_count
            if right_distance <= left_distance:
                button = BUTTON_RIGHT
                next_index = (current + 1) % candidate_count
            else:
                button = BUTTON_LEFT
                next_index = (current - 1) % candidate_count
        elif target > current:
            button = BUTTON_RIGHT
            next_index = current + 1
        else:
            button = BUTTON_LEFT
            next_index = max(0, current - 1)

        command = action_memory.step_button_press(button)
        if command:
            action_memory.usurp_cursor_index = next_index
        return ActCommand(buttons=command)


def _current_usurp_cursor_index(belief_state, action_memory) -> int:
    for source in _usurp_sources(belief_state):
        value = _state_value(
            source,
            "usurp_cursor_index",
            "candidate_cursor_index",
            "selected_candidate_index",
            "usurp_candidate_index",
            "cursor_index",
        )
        if value is not None:
            index = max(0, int(value))
            action_memory.usurp_cursor_index = index
            return index

    if not hasattr(action_memory, "usurp_cursor_index"):
        action_memory.usurp_cursor_index = 0
    return max(0, int(action_memory.usurp_cursor_index))


def _candidate_count(
    belief_state,
    target: int,
    current: int,
) -> tuple[int, bool]:
    for source in _usurp_sources(belief_state):
        count = _positive_int(
            _state_value(source, "usurp_candidate_count", "candidate_count")
        )
        if count is not None:
            return (count, True)

        for name in (
            "usurp_candidates",
            "candidates",
            "candidate_colors",
            "target_colors",
        ):
            values = _state_value(source, name)
            if values is not None:
                try:
                    count = len(values)
                except TypeError:
                    pass
                else:
                    if count > 0:
                        return (count, True)

    player_count = _positive_int(_state_value(belief_state, "player_count"))
    if player_count is not None:
        return (player_count, True)

    return (max(target + 1, current + 1, 1), False)


def _usurp_sources(belief_state):
    yield belief_state

    extra = _state_value(belief_state, "extra")
    if isinstance(extra, dict):
        yield extra

    global_chat = _state_value(belief_state, "global_chat")
    if global_chat is not None:
        yield global_chat
        candidate = _state_value(global_chat, "usurp_candidate")
        if candidate is not None:
            yield candidate

    candidate = _state_value(belief_state, "usurp_candidate")
    if candidate is not None:
        yield candidate


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


__all__ = [
    "PassLeadershipTask",
    "TakeLeadershipTask",
    "VoteUsurpTask",
]
