"""Follower tests: diagonal speed exploitation + wall bump-and-dodge.

Ported from swgy-crewrift ``test_follow_diagonal.py`` + ``test_follow_dodge.py``.

The engine clamps velX/velY independently, so holding both buttons yields |v| =
max_speed*sqrt(2) (~+41%). The inertia follower used to L2-normalise the desired velocity to
|v| = max_speed, braking the diagonal down -- the "follows slowly" bug.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from players.player_sdk import nav_mesh as nav
from players.player_sdk.nav_mesh.model import NavGrid
from players.player_sdk.nav_mesh.params import NavParams
from players.player_sdk.nav_mesh.plan import NavPlan


def test_engine_diagonal_is_41pct_faster_than_cardinal():
    """The verified speed model: because the engine clamps velX/velY per-axis
    (Accel=76, MaxSpeed=704, MotionScale=256, never normalized), holding two
    buttons reaches |v| = max_speed*sqrt(2). Cardinal terminal is max_speed."""
    max_speed = 704 / 256  # the origin engine's MaxSpeed/MotionScale, px/tick
    assert max_speed == 2.75
    cardinal = max_speed  # one axis at terminal
    diagonal = math.hypot(max_speed, max_speed)  # both axes clamped independently
    assert diagonal == pytest.approx(max_speed * math.sqrt(2))
    speedup = diagonal / cardinal - 1.0
    assert 0.41 < speedup < 0.415  # ~ +41.4%


def _far_diag_state(diagonal: bool) -> "nav.NavState":
    # A far diagonal waypoint -> no arrival easing; cruising at 2.5 px/axis, which sits ABOVE
    # the old L2 desired (2.75/sqrt(2)=1.94) but below the per-axis max (2.75).
    state = nav.NavState(
        plan=NavPlan(nodes=(0,), waypoints=((1000, 1000),), cost=0.0, goal=0),
        params=NavParams(diagonal=diagonal),
    )  # inertia default True
    state.velocity = (2.5, 2.5)
    return state


def test_diagonal_holds_full_per_axis_speed():
    # Must KEEP pressing both axes (hold the boost), not brake. L2 would return (-1, -1).
    assert _far_diag_state(diagonal=True).heading((0, 0)) == (1, 1)


def test_four_way_presses_one_axis_when_diagonal_off():
    dx, dy = _far_diag_state(diagonal=False).heading((0, 0))
    assert (dx == 0) ^ (dy == 0)  # exactly one axis under 4-way


# --- bump-and-dodge (from test_follow_dodge.py) ---

def _state(grid: NavGrid | None) -> "nav.NavState":
    return nav.NavState(
        plan=NavPlan(nodes=(0,), waypoints=((30, 10),), cost=0.0, goal=0),
        params=NavParams(),
        grid=grid,
    )


def test_goes_straight_when_path_is_clear():
    grid = NavGrid.from_mask(np.ones((40, 40), bool))
    assert _state(grid).heading((10, 10), collision=(10, 10)) == (1, 0)


def test_dodges_around_a_wall_block():
    mask = np.ones((40, 40), bool)
    mask[8:13, 14:17] = False  # wall block: y in [8,12], x in [14,16]
    grid = NavGrid.from_mask(mask)
    state = _state(grid)
    assert not state._walkable_ahead((10, 10), 1, 0)  # straight right is blocked
    dx, dy = state.heading((10, 10), collision=(10, 10))
    assert dx == 1 and dy != 0  # deviated off-axis to round the block
    assert state._walkable_ahead((10, 10), dx, dy)  # ...and the chosen direction is clear


def test_no_grid_is_passthrough():
    # No walkability data -> steering is whatever pure seek produced (here straight right).
    assert _state(None).heading((10, 10), collision=(10, 10)) == (1, 0)
