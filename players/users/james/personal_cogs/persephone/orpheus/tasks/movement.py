"""Spatial movement tasks for Orpheus."""

from __future__ import annotations

import math
import random
from collections import deque
from dataclasses import dataclass
from typing import ClassVar

from orpheus import pathfinding
from orpheus.occupancy_grid import CellState
from orpheus.task import ActCommand, Task
from orpheus.types import (
    BUTTON_DOWN,
    BUTTON_LEFT,
    BUTTON_RIGHT,
    BUTTON_UP,
    View,
)

OVERWORLD_VIEWS: frozenset[View] = frozenset(
    {
        View.PLAYING,
        View.HOSTAGE_SELECT,
        View.LEADER_SUMMIT,
        View.WAITING_ENTRY,
    }
)

GOAL_RADIUS_PX = 3.0
STUCK_REPATH_TICKS = 10
DIRECT_RECOVERY_TICKS = 12
WANDER_RANDOM_ATTEMPTS = 20
WANDER_RECENT_CELL_LIMIT = 64
_DIRECT_RECOVERY_TICKS_KEY = "movement_direct_recovery_ticks"
_DIRECT_APPROACH_TICKS_KEY = "movement_direct_approach_ticks"


@dataclass(frozen=True)
class MoveToTask(Task):
    """Move toward a fixed world coordinate using A* waypoints."""

    x: int
    y: int

    valid_views: ClassVar[frozenset[View]] = OVERWORLD_VIEWS

    def select_action(self, belief_state, action_memory) -> ActCommand:
        return _movement_command_to(
            belief_state,
            action_memory,
            (self.x, self.y),
            goal_radius=GOAL_RADIUS_PX,
        )


@dataclass(frozen=True)
class FollowTask(Task):
    """Follow a player until within ``stop_distance`` pixels."""

    player_index: int
    stop_distance: int = 10

    valid_views: ClassVar[frozenset[View]] = OVERWORLD_VIEWS

    def select_action(self, belief_state, action_memory) -> ActCommand:
        self_position = _position2d(getattr(belief_state, "position", None))
        if self_position is None:
            return ActCommand()

        player = getattr(belief_state, "players", {}).get(self.player_index)
        target_position = _position2d(getattr(player, "position", None))
        if target_position is None:
            return ActCommand()

        if _distance(self_position, target_position) <= self.stop_distance:
            return ActCommand()

        previous_target = getattr(action_memory, "follow_target_position", None)
        if previous_target is None or _distance(previous_target, target_position) > 5:
            action_memory.path = None
            action_memory.path_index = 0
            action_memory.follow_target_position = target_position

        return _movement_command_to(
            belief_state,
            action_memory,
            target_position,
            goal_radius=float(self.stop_distance),
        )


@dataclass(frozen=True)
class WanderTask(Task):
    """Deterministically pick random room waypoints and walk toward them."""

    valid_views: ClassVar[frozenset[View]] = OVERWORLD_VIEWS

    def select_action(self, belief_state, action_memory) -> ActCommand:
        position = _position2d(getattr(belief_state, "position", None))
        room_size = getattr(belief_state, "room_size", None)
        if position is None or room_size is None:
            return ActCommand()

        _record_wander_visit(belief_state, action_memory, position)

        waypoint = getattr(action_memory, "wander_waypoint", None)
        if waypoint is None or _distance(position, waypoint) <= GOAL_RADIUS_PX:
            waypoint = _pick_wander_waypoint(belief_state, action_memory)
            if waypoint is None:
                return ActCommand()
            action_memory.wander_waypoint = waypoint
            action_memory.path = None
            action_memory.path_index = 0

        return _movement_command_to(
            belief_state,
            action_memory,
            waypoint,
            goal_radius=GOAL_RADIUS_PX,
        )


