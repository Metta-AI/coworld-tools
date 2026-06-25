"""A* pathfinding over Orpheus occupancy grids."""

from __future__ import annotations

import heapq
import math

from orpheus.occupancy_grid import CellState, OccupancyGrid

GridCoord = tuple[int, int]

_NEIGHBORS = (
    (-1, 0, 1.0),
    (1, 0, 1.0),
    (0, -1, 1.0),
    (0, 1, 1.0),
    (-1, -1, math.sqrt(2.0)),
    (1, -1, math.sqrt(2.0)),
    (-1, 1, math.sqrt(2.0)),
    (1, 1, math.sqrt(2.0)),
)


def a_star(
    grid: OccupancyGrid,
    start: tuple[int, int],
    goal: tuple[int, int],
    expansion: int = 2,
) -> list[tuple[int, int]] | None:
    """Find a path from start to goal world coordinates.

    Returned waypoints are world-pixel centers of the traversed grid cells,
    including the start and goal cells. UNKNOWN cells are traversable; WALL
    cells and cells inside the configured expansion radius are impassable.
    """
    if expansion < 0:
        raise ValueError("expansion must be non-negative")

    start_grid = grid.world_to_grid(*start)
    goal_grid = grid.world_to_grid(*goal)

    if not _is_passable(grid, *start_grid, expansion):
        return None
    if not _is_passable(grid, *goal_grid, expansion):
        return None

    open_set: list[tuple[float, int, int, int]] = []
    counter = 0
    heapq.heappush(
        open_set,
        (_heuristic(start_grid, goal_grid), counter, *start_grid),
    )

    came_from: dict[GridCoord, GridCoord] = {}
    g_score: dict[GridCoord, float] = {start_grid: 0.0}
    closed: set[GridCoord] = set()

    while open_set:
        _, _, current_x, current_y = heapq.heappop(open_set)
        current = (current_x, current_y)
        if current in closed:
            continue
        if current == goal_grid:
            return reconstruct_path(came_from, current, grid)

        closed.add(current)

        for dx, dy, move_cost in _NEIGHBORS:
            neighbor = (current_x + dx, current_y + dy)
            if neighbor in closed:
                continue
            if not _is_passable(grid, neighbor[0], neighbor[1], expansion):
                continue

            tentative_g = g_score[current] + move_cost
            if tentative_g >= g_score.get(neighbor, math.inf):
                continue

            came_from[neighbor] = current
            g_score[neighbor] = tentative_g
            counter += 1
            f_score = tentative_g + _heuristic(neighbor, goal_grid)
            heapq.heappush(open_set, (f_score, counter, *neighbor))

    return None


def reconstruct_path(
    came_from: dict[GridCoord, GridCoord],
    current_grid: GridCoord,
    grid: OccupancyGrid,
) -> list[tuple[int, int]]:
    """Reconstruct a path as center-of-cell world coordinates."""
    path_grids = [current_grid]
    while current_grid in came_from:
        current_grid = came_from[current_grid]
        path_grids.append(current_grid)
    path_grids.reverse()

    return [_grid_center_to_world(grid, gx, gy) for gx, gy in path_grids]


def _grid_center_to_world(
    grid: OccupancyGrid,
    gx: int,
    gy: int,
) -> tuple[int, int]:
    world_x, world_y = grid.grid_to_world(gx, gy)
    center_offset = grid.resolution // 2
    return world_x + center_offset, world_y + center_offset


def _is_passable(
    grid: OccupancyGrid,
    gx: int,
    gy: int,
    expansion: int,
) -> bool:
    for dy in range(-expansion, expansion + 1):
        for dx in range(-expansion, expansion + 1):
            check_x = gx + dx
            check_y = gy + dy
            if not grid.is_inside(check_x, check_y):
                return False
            if grid.cells[check_y, check_x] == CellState.WALL:
                return False
    return True


def _heuristic(a: GridCoord, b: GridCoord) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


__all__ = ["a_star", "reconstruct_path"]
