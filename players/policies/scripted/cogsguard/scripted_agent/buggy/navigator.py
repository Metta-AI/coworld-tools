"""A* navigator for Planky policy."""

from __future__ import annotations

import heapq
import random
from typing import TYPE_CHECKING, Optional

from mettagrid.simulator import Action

if TYPE_CHECKING:
    from .entity_map import EntityMap

MOVE_DELTAS: dict[str, tuple[int, int]] = {
    "north": (-1, 0),
    "south": (1, 0),
    "east": (0, 1),
    "west": (0, -1),
}

DIRECTIONS = ["north", "south", "east", "west"]


class Navigator:
    """A* pathfinding over the entity map."""

    def __init__(self) -> None:
        self._cached_path: Optional[list[tuple[int, int]]] = None
        self._cached_target: Optional[tuple[int, int]] = None
        self._cached_reach_adjacent: bool = False
        self._position_history: list[tuple[int, int]] = []

    def get_action(
        self,
        current: tuple[int, int],
        target: tuple[int, int],
        map: EntityMap,
        reach_adjacent: bool = False,
    ) -> Action:
        """Navigate from current to target using A*.

        Args:
            current: Current position
            target: Target position
            map: Entity map for pathfinding
            reach_adjacent: If True, stop adjacent to target
        """
        # Track position history for stuck detection
        self._position_history.append(current)
        if len(self._position_history) > 30:
            self._position_history.pop(0)

        # Stuck detection
        if self._is_stuck():
            action = self._break_stuck(current, map)
            if action:
                return action

        if current == target and not reach_adjacent:
            return Action(name="noop")

        # Check if adjacent to target (for reach_adjacent mode)
        if reach_adjacent and _manhattan(current, target) == 1:
            return Action(name="noop")

        # Get or compute path
        path = self._get_path(current, target, map, reach_adjacent)

        if not path:
            # No path found — try exploring toward target
            return self._move_toward_greedy(current, target, map)

        next_pos = path[0]

        # Check if next position is blocked by agent
        if map.has_agent(next_pos):
            sidestep = self._find_sidestep(current, next_pos, target, map)
            if sidestep:
                self._cached_path = None
                return _move_action(current, sidestep)
            return Action(name="noop")  # Wait for agent to move

        # Advance path
        self._cached_path = path[1:] if len(path) > 1 else None
        return _move_action(current, next_pos)

    def explore(
        self,
        current: tuple[int, int],
        map: EntityMap,
        direction_bias: Optional[str] = None,
    ) -> Action:
        """Navigate toward unexplored frontier cells."""
        self._position_history.append(current)
        if len(self._position_history) > 30:
            self._position_history.pop(0)

        if self._is_stuck():
            action = self._break_stuck(current, map)
            if action:
                return action

        frontier = self._find_frontier(current, map, direction_bias)
        if frontier:
            return self.get_action(current, frontier, map)

        # No frontier — random walk
        return self._random_move(current, map)

    def _get_path(
        self,
        start: tuple[int, int],
        target: tuple[int, int],
        map: EntityMap,
        reach_adjacent: bool,
    ) -> Optional[list[tuple[int, int]]]:
        """Get cached path or compute new one."""
        if self._cached_path and self._cached_target == target and self._cached_reach_adjacent == reach_adjacent:
            # Verify path is still valid
            for pos in self._cached_path:
                if map.has_agent(pos):
                    break
            else:
                return self._cached_path

        # Compute new path
        goal_cells = self._compute_goals(target, map, reach_adjacent)
        if not goal_cells:
            return None

        # Try known terrain first
        path = self._astar(start, goal_cells, map, allow_unknown=False)
        if not path:
            # Allow unknown cells
            path = self._astar(start, goal_cells, map, allow_unknown=True)

        self._cached_path = path.copy() if path else None
        self._cached_target = target
        self._cached_reach_adjacent = reach_adjacent
        return path

    def _compute_goals(
        self,
        target: tuple[int, int],
        map: EntityMap,
        reach_adjacent: bool,
    ) -> list[tuple[int, int]]:
        if not reach_adjacent:
            return [target]
        goals = []
        for dr, dc in MOVE_DELTAS.values():
            nr, nc = target[0] + dr, target[1] + dc
            pos = (nr, nc)
            if self._is_traversable(pos, map, allow_unknown=True):
                goals.append(pos)
        return goals

    def _astar(
        self,
        start: tuple[int, int],
        goals: list[tuple[int, int]],
        map: EntityMap,
        allow_unknown: bool,
    ) -> list[tuple[int, int]]:
        """A* pathfinding with iteration limit to prevent hanging."""
        goal_set = set(goals)
        if not goals:
            return []

        def h(pos: tuple[int, int]) -> int:
            return min(_manhattan(pos, g) for g in goals)

        tie = 0
        iterations = 0
        max_iterations = 5000  # Prevent infinite search on large unknown maps

        open_set: list[tuple[int, int, tuple[int, int]]] = [(h(start), tie, start)]
        came_from: dict[tuple[int, int], Optional[tuple[int, int]]] = {start: None}
        g_score: dict[tuple[int, int], int] = {start: 0}

        while open_set and iterations < max_iterations:
            iterations += 1
            _, _, current = heapq.heappop(open_set)

            if current in goal_set:
                return self._reconstruct(came_from, current)

            current_g = g_score.get(current, float("inf"))
            if isinstance(current_g, float):
                continue

            for dr, dc in MOVE_DELTAS.values():
                neighbor = (current[0] + dr, current[1] + dc)
                is_goal = neighbor in goal_set
                if not is_goal and not self._is_traversable(neighbor, map, allow_unknown):
                    continue

                tentative_g = current_g + 1
                if tentative_g < g_score.get(neighbor, float("inf")):
                    came_from[neighbor] = current
                    g_score[neighbor] = tentative_g
                    f = tentative_g + h(neighbor)
                    tie += 1
                    heapq.heappush(open_set, (f, tie, neighbor))

        return []

    def _reconstruct(
        self,
        came_from: dict[tuple[int, int], Optional[tuple[int, int]]],
        current: tuple[int, int],
    ) -> list[tuple[int, int]]:
        path = []
        while came_from[current] is not None:
            path.append(current)
            prev = came_from[current]
            assert prev is not None
            current = prev
        path.reverse()
        return path

    def _is_traversable(
        self,
        pos: tuple[int, int],
        map: EntityMap,
        allow_unknown: bool = False,
    ) -> bool:
        """Check if a cell can be walked through."""
        if map.is_wall(pos) or map.is_structure(pos):
            return False
        if map.has_agent(pos):
            return False
        if pos in map.explored:
            return pos not in map.entities or map.entities[pos].type == "agent"
        # Unknown cell
        return allow_unknown

    def _find_frontier(
        self,
        from_pos: tuple[int, int],
        map: EntityMap,
        direction_bias: Optional[str] = None,
    ) -> Optional[tuple[int, int]]:
        """BFS to find nearest unexplored cell adjacent to explored free cell."""
        from collections import deque  # noqa: PLC0415

        if direction_bias == "north":
            deltas = [(-1, 0), (0, -1), (0, 1), (1, 0)]
        elif direction_bias == "south":
            deltas = [(1, 0), (0, -1), (0, 1), (-1, 0)]
        elif direction_bias == "east":
            deltas = [(0, 1), (-1, 0), (1, 0), (0, -1)]
        elif direction_bias == "west":
            deltas = [(0, -1), (-1, 0), (1, 0), (0, 1)]
        else:
            deltas = [(-1, 0), (1, 0), (0, -1), (0, 1)]

        visited: set[tuple[int, int]] = {from_pos}
        queue: deque[tuple[int, int, int]] = deque([(from_pos[0], from_pos[1], 0)])

        while queue:
            r, c, dist = queue.popleft()
            if dist > 50:
                continue

            for dr, dc in deltas:
                nr, nc = r + dr, c + dc
                pos = (nr, nc)
                if pos in visited:
                    continue
                visited.add(pos)

                if pos not in map.explored:
                    # Check if any neighbor is explored and free
                    for dr2, dc2 in deltas:
                        adj = (nr + dr2, nc + dc2)
                        if adj in map.explored and map.is_free(adj):
                            return pos
                    continue

                if map.is_free(pos):
                    queue.append((nr, nc, dist + 1))

        return None

    def _find_sidestep(
        self,
        current: tuple[int, int],
        blocked: tuple[int, int],
        target: tuple[int, int],
        map: EntityMap,
    ) -> Optional[tuple[int, int]]:
        """Find sidestep around blocking agent."""
        current_dist = _manhattan(current, target)
        candidates = []
        for d in DIRECTIONS:
            dr, dc = MOVE_DELTAS[d]
            pos = (current[0] + dr, current[1] + dc)
            if pos == blocked:
                continue
            if not self._is_traversable(pos, map, allow_unknown=True):
                continue
            new_dist = _manhattan(pos, target)
            score = new_dist - current_dist
            candidates.append((score, pos))

        if not candidates:
            return None
        candidates.sort()
        if candidates[0][0] <= 2:
            return candidates[0][1]
        return None

    def _is_stuck(self) -> bool:
        history = self._position_history
        if len(history) < 6:
            return False
        recent = history[-6:]
        if len(set(recent)) <= 2:
            return True
        if len(history) >= 20:
            current = history[-1]
            earlier = history[:-10]
            if earlier.count(current) >= 2:
                return True
        return False

    def _break_stuck(self, current: tuple[int, int], map: EntityMap) -> Optional[Action]:
        self._cached_path = None
        self._cached_target = None
        self._position_history.clear()
        return self._random_move(current, map)

    def _random_move(self, current: tuple[int, int], map: EntityMap) -> Action:
        dirs = list(DIRECTIONS)
        random.shuffle(dirs)
        for d in dirs:
            dr, dc = MOVE_DELTAS[d]
            pos = (current[0] + dr, current[1] + dc)
            if pos in map.explored and not map.is_wall(pos) and not map.is_structure(pos):
                return Action(name=f"move_{d}")
        # Try unknown cells
        for d in dirs:
            dr, dc = MOVE_DELTAS[d]
            pos = (current[0] + dr, current[1] + dc)
            if not map.is_wall(pos):
                return Action(name=f"move_{d}")
        return Action(name="noop")

    def _move_toward_greedy(self, current: tuple[int, int], target: tuple[int, int], map: EntityMap) -> Action:
        """Move greedily toward target without pathfinding."""
        dr = target[0] - current[0]
        dc = target[1] - current[1]

        # Try primary direction
        if abs(dr) >= abs(dc):
            primary = "south" if dr > 0 else "north"
            secondary = "east" if dc > 0 else "west"
        else:
            primary = "east" if dc > 0 else "west"
            secondary = "south" if dr > 0 else "north"

        for d in [primary, secondary]:
            ddr, ddc = MOVE_DELTAS[d]
            pos = (current[0] + ddr, current[1] + ddc)
            if not map.is_wall(pos) and not map.is_structure(pos) and not map.has_agent(pos):
                return Action(name=f"move_{d}")

        return self._random_move(current, map)


def _manhattan(a: tuple[int, int], b: tuple[int, int]) -> int:
    return abs(a[0] - b[0]) + abs(a[1] - b[1])


def _move_action(current: tuple[int, int], target: tuple[int, int]) -> Action:
    """Return move action from current to adjacent target."""
    dr = target[0] - current[0]
    dc = target[1] - current[1]
    if dr == -1 and dc == 0:
        return Action(name="move_north")
    if dr == 1 and dc == 0:
        return Action(name="move_south")
    if dr == 0 and dc == 1:
        return Action(name="move_east")
    if dr == 0 and dc == -1:
        return Action(name="move_west")
    return Action(name="noop")