def _movement_command_to(
    belief_state,
    action_memory,
    goal: tuple[int, int],
    goal_radius: float,
) -> ActCommand:
    position = _position2d(getattr(belief_state, "position", None))
    if position is None:
        return ActCommand()

    if _distance(position, goal) <= goal_radius:
        return ActCommand()

    direct_recovery_ticks = getattr(action_memory, _DIRECT_RECOVERY_TICKS_KEY, 0)
    if direct_recovery_ticks > 0:
        setattr(action_memory, _DIRECT_RECOVERY_TICKS_KEY, direct_recovery_ticks - 1)
        return ActCommand(buttons=_direct_approach_mask(action_memory, position, goal))

    if _is_stuck(action_memory, position):
        action_memory.path = None
        action_memory.path_index = 0
        action_memory.stuck_ticks = 0
        action_memory.last_position = None
        setattr(action_memory, _DIRECT_RECOVERY_TICKS_KEY, DIRECT_RECOVERY_TICKS)
        return ActCommand(buttons=_direct_approach_mask(action_memory, position, goal))

    path = getattr(action_memory, "path", None)
    if path is None:
        path = _compute_path(belief_state, position, goal)
        if path is None and goal_radius > GOAL_RADIUS_PX:
            path = _compute_path_to_nearby_goal(
                belief_state,
                position,
                goal,
                goal_radius,
            )
        if path is None:
            # Unreachable under the current occupancy grid. Use a short direct
            # probe before trying A* again; the live geometry can leave the
            # coarse occupancy path stale around corners and moving blockers.
            action_memory.path = []
            action_memory.path_index = 0
            setattr(action_memory, _DIRECT_RECOVERY_TICKS_KEY, DIRECT_RECOVERY_TICKS)
            return ActCommand(buttons=_direct_approach_mask(action_memory, position, goal))
        action_memory.path = path
        action_memory.path_index = 0

    if not path:
        return ActCommand()

    waypoint = _current_waypoint(action_memory, position, goal)
    return ActCommand(buttons=_direction_mask(position, waypoint))


def _compute_path(
    belief_state,
    position: tuple[int, int],
    goal: tuple[int, int],
) -> list[tuple[int, int]] | None:
    grid = getattr(belief_state, "occupancy_grid", None)
    if grid is None:
        return [position, goal]
    return pathfinding.a_star(grid, position, goal)


def _compute_path_to_nearby_goal(
    belief_state,
    position: tuple[int, int],
    goal: tuple[int, int],
    goal_radius: float,
) -> list[tuple[int, int]] | None:
    grid = getattr(belief_state, "occupancy_grid", None)
    if grid is None:
        return None

    goal_gx, goal_gy = grid.world_to_grid(*goal)
    radius_cells = max(1, math.ceil(goal_radius / grid.resolution))
    center_offset = grid.resolution // 2
    candidates: list[tuple[float, float, tuple[int, int]]] = []

    for gy in range(goal_gy - radius_cells, goal_gy + radius_cells + 1):
        for gx in range(goal_gx - radius_cells, goal_gx + radius_cells + 1):
            if not grid.is_inside(gx, gy):
                continue
            world_x, world_y = grid.grid_to_world(gx, gy)
            candidate = (world_x + center_offset, world_y + center_offset)
            distance_to_goal = _distance(candidate, goal)
            if distance_to_goal > goal_radius:
                continue
            candidates.append(
                (
                    distance_to_goal,
                    _distance(position, candidate),
                    candidate,
                )
            )

    for _distance_to_goal, _distance_to_position, candidate in sorted(candidates):
        path = pathfinding.a_star(grid, position, candidate)
        if path is not None:
            return path

    return None


def _current_waypoint(
    action_memory,
    position: tuple[int, int],
    goal: tuple[int, int],
) -> tuple[int, int]:
    path = action_memory.path
    index = getattr(action_memory, "path_index", 0)
    while index < len(path) and _distance(position, path[index]) <= GOAL_RADIUS_PX:
        index += 1
    action_memory.path_index = index
    if index >= len(path):
        return goal
    return path[index]


def _direction_mask(
    position: tuple[int, int],
    target: tuple[int, int],
) -> int:
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


