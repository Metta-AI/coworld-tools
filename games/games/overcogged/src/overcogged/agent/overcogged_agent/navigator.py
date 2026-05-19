"""Deterministic A* navigator for the Overcogged scripted policy."""

from __future__ import annotations

import heapq
from collections import deque

from mettagrid.simulator import Action

from .entity_map import EntityMap

MOVE_DELTAS: dict[str, tuple[int, int]] = {
    "north": (-1, 0),
    "east": (0, 1),
    "south": (1, 0),
    "west": (0, -1),
}
DIRECTIONS = list(MOVE_DELTAS)


class Navigator:
    def __init__(self, preferred_direction: str = "east") -> None:
        self._cached_path: list[tuple[int, int]] | None = None
        self._cached_target: tuple[int, int] | None = None
        self._history: list[tuple[int, int]] = []
        self._preferred_direction = preferred_direction if preferred_direction in MOVE_DELTAS else "east"

    def get_action(
        self,
        pos: tuple[int, int],
        target: tuple[int, int],
        entity_map: EntityMap,
        reach_adjacent: bool = False,
    ) -> Action:
        self._track(pos)
        if self._is_stuck():
            return self._break_stuck(pos, entity_map)

        if pos == target and not reach_adjacent:
            return Action(name="noop")
        if reach_adjacent and manhattan(pos, target) == 1:
            return Action(name="noop")

        path = self._get_path(pos, target, entity_map, reach_adjacent)
        if not path:
            return self._greedy(pos, target, entity_map)

        nxt = path[0]
        if entity_map.has_agent(nxt):
            side_step = self._sidestep(pos, nxt, target, entity_map)
            if side_step is not None:
                self._cached_path = None
                return move_action(pos, side_step)
            return Action(name="noop")

        self._cached_path = path[1:] or None
        return move_action(pos, nxt)

    def explore(self, pos: tuple[int, int], entity_map: EntityMap, bias: str | None = None) -> Action:
        self._track(pos)
        if self._is_stuck():
            return self._break_stuck(pos, entity_map)

        frontier = self._frontier(pos, entity_map, bias)
        if frontier:
            return self.get_action(pos, frontier, entity_map)
        return self._fallback_move(pos, entity_map, bias)

    def _ordered_directions(self, bias: str | None) -> list[str]:
        preferred = bias if bias in MOVE_DELTAS else self._preferred_direction
        return [preferred, *[direction for direction in DIRECTIONS if direction != preferred]]

    def _track(self, pos: tuple[int, int]) -> None:
        self._history.append(pos)
        if len(self._history) > 30:
            self._history.pop(0)

    def _is_stuck(self) -> bool:
        history = self._history
        if len(history) >= 6 and len(set(history[-6:])) <= 2:
            return True
        return len(history) >= 20 and history[:-10].count(history[-1]) >= 2

    def _break_stuck(self, pos: tuple[int, int], entity_map: EntityMap) -> Action:
        self._cached_path = None
        self._cached_target = None
        self._history.clear()
        return self._fallback_move(pos, entity_map, None)

    def _get_path(
        self,
        start: tuple[int, int],
        target: tuple[int, int],
        entity_map: EntityMap,
        reach_adjacent: bool,
    ) -> list[tuple[int, int]] | None:
        if self._cached_path and self._cached_target == target:
            return self._cached_path

        goals = self._goal_cells(target, entity_map, reach_adjacent)
        if not goals:
            return None

        path = self._astar(start, goals, entity_map, False) or self._astar(start, goals, entity_map, True)
        self._cached_path = list(path) if path else None
        self._cached_target = target
        return self._cached_path

    def _goal_cells(
        self,
        target: tuple[int, int],
        entity_map: EntityMap,
        reach_adjacent: bool,
    ) -> list[tuple[int, int]]:
        if not reach_adjacent:
            return [target]

        goals: list[tuple[int, int]] = []
        for dr, dc in MOVE_DELTAS.values():
            cell = (target[0] + dr, target[1] + dc)
            if entity_map.is_wall(cell) or entity_map.is_structure(cell) or entity_map.has_agent(cell):
                continue
            goals.append(cell)
        return goals

    def _astar(
        self,
        start: tuple[int, int],
        goals: list[tuple[int, int]],
        entity_map: EntityMap,
        allow_unknown: bool,
    ) -> list[tuple[int, int]]:
        goal_set = set(goals)

        def heuristic(pos: tuple[int, int]) -> int:
            return min(manhattan(pos, goal) for goal in goals)

        tie_breaker = 0
        heap: list[tuple[int, int, tuple[int, int]]] = [(heuristic(start), 0, start)]
        came_from: dict[tuple[int, int], tuple[int, int] | None] = {start: None}
        g_score: dict[tuple[int, int], int] = {start: 0}

        for _ in range(5000):
            if not heap:
                break

            _, _, current = heapq.heappop(heap)
            if current in goal_set:
                path: list[tuple[int, int]] = []
                cursor = current
                while came_from[cursor] is not None:
                    path.append(cursor)
                    parent = came_from[cursor]
                    assert parent is not None
                    cursor = parent
                path.reverse()
                return path

            current_g = g_score.get(current, 9999999)
            for direction in DIRECTIONS:
                dr, dc = MOVE_DELTAS[direction]
                neighbor = (current[0] + dr, current[1] + dc)
                if neighbor not in goal_set and not self._walkable(neighbor, entity_map, allow_unknown):
                    continue
                next_g = current_g + 1
                if next_g < g_score.get(neighbor, 9999999):
                    came_from[neighbor] = current
                    g_score[neighbor] = next_g
                    tie_breaker += 1
                    heapq.heappush(heap, (next_g + heuristic(neighbor), tie_breaker, neighbor))

        return []

    def _walkable(self, pos: tuple[int, int], entity_map: EntityMap, allow_unknown: bool) -> bool:
        if entity_map.is_wall(pos) or entity_map.is_structure(pos) or entity_map.has_agent(pos):
            return False
        if pos in entity_map.explored:
            return pos not in entity_map.entities or entity_map.entities[pos].type == "agent"
        return allow_unknown

    def _frontier(
        self,
        pos: tuple[int, int],
        entity_map: EntityMap,
        bias: str | None,
    ) -> tuple[int, int] | None:
        ordered_dirs = self._ordered_directions(bias)
        deltas = [MOVE_DELTAS[direction] for direction in ordered_dirs]

        visited: set[tuple[int, int]] = {pos}
        queue: deque[tuple[int, int, int]] = deque([(pos[0], pos[1], 0)])
        while queue:
            row, col, dist = queue.popleft()
            if dist > 50:
                continue

            for dr, dc in deltas:
                p = (row + dr, col + dc)
                if p in visited:
                    continue
                visited.add(p)

                if p not in entity_map.explored:
                    for dr2, dc2 in deltas:
                        adj = (p[0] + dr2, p[1] + dc2)
                        if adj in entity_map.explored and entity_map.is_free(adj):
                            return p
                    continue

                if entity_map.is_free(p):
                    queue.append((p[0], p[1], dist + 1))

        return None

    def _sidestep(
        self,
        current: tuple[int, int],
        blocked: tuple[int, int],
        target: tuple[int, int],
        entity_map: EntityMap,
    ) -> tuple[int, int] | None:
        current_dist = manhattan(current, target)
        candidates: list[tuple[int, int, tuple[int, int]]] = []

        for direction in DIRECTIONS:
            dr, dc = MOVE_DELTAS[direction]
            pos = (current[0] + dr, current[1] + dc)
            if pos == blocked:
                continue
            if self._walkable(pos, entity_map, True):
                candidates.append((manhattan(pos, target) - current_dist, DIRECTIONS.index(direction), pos))

        if candidates:
            candidates.sort()
            if candidates[0][0] <= 2:
                return candidates[0][2]
        return None

    def _greedy(
        self,
        current: tuple[int, int],
        target: tuple[int, int],
        entity_map: EntityMap,
    ) -> Action:
        dr, dc = target[0] - current[0], target[1] - current[1]
        if abs(dr) >= abs(dc):
            primary = "south" if dr > 0 else "north"
            secondary = "east" if dc > 0 else "west"
        else:
            primary = "east" if dc > 0 else "west"
            secondary = "south" if dr > 0 else "north"

        for direction in (primary, secondary):
            ddr, ddc = MOVE_DELTAS[direction]
            pos = (current[0] + ddr, current[1] + ddc)
            if not entity_map.is_wall(pos) and not entity_map.is_structure(pos) and not entity_map.has_agent(pos):
                return Action(name=f"move_{direction}")

        return self._fallback_move(current, entity_map, None)

    def _fallback_move(self, pos: tuple[int, int], entity_map: EntityMap, bias: str | None) -> Action:
        for direction in self._ordered_directions(bias):
            dr, dc = MOVE_DELTAS[direction]
            nxt = (pos[0] + dr, pos[1] + dc)
            if self._walkable(nxt, entity_map, False):
                return Action(name=f"move_{direction}")
        return Action(name="noop")


def manhattan(a: tuple[int, int], b: tuple[int, int]) -> int:
    return abs(a[0] - b[0]) + abs(a[1] - b[1])


def move_action(current: tuple[int, int], target: tuple[int, int]) -> Action:
    dr, dc = target[0] - current[0], target[1] - current[1]
    if dr == -1 and dc == 0:
        return Action(name="move_north")
    if dr == 1 and dc == 0:
        return Action(name="move_south")
    if dr == 0 and dc == 1:
        return Action(name="move_east")
    if dr == 0 and dc == -1:
        return Action(name="move_west")
    return Action(name="noop")


def move_toward(current: tuple[int, int], target: tuple[int, int]) -> Action:
    dr, dc = target[0] - current[0], target[1] - current[1]
    if dr == 1 and dc == 0:
        return Action(name="move_south")
    if dr == -1 and dc == 0:
        return Action(name="move_north")
    if dr == 0 and dc == 1:
        return Action(name="move_east")
    if dr == 0 and dc == -1:
        return Action(name="move_west")
    if abs(dr) >= abs(dc):
        return Action(name="move_south" if dr > 0 else "move_north")
    return Action(name="move_east" if dc > 0 else "move_west")
