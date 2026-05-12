"""Geometry, movement, and navigation helpers."""

from __future__ import annotations

from cvc.cogent.player_cog.policy.helpers.types import (
    _ALIGNER_EXPLORE_OFFSETS,
    _MINER_EXPLORE_OFFSETS,
    _MOVE_DELTAS,
    _SCRAMBLER_EXPLORE_OFFSETS,
)


def manhattan(a: tuple[int, int], b: tuple[int, int]) -> int:
    return abs(a[0] - b[0]) + abs(a[1] - b[1])


def direction_from_step(current: tuple[int, int], next_step: tuple[int, int]) -> str:
    dx = next_step[0] - current[0]
    dy = next_step[1] - current[1]
    if dx == 1:
        return "east"
    if dx == -1:
        return "west"
    if dy == 1:
        return "south"
    if dy == -1:
        return "north"
    raise ValueError(f"Non-adjacent step from {current} to {next_step}")


def format_position(position: tuple[int, int]) -> str:
    return f"{position[0]},{position[1]}"


def greedy_step(
    current: tuple[int, int],
    target: tuple[int, int],
    blocked: set[tuple[int, int]],
) -> tuple[int, int] | None:
    candidates = []
    for direction, (dx, dy) in _MOVE_DELTAS.items():
        nxt = (current[0] + dx, current[1] + dy)
        if nxt in blocked:
            continue
        candidates.append((manhattan(nxt, target), direction, nxt))
    if not candidates:
        return None
    candidates.sort()
    return candidates[0][2]


def explore_offsets(role: str) -> tuple[tuple[int, int], ...]:
    if role == "miner":
        return _MINER_EXPLORE_OFFSETS
    if role == "scrambler":
        return _SCRAMBLER_EXPLORE_OFFSETS
    return _ALIGNER_EXPLORE_OFFSETS


def unstick_directions(agent_id: int, step_index: int) -> tuple[str, ...]:
    orders = (
        ("north", "east", "south", "west"),
        ("east", "south", "west", "north"),
        ("south", "west", "north", "east"),
        ("west", "north", "east", "south"),
    )
    return orders[(agent_id + step_index) % len(orders)]
