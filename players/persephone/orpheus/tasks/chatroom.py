"""Whisper lifecycle tasks."""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

from orpheus.logging import LogLevel, log_event
from orpheus.task import ActCommand, Task
from orpheus.tasks._menu_nav import MenuNavigator
from orpheus.tasks.movement import _distance, _movement_command_to, _position2d
from orpheus.tasks.view_management import OPEN_VIEW_VIEWS
from orpheus.types import (
    BUTTON_A,
    BUTTON_B,
    BUTTON_DOWN,
    BUTTON_LEFT,
    BUTTON_RIGHT,
    BUTTON_SELECT,
    BUTTON_UP,
    View,
)

ENTRY_DISTANCE_PX = 20.0
RECENT_WHISPER_TICKS = 60
_INITIATE_WHISPER_STATE_KEY = "_initiate_whisper_state"
_INITIATE_LAST_ENTRY_BUTTON_TICK_KEY = "_initiate_last_entry_button_tick"
_INITIATE_RETRY_INTERVAL_TICKS = 4
_INITIATE_MAX_TICKS = 120
_ENTRY_RETRY_INTERVAL_TICKS = 72
_ENTRY_INITIATE_MAX_TICKS = 192
_ENTRY_SWEEP_GOAL_KEY = "move_and_initiate_goal"
_ENTRY_SWEEP_TICKS_KEY = "move_and_initiate_sweep_ticks"
_ENTRY_SWEEP_RADIUS = 16
_ENTRY_SWEEP_LEG_TICKS = 6
_GOAL_REPATH_DISTANCE = 5
_RENDEZVOUS_SWEEP_GOAL_KEY = "rendezvous_entry_sweep_goal"
_RENDEZVOUS_SWEEP_TICKS_KEY = "rendezvous_entry_sweep_ticks"
_RENDEZVOUS_SWEEP_RADIUS = 24
_RENDEZVOUS_SWEEP_LEG_TICKS = 10
_DIRECT_APPROACH_TICKS_KEY = "direct_approach_ticks"


@dataclass(frozen=True)
class CreateWhisperTask(Task):
    """Create a new whisper at the current position."""

    valid_views: ClassVar[frozenset[View]] = OPEN_VIEW_VIEWS

    def select_action(self, belief_state, action_memory) -> ActCommand:
        return ActCommand(buttons=action_memory.step_button_press(BUTTON_A))


@dataclass(frozen=True)
class InitiateWhisperTask(Task):
    target_index: int | None = None
    use_button_b: bool = False

    valid_views: ClassVar[frozenset[View]] = OPEN_VIEW_VIEWS

    def select_action(self, belief_state, action_memory) -> ActCommand:
        button = _initiate_retry_button(
            belief_state,
            self.target_index,
            self.use_button_b,
        )
        if button and self.use_button_b:
            position = _position2d(getattr(belief_state, "position", None))
            target_position = None
            if self.target_index is not None:
                player = getattr(belief_state, "players", {}).get(self.target_index)
                target_position = _position2d(getattr(player, "position", None))
            goal = target_position or position
            close_to_goal = (
                position is not None
                and goal is not None
                and _distance(position, goal) <= ENTRY_DISTANCE_PX
            )
            _log_entry_button_pulse(
                belief_state,
                task_type=type(self).__name__,
                target_index=self.target_index,
                goal=goal,
                position=position,
                close_to_goal=close_to_goal,
                use_button_b=self.use_button_b,
            )
        return ActCommand(buttons=button)

    @staticmethod
    def has_failed(belief_state) -> bool:
        state = belief_state.extra.get(_INITIATE_WHISPER_STATE_KEY)
        return isinstance(state, dict) and state.get("failed", False)

    @staticmethod
    def clear_state(belief_state) -> None:
        belief_state.extra.pop(_INITIATE_WHISPER_STATE_KEY, None)


