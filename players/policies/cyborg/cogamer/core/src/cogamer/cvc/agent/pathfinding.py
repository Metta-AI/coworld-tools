"""Pure pathfinding and oscillation detection functions."""

from __future__ import annotations

import heapq
from dataclasses import dataclass

from cogamer.cvc.agent.geometry import greedy_step, manhattan
from cogamer.cvc.agent.types import _MOVE_DELTAS

_DEFAULT_BOUND_MARGIN = 12


@dataclass(slots=True)
class NavigationObservation:
    position: tuple[int, int]
    subtask: str
    target_kind: str
    target_position: tuple[int, int] | None


def astar_next_step(
    current: tuple[int, int],
    target: tuple[int, int],
    blocked: set[tuple[int, int]],
    *,
    bound_margin: int = _DEFAULT_BOUND_MARGIN,
) -> tuple[int, int] | None:
    if current == target:
        return None

    if manhattan(current, target) <= 1:
        return target

    min_x = min(current[0], target[0]) - bound_margin
    max_x = max(current[0], target[0]) + bound_margin
    min_y = min(current[1], target[1]) - bound_margin
    max_y = max(current[1], target[1]) + bound_margin

    frontier: list[tuple[int, int, tuple[int, int]]] = [(0, 0, current)]
    came_from: dict[tuple[int, int], tuple[int, int]] = {}
    best_cost = {current: 0}

    while frontier:
        _, cost, node = heapq.heappop(frontier)
        if node == target:
            break
        if cost > best_cost.get(node, cost):
            continue
        for dx, dy in _MOVE_DELTAS.values():
            nxt = (node[0] + dx, node[1] + dy)
            if nxt in blocked:
                continue
            if nxt[0] < min_x or nxt[0] > max_x or nxt[1] < min_y or nxt[1] > max_y:
                continue
            next_cost = cost + 1
            if next_cost >= best_cost.get(nxt, 1 << 30):
                continue
            best_cost[nxt] = next_cost
            came_from[nxt] = node
            priority = next_cost + manhattan(nxt, target)
            heapq.heappush(frontier, (priority, next_cost, nxt))

    if target not in came_from:
        return greedy_step(current, target, blocked)

    step = target
    while came_from[step] != current:
        step = came_from[step]
    return step


def detect_extractor_oscillation(
    observations: list[NavigationObservation],
    *,
    max_history: int = 6,
) -> int:
    if len(observations) < 2:
        return 0
    max_size = min(len(observations), max_history)
    for size in range(max_size, 1, -1):
        window = observations[-size:]
        first = window[0]
        second = window[1]
        if first.position == second.position:
            continue
        if not first.subtask.startswith("mine_"):
            continue
        if not first.target_kind.endswith("_extractor"):
            continue
        if first.target_position is None:
            continue
        if any(
            item.subtask != first.subtask
            or item.target_kind != first.target_kind
            or item.target_position != first.target_position
            for item in window
        ):
            continue
        if all(
            item.position == (first.position if index % 2 == 0 else second.position)
            for index, item in enumerate(window)
        ):
            return size
    return 0
