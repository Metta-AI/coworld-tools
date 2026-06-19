"""Tests for the Paint Arena default policy.

Embeds an exact local simulator of the Paint Arena game server
(`coworld/examples/paintarena/game/server.py`) so the scripted policy can be
checked deterministically with no Docker and no hosted evals. This simulator is
the fast iteration harness for strategy changes.
"""

from __future__ import annotations

from collections.abc import Callable

from players.paintarena.default.strategy import MOVES, Observation, choose_move

WIDTH = 12
HEIGHT = 8
MAX_TICKS = 100
DIRECTIONS = {"up": (0, -1), "down": (0, 1), "left": (-1, 0), "right": (1, 0), "stay": (0, 0)}

Policy = Callable[[dict, int], str]


def _starting_positions(count: int) -> list[list[int]]:
    corners = [[0, 0], [WIDTH - 1, HEIGHT - 1], [0, HEIGHT - 1], [WIDTH - 1, 0]]
    return [corners[slot % len(corners)].copy() for slot in range(count)]


def _snapshot(positions: list[list[int]], tile_owners: list[int], tick: int) -> dict:
    return {
        "type": "observation",
        "width": WIDTH,
        "height": HEIGHT,
        "positions": [p.copy() for p in positions],
        "tile_owners": tile_owners.copy(),
        "scores": [tile_owners.count(s) for s in range(len(positions))],
        "tick": tick,
        "max_ticks": MAX_TICKS,
    }


def _play(p0: Policy, p1: Policy) -> tuple[int, int]:
    positions = _starting_positions(2)
    tile_owners = [-1] * (WIDTH * HEIGHT)
    policies = [p0, p1]
    obs = _snapshot(positions, tile_owners, 0)
    actions = [policies[s](obs, s) for s in range(2)]
    for tick in range(1, MAX_TICKS + 1):
        for slot in range(2):
            dx, dy = DIRECTIONS[actions[slot]]
            x, y = positions[slot]
            positions[slot] = [min(max(x + dx, 0), WIDTH - 1), min(max(y + dy, 0), HEIGHT - 1)]
        for slot in range(2):
            x, y = positions[slot]
            tile_owners[y * WIDTH + x] = slot
        obs = _snapshot(positions, tile_owners, tick)
        actions = [policies[s](obs, s) for s in range(2)]
    return tile_owners.count(0), tile_owners.count(1)


def _sweep_move(message: dict, slot: int) -> str:
    x, y = message["positions"][slot]
    width, height = message["width"], message["height"]
    if slot % 2 == 0:
        if y % 2 == 0 and x < width - 1:
            return "right"
        if y % 2 == 1 and x > 0:
            return "left"
        if y < height - 1:
            return "down"
        return "up"
    if y % 2 == 0 and x > 0:
        return "left"
    if y % 2 == 1 and x < width - 1:
        return "right"
    if y > 0:
        return "up"
    return "down"


def _default_move(message: dict, slot: int) -> str:
    return choose_move(Observation.model_validate(message), slot)


def test_choose_move_always_legal() -> None:
    """Over a full self-play game the policy only ever emits legal moves."""
    positions = _starting_positions(2)
    tile_owners = [-1] * (WIDTH * HEIGHT)
    for tick in range(MAX_TICKS + 1):
        obs = _snapshot(positions, tile_owners, tick)
        for slot in range(2):
            move = choose_move(Observation.model_validate(obs), slot)
            assert move in MOVES
            dx, dy = DIRECTIONS[move]
            x, y = positions[slot]
            positions[slot] = [min(max(x + dx, 0), WIDTH - 1), min(max(y + dy, 0), HEIGHT - 1)]
        for slot in range(2):
            x, y = positions[slot]
            tile_owners[y * WIDTH + x] = slot


def test_stays_when_board_fully_owned() -> None:
    obs = Observation(
        width=WIDTH,
        height=HEIGHT,
        positions=[[0, 0], [WIDTH - 1, HEIGHT - 1]],
        tile_owners=[0] * (WIDTH * HEIGHT),
        tick=10,
        max_ticks=MAX_TICKS,
    )
    assert choose_move(obs, 0) == "stay"


def test_beats_sweep_painter_from_both_seats() -> None:
    a0, a1 = _play(_default_move, _sweep_move)
    assert a0 > a1, f"default(seat0)={a0} should beat sweep(seat1)={a1}"
    b0, b1 = _play(_sweep_move, _default_move)
    assert b1 > b0, f"default(seat1)={b1} should beat sweep(seat0)={b0}"
