"""A* navigator for the Hunger agent."""

from __future__ import annotations

import heapq
import random
from collections import deque
from typing import TYPE_CHECKING

from mettagrid.simulator import Action

if TYPE_CHECKING:
    from .entity_map import EntityMap

MOVE_DELTAS: dict[str, tuple[int, int]] = {
    "north": (-1, 0),
    "south": (1, 0),
    "east": (0, 1),
    "west": (0, -1),
}
DIRECTIONS = list(MOVE_DELTAS)


class Navigator:
    def __init__(self) -> None:
        self._cached_path: list[tuple[int, int]] | None = None
        self._cached_target: tuple[int, int] | None = None
        self._history: list[tuple[int, int]] = []

    def get_action(
        self,
        pos: tuple[int, int],
        target: tuple[int, int],
        map: EntityMap,
        reach_adjacent: bool = False,
    ) -> Action:
        self._track(pos)
        if self._is_stuck():
            return self._break_stuck(pos, map)

        if pos == target and not reach_adjacent:
            return Action(name="noop")
        if reach_adjacent and manhattan(pos, target) == 1:
            return Action(name="noop")

        path = self._get_path(pos, target, map, reach_adjacent)
        if not path:
            return self._greedy(pos, target, map)

        nxt = path[0]
        if map.has_agent(nxt):
            side = self._sidestep(pos, nxt, target, map)
            if side:
                self._cached_path = None
                return move_action(pos, side)
            return Action(name="noop")

        self._cached_path = path[1:] or None
        return move_action(pos, nxt)

    def explore(self, pos: tuple[int, int], map: EntityMap, bias: str | None = None) -> Action:
        self._track(pos)
        if self._is_stuck():
            return self._break_stuck(pos, map)
        frontier = self._frontier(pos, map, bias)
        if frontier:
            return self.get_action(pos, frontier, map)
        return self._random(pos, map)

    def _track(self, pos: tuple[int, int]) -> None:
        self._history.append(pos)
        if len(self._history) > 30:
            self._history.pop(0)

    def _is_stuck(self) -> bool:
        h = self._history
        if len(h) >= 6 and len(set(h[-6:])) <= 2:
            return True
        return len(h) >= 20 and h[:-10].count(h[-1]) >= 2

    def _break_stuck(self, pos: tuple[int, int], map: EntityMap) -> Action:
        self._cached_path = None
        self._cached_target = None
        self._history.clear()
        return self._random(pos, map)

    def _get_path(
        self, start: tuple[int, int], target: tuple[int, int], map: EntityMap, adj: bool
    ) -> list[tuple[int, int]] | None:
        if self._cached_path and self._cached_target == target:
            return self._cached_path
        goals = self._goal_cells(target, map, adj)
        if not goals:
            return None
        path = self._astar(start, goals, map, False) or self._astar(start, goals, map, True)
        self._cached_path = list(path) if path else None
        self._cached_target = target
        return self._cached_path

    def _goal_cells(self, target: tuple[int, int], map: EntityMap, adj: bool) -> list[tuple[int, int]]:
        if not adj:
            return [target]
        goals: list[tuple[int, int]] = []
        for dr, dc in MOVE_DELTAS.values():
            cell = (target[0] + dr, target[1] + dc)
            if map.is_wall(cell) or map.is_structure(cell) or map.has_agent(cell):
                continue
            goals.append(cell)
        return goals

    def _astar(
        self,
        start: tuple[int, int],
        goals: list[tuple[int, int]],
        map: EntityMap,
        allow_unknown: bool,
    ) -> list[tuple[int, int]]:
        goal_set = set(goals)

        def h(p: tuple[int, int]) -> int:
            return min(manhattan(p, g) for g in goals)

        tie = 0
        heap: list[tuple[int, int, tuple[int, int]]] = [(h(start), 0, start)]
        came: dict[tuple[int, int], tuple[int, int] | None] = {start: None}
        gscore: dict[tuple[int, int], int] = {start: 0}

        for _ in range(5000):
            if not heap:
                break
            _, _, cur = heapq.heappop(heap)
            if cur in goal_set:
                path: list[tuple[int, int]] = []
                while came[cur] is not None:
                    path.append(cur)
                    cur = came[cur]  # type: ignore[assignment]
                path.reverse()
                return path
            cg = gscore.get(cur, 9999999)
            for dr, dc in MOVE_DELTAS.values():
                nb = (cur[0] + dr, cur[1] + dc)
                if nb not in goal_set and not self._walkable(nb, map, allow_unknown):
                    continue
                ng = cg + 1
                if ng < gscore.get(nb, 9999999):
                    came[nb] = cur
                    gscore[nb] = ng
                    tie += 1
                    heapq.heappush(heap, (ng + h(nb), tie, nb))
        return []

    def _walkable(self, pos: tuple[int, int], map: EntityMap, allow_unknown: bool) -> bool:
        if map.is_wall(pos) or map.is_structure(pos) or map.has_agent(pos):
            return False
        if pos in map.explored:
            return pos not in map.entities or map.entities[pos].type == "agent"
        return allow_unknown

    def _frontier(self, pos: tuple[int, int], map: EntityMap, bias: str | None) -> tuple[int, int] | None:
        deltas = list(MOVE_DELTAS.values())
        if bias and bias in MOVE_DELTAS:
            d = MOVE_DELTAS[bias]
            deltas = [d] + [x for x in deltas if x != d]

        visited: set[tuple[int, int]] = {pos}
        q: deque[tuple[int, int, int]] = deque([(pos[0], pos[1], 0)])
        while q:
            r, c, dist = q.popleft()
            if dist > 50:
                continue
            for dr, dc in deltas:
                p = (r + dr, c + dc)
                if p in visited:
                    continue
                visited.add(p)
                if p not in map.explored:
                    for dr2, dc2 in deltas:
                        adj = (p[0] + dr2, p[1] + dc2)
                        if adj in map.explored and map.is_free(adj):
                            return p
                    continue
                if map.is_free(p):
                    q.append((p[0], p[1], dist + 1))
        return None

    def _sidestep(
        self,
        cur: tuple[int, int],
        blocked: tuple[int, int],
        target: tuple[int, int],
        map: EntityMap,
    ) -> tuple[int, int] | None:
        cd = manhattan(cur, target)
        cands = []
        for d in DIRECTIONS:
            dr, dc = MOVE_DELTAS[d]
            p = (cur[0] + dr, cur[1] + dc)
            if p == blocked:
                continue
            if self._walkable(p, map, True):
                cands.append((manhattan(p, target) - cd, p))
        if cands:
            cands.sort()
            if cands[0][0] <= 2:
                return cands[0][1]
        return None

    def _greedy(self, cur: tuple[int, int], target: tuple[int, int], map: EntityMap) -> Action:
        dr, dc = target[0] - cur[0], target[1] - cur[1]
        if abs(dr) >= abs(dc):
            primary = "south" if dr > 0 else "north"
            secondary = "east" if dc > 0 else "west"
        else:
            primary = "east" if dc > 0 else "west"
            secondary = "south" if dr > 0 else "north"
        for d in (primary, secondary):
            ddr, ddc = MOVE_DELTAS[d]
            p = (cur[0] + ddr, cur[1] + ddc)
            if not map.is_wall(p) and not map.is_structure(p) and not map.has_agent(p):
                return Action(name=f"move_{d}")
        return self._random(cur, map)

    def _random(self, pos: tuple[int, int], map: EntityMap) -> Action:
        dirs = list(DIRECTIONS)
        random.shuffle(dirs)
        for d in dirs:
            dr, dc = MOVE_DELTAS[d]
            p = (pos[0] + dr, pos[1] + dc)
            if p in map.explored and not map.is_wall(p) and not map.is_structure(p):
                return Action(name=f"move_{d}")
        for d in dirs:
            dr, dc = MOVE_DELTAS[d]
            if not map.is_wall((pos[0] + dr, pos[1] + dc)):
                return Action(name=f"move_{d}")
        return Action(name="noop")


def manhattan(a: tuple[int, int], b: tuple[int, int]) -> int:
    return abs(a[0] - b[0]) + abs(a[1] - b[1])


def move_action(cur: tuple[int, int], tgt: tuple[int, int]) -> Action:
    dr, dc = tgt[0] - cur[0], tgt[1] - cur[1]
    if dr == -1 and dc == 0:
        return Action(name="move_north")
    if dr == 1 and dc == 0:
        return Action(name="move_south")
    if dr == 0 and dc == 1:
        return Action(name="move_east")
    if dr == 0 and dc == -1:
        return Action(name="move_west")
    return Action(name="noop")


def move_toward(cur: tuple[int, int], tgt: tuple[int, int]) -> Action:
    """Move one step toward target (for bumping adjacent objects)."""
    dr, dc = tgt[0] - cur[0], tgt[1] - cur[1]
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