def _initiate_retry_button(
    belief_state,
    target_index: int | None,
    use_button_b: bool,
    *,
    entry_close_key: bool = False,
) -> int:
    signature = (target_index, use_button_b, entry_close_key)
    state = belief_state.extra.get(_INITIATE_WHISPER_STATE_KEY)
    retry_interval = (
        _ENTRY_RETRY_INTERVAL_TICKS if use_button_b else _INITIATE_RETRY_INTERVAL_TICKS
    )
    current_tick = getattr(belief_state, "tick", None)
    if not isinstance(state, dict) or state.get("signature") != signature:
        state = {"ticks": 0, "signature": signature}
        belief_state.extra[_INITIATE_WHISPER_STATE_KEY] = state
    elif isinstance(current_tick, int):
        last_tick = state.get("last_tick")
        if isinstance(last_tick, int) and current_tick - last_tick > retry_interval:
            state = {"ticks": 0, "signature": signature}
            belief_state.extra[_INITIATE_WHISPER_STATE_KEY] = state

    state["ticks"] += 1
    if isinstance(current_tick, int):
        state["last_tick"] = current_tick
    ticks = state["ticks"]

    max_ticks = _ENTRY_INITIATE_MAX_TICKS if use_button_b else _INITIATE_MAX_TICKS
    if ticks > max_ticks:
        state["failed"] = True
        return 0

    if use_button_b:
        if (ticks - 1) % _ENTRY_RETRY_INTERVAL_TICKS == 0:
            if isinstance(current_tick, int):
                last_button_tick = belief_state.extra.get(
                    _INITIATE_LAST_ENTRY_BUTTON_TICK_KEY
                )
                if (
                    isinstance(last_button_tick, int)
                    and 0 <= current_tick - last_button_tick < _ENTRY_RETRY_INTERVAL_TICKS
                ):
                    state["ticks"] = 0
                    return 0
                belief_state.extra[_INITIATE_LAST_ENTRY_BUTTON_TICK_KEY] = current_tick
            return BUTTON_B
        return 0

    if (ticks - 1) % _INITIATE_RETRY_INTERVAL_TICKS == 0:
        return BUTTON_A
    return 0


@dataclass(frozen=True)
class MoveAndInitiateWhisperTask(Task):
    """Move toward a point while retrying the whisper-entry button.

    This is primarily for entry requests: the server accepts B only on a
    rising edge and only while inside the 20px bubble of an open whisper.
    Pressing B again while an entry request is pending cancels that request, so
    retries are deliberately much slower than ordinary A-button creation.
    """

    x: int
    y: int
    target_index: int | None = None
    use_button_b: bool = True
    button_radius: float | None = None

    valid_views: ClassVar[frozenset[View]] = OPEN_VIEW_VIEWS

    def select_action(self, belief_state, action_memory) -> ActCommand:
        goal = (self.x, self.y)
        _reset_path_if_goal_changed(action_memory, goal)
        position = _position2d(getattr(belief_state, "position", None))
        entry_radius = (
            float(self.button_radius)
            if self.button_radius is not None
            else ENTRY_DISTANCE_PX
        )
        close_to_goal = (
            position is not None and _distance(position, goal) <= entry_radius
        )
        movement = _entry_approach_command(
            belief_state,
            action_memory,
            goal,
            use_button_b=self.use_button_b,
            button_radius=entry_radius,
        )
        button = 0
        if close_to_goal:
            button = _initiate_retry_button(
                belief_state,
                self.target_index,
                self.use_button_b,
                entry_close_key=True,
            )
        if button:
            _log_entry_button_pulse(
                belief_state,
                task_type=type(self).__name__,
                target_index=self.target_index,
                goal=goal,
                position=position,
                close_to_goal=close_to_goal,
                use_button_b=self.use_button_b,
                button_radius=entry_radius,
            )
            return ActCommand(buttons=button)
        return movement


@dataclass(frozen=True)
class RendezvousEntrySweepTask(Task):
    """Sweep a rendezvous area while retrying the whisper-entry button."""

    x: int
    y: int
    target_index: int | None = None
    use_button_b: bool = True
    radius: int = _RENDEZVOUS_SWEEP_RADIUS
    button_radius: float | None = None

    valid_views: ClassVar[frozenset[View]] = OPEN_VIEW_VIEWS

    def select_action(self, belief_state, action_memory) -> ActCommand:
        goal = (self.x, self.y)
        _reset_rendezvous_sweep_if_goal_changed(action_memory, goal, self.radius)
        position = _position2d(getattr(belief_state, "position", None))
        entry_radius = (
            float(self.button_radius)
            if self.button_radius is not None
            else ENTRY_DISTANCE_PX
        )
        close_to_goal = (
            position is not None and _distance(position, goal) <= entry_radius
        )
        movement = _rendezvous_sweep_command(
            belief_state,
            action_memory,
            goal,
            radius=self.radius,
            button_radius=entry_radius,
        )
        button = 0
        if close_to_goal:
            button = _initiate_retry_button(
                belief_state,
                self.target_index,
                self.use_button_b,
                entry_close_key=True,
            )
        if button:
            _log_entry_button_pulse(
                belief_state,
                task_type=type(self).__name__,
                target_index=self.target_index,
                goal=goal,
                position=position,
                close_to_goal=close_to_goal,
                use_button_b=self.use_button_b,
                button_radius=entry_radius,
            )
            return ActCommand(buttons=button)
        return movement