def _is_stuck(action_memory, position: tuple[int, int]) -> bool:
    last_position = getattr(action_memory, "last_position", None)
    if last_position == position:
        action_memory.stuck_ticks = getattr(action_memory, "stuck_ticks", 0) + 1
    else:
        action_memory.stuck_ticks = 0
        action_memory.last_position = position
    return action_memory.stuck_ticks > STUCK_REPATH_TICKS


def _pick_wander_waypoint(belief_state, action_memory) -> tuple[int, int] | None:
    if not hasattr(action_memory, "wander_rng"):
        action_memory.wander_rng = random.Random(0)

    room_w, room_h = belief_state.room_size
    grid = getattr(belief_state, "occupancy_grid", None)
    position = _position2d(getattr(belief_state, "position", None))
    if position is None:
        return None

    if grid is not None and _grid_has_exploration_data(grid):
        waypoint = _pick_reachable_grid_waypoint(
            grid,
            position,
            action_memory.wander_rng,
            CellState.UNKNOWN,
        )
        if waypoint is not None:
            return waypoint

        recent_cells = set(getattr(action_memory, "wander_recent_cells", ()))
        waypoint = _pick_reachable_grid_waypoint(
            grid,
            position,
            action_memory.wander_rng,
            CellState.FREE,
            excluded_cells=recent_cells,
        )
        if waypoint is not None:
            return waypoint

        waypoint = _pick_reachable_grid_waypoint(
            grid,
            position,
            action_memory.wander_rng,
            CellState.FREE,
        )
        if waypoint is not None:
            return waypoint

    for _ in range(WANDER_RANDOM_ATTEMPTS):
        x = action_memory.wander_rng.randint(4, max(4, room_w - 5))
        y = action_memory.wander_rng.randint(4, max(4, room_h - 5))
        if grid is None or pathfinding.a_star(grid, position, (x, y)) is not None:
            return (x, y)

    return None


def _record_wander_visit(belief_state, action_memory, position: tuple[int, int]) -> None:
    grid = getattr(belief_state, "occupancy_grid", None)
    if grid is None:
        return

    cell = grid.world_to_grid(*position)
    if not grid.is_inside(*cell):
        return

    recent_cells = getattr(action_memory, "wander_recent_cells", None)
    if recent_cells is None:
        recent_cells = deque(maxlen=WANDER_RECENT_CELL_LIMIT)
        action_memory.wander_recent_cells = recent_cells

    if not recent_cells or recent_cells[-1] != cell:
        recent_cells.append(cell)


def _grid_has_exploration_data(grid) -> bool:
    return bool((grid.cells == int(CellState.FREE)).any())


def _pick_reachable_grid_waypoint(
    grid,
    position: tuple[int, int],
    rng: random.Random,
    state: CellState,
    excluded_cells: set[tuple[int, int]] | None = None,
) -> tuple[int, int] | None:
    candidates = _grid_cells_with_state(grid, state, excluded_cells)
    rng.shuffle(candidates)

    for gx, gy in candidates:
        waypoint = grid.grid_to_world(gx, gy)
        if pathfinding.a_star(grid, position, waypoint) is not None:
            return waypoint

    return None


def _grid_cells_with_state(
    grid,
    state: CellState,
    excluded_cells: set[tuple[int, int]] | None,
) -> list[tuple[int, int]]:
    excluded_cells = excluded_cells or set()
    grid_ys, grid_xs = (grid.cells == int(state)).nonzero()
    return [
        (int(gx), int(gy))
        for gy, gx in zip(grid_ys, grid_xs)
        if (int(gx), int(gy)) not in excluded_cells
    ]


def _position2d(value) -> tuple[int, int] | None:
    if value is None:
        return None
    if len(value) < 2:
        return None
    return int(value[0]), int(value[1])


def _distance(
    a: tuple[int, int],
    b: tuple[int, int],
) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


__all__ = [
    "OVERWORLD_VIEWS",
    "MoveToTask",
    "FollowTask",
    "WanderTask",
]
