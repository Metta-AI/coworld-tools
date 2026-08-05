"""Tests for the Paint Arena gridnav demo policy.

Embeds its own copy of the exact local Paint Arena simulator (same as
``test_paintarena_default.py`` — deliberately duplicated rather than
refactoring that file) so the SDK-library demo can be checked
deterministically with no Docker and no hosted evals.
"""

from __future__ import annotations

from collections.abc import Callable

from players.paintarena.gridnav.strategy import MOVES, GridNavPolicy, Observation

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


def _gridnav_policy() -> Policy:
    policy = GridNavPolicy()

    def move(message: dict, slot: int) -> str:
        return policy.choose_move(Observation.model_validate(message), slot)

    return move


def test_choose_move_always_legal() -> None:
    """Over a full self-play game the policy only ever emits legal moves."""
    positions = _starting_positions(2)
    tile_owners = [-1] * (WIDTH * HEIGHT)
    policies = [GridNavPolicy(), GridNavPolicy()]
    for tick in range(MAX_TICKS + 1):
        obs = _snapshot(positions, tile_owners, tick)
        for slot in range(2):
            move = policies[slot].choose_move(Observation.model_validate(obs), slot)
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
    assert GridNavPolicy().choose_move(obs, 0) == "stay"


def test_paints_meaningful_territory_from_both_seats() -> None:
    """The demo must actually work as a player: against the bundled sweep
    painter it should claim a solid share of the board from either seat."""
    a0, a1 = _play(_gridnav_policy(), _sweep_move)
    assert a0 >= WIDTH * HEIGHT // 3, f"gridnav(seat0)={a0} vs sweep={a1}"
    b0, b1 = _play(_sweep_move, _gridnav_policy())
    assert b1 >= WIDTH * HEIGHT // 3, f"gridnav(seat1)={b1} vs sweep={b0}"


def test_sticky_target_prevents_oscillation() -> None:
    """With two equidistant unpainted tiles, the sticky target keeps the
    policy committed instead of flip-flopping (net progress every 2 ticks)."""
    policy = GridNavPolicy()
    positions = _starting_positions(2)
    tile_owners = [-1] * (WIDTH * HEIGHT)
    seen: list[list[int]] = []
    for tick in range(30):
        obs = _snapshot(positions, tile_owners, tick)
        move = policy.choose_move(Observation.model_validate(obs), 0)
        dx, dy = DIRECTIONS[move]
        x, y = positions[0]
        positions[0] = [min(max(x + dx, 0), WIDTH - 1), min(max(y + dy, 0), HEIGHT - 1)]
        x, y = positions[0]
        tile_owners[y * WIDTH + x] = 0
        seen.append(positions[0].copy())
    unique_cells = {tuple(p) for p in seen}
    # 30 ticks of committed painting should visit many distinct cells.
    assert len(unique_cells) >= 12, f"visited only {len(unique_cells)} cells"