def _log_entry_button_pulse(
    belief_state,
    *,
    task_type: str,
    target_index: int | None,
    goal: tuple[int, int] | None,
    position: tuple[int, int] | None,
    close_to_goal: bool,
    use_button_b: bool,
    button_radius: float | None = None,
) -> None:
    if not use_button_b:
        return
    log_event(
        getattr(belief_state, "_logger", None),
        "entry_button_pulse",
        {
            "task_type": task_type,
            "target_index": target_index,
            "goal": list(goal) if goal is not None else None,
            "position": list(position) if position is not None else None,
            "close_to_goal": bool(close_to_goal),
            "button_radius": button_radius,
        },
        LogLevel.DECISIONS,
    )


def _reset_rendezvous_sweep_if_goal_changed(
    action_memory,
    goal: tuple[int, int],
    radius: int,
) -> None:
    previous = getattr(action_memory, _RENDEZVOUS_SWEEP_GOAL_KEY, None)
    current = (goal, radius)
    if previous == current:
        return
    setattr(action_memory, _RENDEZVOUS_SWEEP_GOAL_KEY, current)
    setattr(action_memory, _RENDEZVOUS_SWEEP_TICKS_KEY, 0)
    setattr(action_memory, _DIRECT_APPROACH_TICKS_KEY, 0)
    action_memory.path = None
    action_memory.path_index = 0


def _rendezvous_sweep_command(
    belief_state,
    action_memory,
    goal: tuple[int, int],
    *,
    radius: int,
    button_radius: float | None = None,
) -> ActCommand:
    position = _position2d(getattr(belief_state, "position", None))
    if position is None:
        return ActCommand()

    entry_radius = (
        float(button_radius) if button_radius is not None else ENTRY_DISTANCE_PX
    )
    if _distance(position, goal) > entry_radius:
        movement = _movement_command_to(
            belief_state,
            action_memory,
            goal,
            goal_radius=entry_radius,
        )
        if movement.buttons:
            return movement
        return ActCommand(buttons=_direct_approach_mask(action_memory, position, goal))

    target = _rendezvous_sweep_target(action_memory, goal, radius, belief_state)
    return ActCommand(buttons=_direction_mask(position, target))


