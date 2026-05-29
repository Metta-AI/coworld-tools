"""Nav grid + A* route planning tests (design §6, §9)."""

from __future__ import annotations

import numpy as np

from players.crewrift.crewborg.nav import build_nav_grid, plan_route


def test_coarse_cell_walkable_only_if_all_pixels_walkable() -> None:
    mask = np.ones((16, 16), dtype=bool)
    mask[0, 0] = False  # one blocked pixel taints its 8x8 cell
    grid = build_nav_grid(mask, cell_size=8)
    assert grid.rows == 2 and grid.cols == 2
    assert not grid.is_walkable_cell(0, 0)
    assert grid.is_walkable_cell(1, 1)


def test_route_goes_around_a_wall() -> None:
    # Open 80x24 map with a vertical wall at columns 32..39 except a gap at the top.
    mask = np.ones((24, 80), dtype=bool)
    mask[8:, 32:40] = False  # wall blocks the lower rows; gap stays open up top
    grid = build_nav_grid(mask, cell_size=8)

    route = plan_route(grid, (8, 16), (72, 16))
    assert route, "expected a route around the wall"
    assert route[-1] == (72, 16)  # ends exactly on the goal
    # The detour must rise toward the gap rather than crossing the wall band.
    assert any(y < 8 for _, y in route)


def test_unreachable_goal_returns_empty() -> None:
    mask = np.ones((24, 48), dtype=bool)
    mask[:, 24:32] = False  # a full-height wall splits the map in two
    grid = build_nav_grid(mask, cell_size=8)
    assert plan_route(grid, (8, 12), (40, 12)) == []


def test_nearest_walkable_snaps_a_blocked_start() -> None:
    mask = np.ones((16, 16), dtype=bool)
    mask[0:8, 0:8] = False  # top-left cell blocked
    grid = build_nav_grid(mask, cell_size=8)
    # Start inside the blocked cell still yields a route by snapping to a neighbour.
    assert plan_route(grid, (2, 2), (12, 12))
