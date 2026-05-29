"""Navigation graph + route planning over the walkability grid (design §6, §9).

The walkability mask (a bool grid, decoded once from the stream's ``walkability
map`` sprite) is coarsened into a navigation grid of ``cell_size``-pixel cells —
a cell is walkable iff every underlying pixel is walkable — and A* plans a route
of world-coordinate waypoints over it. Coarsening keeps A* fast on the full
1235×659 map; the grid is static for an episode, so it is built once and cached
(see :func:`build_nav_grid` callers in ``types.update_belief``).

The action layer (:mod:`.action`) follows the returned waypoints; this module
never touches transport.
"""

from __future__ import annotations

import heapq
import math
from dataclasses import dataclass

import numpy as np

DEFAULT_CELL_SIZE = 8

# 8-connected moves. Diagonals require both adjacent orthogonals walkable (no
# corner cutting through walls).
_ORTHO = [(-1, 0), (1, 0), (0, -1), (0, 1)]
_DIAG = [(-1, -1), (-1, 1), (1, -1), (1, 1)]


@dataclass
class NavGrid:
    """A coarse navigation grid over the walkability mask."""

    walkable: np.ndarray  # bool, shape (rows, cols); True == navigable cell
    cell_size: int
    map_width: int
    map_height: int

    @property
    def rows(self) -> int:
        return int(self.walkable.shape[0])

    @property
    def cols(self) -> int:
        return int(self.walkable.shape[1])

    def world_to_cell(self, x: int, y: int) -> tuple[int, int]:
        col = min(max(x // self.cell_size, 0), self.cols - 1)
        row = min(max(y // self.cell_size, 0), self.rows - 1)
        return row, col

    def cell_to_world(self, row: int, col: int) -> tuple[int, int]:
        """Return the world center of a cell."""

        half = self.cell_size // 2
        return col * self.cell_size + half, row * self.cell_size + half

    def is_walkable_cell(self, row: int, col: int) -> bool:
        return 0 <= row < self.rows and 0 <= col < self.cols and bool(self.walkable[row, col])

    def nearest_walkable_cell(self, row: int, col: int, *, max_radius: int = 8) -> tuple[int, int] | None:
        """Find the closest walkable cell to ``(row, col)`` within ``max_radius``."""

        if self.is_walkable_cell(row, col):
            return row, col
        for radius in range(1, max_radius + 1):
            best: tuple[int, int] | None = None
            for dr in range(-radius, radius + 1):
                for dc in range(-radius, radius + 1):
                    if max(abs(dr), abs(dc)) != radius:
                        continue
                    if self.is_walkable_cell(row + dr, col + dc):
                        best = (row + dr, col + dc)
                        break
                if best is not None:
                    break
            if best is not None:
                return best
        return None


def build_nav_grid(
    walkability: np.ndarray,
    *,
    cell_size: int = DEFAULT_CELL_SIZE,
    map_width: int | None = None,
    map_height: int | None = None,
) -> NavGrid:
    """Coarsen a pixel walkability mask into a :class:`NavGrid`.

    A coarse cell is walkable iff every pixel it covers is walkable (partial edge
    cells beyond a whole multiple of ``cell_size`` are dropped).
    """

    height, width = walkability.shape
    rows = height // cell_size
    cols = width // cell_size
    trimmed = walkability[: rows * cell_size, : cols * cell_size]
    blocks = trimmed.reshape(rows, cell_size, cols, cell_size)
    walkable = blocks.all(axis=(1, 3))
    return NavGrid(
        walkable=walkable,
        cell_size=cell_size,
        map_width=map_width if map_width is not None else width,
        map_height=map_height if map_height is not None else height,
    )


def plan_route(
    grid: NavGrid,
    start_world: tuple[int, int],
    goal_world: tuple[int, int],
) -> list[tuple[int, int]]:
    """A* a route of world waypoints from start to goal, or ``[]`` if unreachable.

    Start/goal cells are snapped to the nearest walkable cell. The final waypoint
    is the exact ``goal_world`` so the action layer drives onto the real target.
    """

    start = grid.nearest_walkable_cell(*grid.world_to_cell(*start_world))
    goal = grid.nearest_walkable_cell(*grid.world_to_cell(*goal_world))
    if start is None or goal is None:
        return []
    if start == goal:
        return [goal_world]

    came_from: dict[tuple[int, int], tuple[int, int]] = {}
    g_score = {start: 0.0}
    open_heap: list[tuple[float, tuple[int, int]]] = [(0.0, start)]
    closed: set[tuple[int, int]] = set()

    while open_heap:
        _, current = heapq.heappop(open_heap)
        if current == goal:
            return _reconstruct(grid, came_from, current, goal_world)
        if current in closed:
            continue
        closed.add(current)
        for neighbor, step_cost in _neighbors(grid, current):
            if neighbor in closed:
                continue
            tentative = g_score[current] + step_cost
            if tentative < g_score.get(neighbor, math.inf):
                came_from[neighbor] = current
                g_score[neighbor] = tentative
                f = tentative + _heuristic(neighbor, goal)
                heapq.heappush(open_heap, (f, neighbor))
    return []


def _neighbors(grid: NavGrid, cell: tuple[int, int]):
    row, col = cell
    for dr, dc in _ORTHO:
        nr, nc = row + dr, col + dc
        if grid.is_walkable_cell(nr, nc):
            yield (nr, nc), 1.0
    for dr, dc in _DIAG:
        nr, nc = row + dr, col + dc
        # No corner cutting: both shared orthogonal cells must be walkable.
        if (
            grid.is_walkable_cell(nr, nc)
            and grid.is_walkable_cell(row + dr, col)
            and grid.is_walkable_cell(row, col + dc)
        ):
            yield (nr, nc), math.sqrt(2.0)


def _heuristic(cell: tuple[int, int], goal: tuple[int, int]) -> float:
    dr = abs(cell[0] - goal[0])
    dc = abs(cell[1] - goal[1])
    # Octile distance: admissible for 8-connected unit/√2 moves.
    return (dr + dc) + (math.sqrt(2.0) - 2.0) * min(dr, dc)


def _reconstruct(
    grid: NavGrid,
    came_from: dict[tuple[int, int], tuple[int, int]],
    current: tuple[int, int],
    goal_world: tuple[int, int],
) -> list[tuple[int, int]]:
    cells = [current]
    while current in came_from:
        current = came_from[current]
        cells.append(current)
    cells.reverse()
    # Cell centers for every step except the last, then the exact goal point.
    waypoints = [grid.cell_to_world(row, col) for row, col in cells[:-1]]
    waypoints.append(goal_world)
    return waypoints