def _rendezvous_sweep_target(
    action_memory,
    goal: tuple[int, int],
    radius: int,
    belief_state,
) -> tuple[int, int]:
    ticks = getattr(action_memory, _RENDEZVOUS_SWEEP_TICKS_KEY, 0) + 1
    setattr(action_memory, _RENDEZVOUS_SWEEP_TICKS_KEY, ticks)
    leg = (ticks // _RENDEZVOUS_SWEEP_LEG_TICKS) % 9
    offsets = (
        (0, 0),
        (radius, 0),
        (radius, radius),
        (0, radius),
        (-radius, radius),
        (-radius, 0),
        (-radius, -radius),
        (0, -radius),
        (radius, -radius),
    )
    dx, dy = offsets[leg]
    return _clamp_to_room((goal[0] + dx, goal[1] + dy), belief_state)


def _clamp_to_room(point: tuple[int, int], belief_state) -> tuple[int, int]:
    room_size = getattr(belief_state, "room_size", None)
    if room_size is None or len(room_size) < 2:
        return point
    width, height = int(room_size[0]), int(room_size[1])
    if width <= 0 or height <= 0:
        return point
    return max(0, min(point[0], width - 1)), max(0, min(point[1], height - 1))


def _reset_path_if_goal_changed(action_memory, goal: tuple[int, int]) -> None:
    previous_goal = getattr(action_memory, _ENTRY_SWEEP_GOAL_KEY, None)
    if previous_goal is not None and _distance(previous_goal, goal) <= _GOAL_REPATH_DISTANCE:
        return
    setattr(action_memory, _ENTRY_SWEEP_GOAL_KEY, goal)
    setattr(action_memory, _ENTRY_SWEEP_TICKS_KEY, 0)
    setattr(action_memory, _DIRECT_APPROACH_TICKS_KEY, 0)
    action_memory.path = None
    action_memory.path_index = 0


def _entry_approach_command(
    belief_state,
    action_memory,
    goal: tuple[int, int],
    *,
    use_button_b: bool,
    button_radius: float | None = None,
) -> ActCommand:
    position = _position2d(getattr(belief_state, "position", None))
    if position is None:
        return ActCommand()

    entry_radius = (
        float(button_radius) if button_radius is not None else ENTRY_DISTANCE_PX
    )
    if use_button_b and _distance(position, goal) <= entry_radius:
        sweep_target = _entry_sweep_target(action_memory, goal)
        return ActCommand(buttons=_direction_mask(position, sweep_target))

    movement = _movement_command_to(
        belief_state,
        action_memory,
        goal,
        goal_radius=entry_radius if use_button_b else ENTRY_DISTANCE_PX,
    )
    if movement.buttons:
        return movement
    if _distance(position, goal) > entry_radius:
        return ActCommand(buttons=_direct_approach_mask(action_memory, position, goal))
    return movement


def _entry_sweep_target(action_memory, goal: tuple[int, int]) -> tuple[int, int]:
    ticks = getattr(action_memory, _ENTRY_SWEEP_TICKS_KEY, 0) + 1
    setattr(action_memory, _ENTRY_SWEEP_TICKS_KEY, ticks)
    leg = (ticks // _ENTRY_SWEEP_LEG_TICKS) % 4
    offsets = (
        (_ENTRY_SWEEP_RADIUS, 0),
        (0, _ENTRY_SWEEP_RADIUS),
        (-_ENTRY_SWEEP_RADIUS, 0),
        (0, -_ENTRY_SWEEP_RADIUS),
    )
    dx, dy = offsets[leg]
    return goal[0] + dx, goal[1] + dy


def _direction_mask(position: tuple[int, int], target: tuple[int, int]) -> int:
    dx = target[0] - position[0]
    dy = target[1] - position[1]
    mask = 0
    if dx > 1:
        mask |= BUTTON_RIGHT
    elif dx < -1:
        mask |= BUTTON_LEFT
    if dy > 1:
        mask |= BUTTON_DOWN
    elif dy < -1:
        mask |= BUTTON_UP
    return mask


def _direct_approach_mask(
    action_memory,
    position: tuple[int, int],
    target: tuple[int, int],
) -> int:
    """Probe one axis at a time when pathfinding cannot route to the target."""
    dx = target[0] - position[0]
    dy = target[1] - position[1]
    horizontal = 0
    vertical = 0
    if dx > 1:
        horizontal = BUTTON_RIGHT
    elif dx < -1:
        horizontal = BUTTON_LEFT
    if dy > 1:
        vertical = BUTTON_DOWN
    elif dy < -1:
        vertical = BUTTON_UP

    if horizontal and vertical:
        ticks = getattr(action_memory, _DIRECT_APPROACH_TICKS_KEY, 0)
        setattr(action_memory, _DIRECT_APPROACH_TICKS_KEY, ticks + 1)
        return horizontal if (ticks // 6) % 2 == 0 else vertical
    return horizontal or vertical


@dataclass(frozen=True)
class RequestEntryTask(Task):
    """Approach a player's whisper and request entry when close enough."""

    player_index: int

    valid_views: ClassVar[frozenset[View]] = OPEN_VIEW_VIEWS

    def select_action(self, belief_state, action_memory) -> ActCommand:
        player = getattr(belief_state, "players", {}).get(self.player_index)
        target_position = _position2d(getattr(player, "position", None))
        self_position = _position2d(getattr(belief_state, "position", None))
        if player is None or target_position is None or self_position is None:
            return ActCommand()

        if _distance(self_position, target_position) <= ENTRY_DISTANCE_PX:
            last_seen = getattr(player, "last_seen_in_whisper", None)
            if (
                last_seen is not None
                and getattr(belief_state, "tick", 0) - last_seen <= RECENT_WHISPER_TICKS
            ):
                return ActCommand(buttons=action_memory.step_button_press(BUTTON_B))
            return ActCommand()

        return _movement_command_to(
            belief_state,
            action_memory,
            target_position,
            goal_radius=ENTRY_DISTANCE_PX,
        )


@dataclass(frozen=True)
class CancelEntryTask(Task):
    """Cancel a pending whisper-entry request."""

    valid_views: ClassVar[frozenset[View]] = frozenset({View.WAITING_ENTRY})

    def select_action(self, belief_state, action_memory) -> ActCommand:
        return ActCommand(buttons=action_memory.step_button_press(BUTTON_B))


@dataclass(frozen=True)
class ExitWhisperTask(Task):
    """Exit the current whisper using the Select shortcut."""

    valid_views: ClassVar[frozenset[View]] = frozenset({View.WHISPER})

    def select_action(self, belief_state, action_memory) -> ActCommand:
        return ActCommand(buttons=action_memory.step_button_press(BUTTON_SELECT))


@dataclass(frozen=True)
class GrantEntryTask(Task):
    """Grant a pending entry request via the whisper menu."""

    valid_views: ClassVar[frozenset[View]] = frozenset({View.WHISPER})

    def select_action(self, belief_state, action_memory) -> ActCommand:
        return MenuNavigator(
            (
                ("category", "LEADER"),
                ("item", "GRANT"),
                ("confirm",),
            )
        ).next_command(belief_state, action_memory)


__all__ = [
    "CreateWhisperTask",
    "InitiateWhisperTask",
    "MoveAndInitiateWhisperTask",
    "RendezvousEntrySweepTask",
    "RequestEntryTask",
    "CancelEntryTask",
    "ExitWhisperTask",
    "GrantEntryTask",
]
