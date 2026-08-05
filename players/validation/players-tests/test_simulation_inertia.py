"""The inertial movement port must match the reference engine's physics.

Ported 1:1 from swgy-crewrift ``packages/swgy-tools/tests/test_enginesim.py``
(module constants became ``InertiaParams`` fields; ``Player`` became
``Body``). The default profile is byte-faithful to the origin engine
(sim.nim), so these assertions pin exact integers, not approximations.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from players.player_sdk.nav_mesh.model import NavGrid
from players.player_sdk.simulation.inertia import Body, Engine, InertiaParams, Walkability, _tdiv

P = InertiaParams()


def _open_engine(n: int = 200) -> Engine:
    return Engine(NavGrid.from_mask(np.ones((n, n), dtype=bool)))


def test_tdiv_truncates_toward_zero_like_nim():
    # Python // floors; Nim div truncates. Friction on negative velocity needs trunc.
    assert _tdiv(-43200, 256) == -168  # not -169
    assert _tdiv(43200, 256) == 168


def test_cardinal_terminal_speed_is_2_75_px():
    eng = _open_engine()
    b = Body(x=20, y=20)
    for _ in range(200):  # plenty to reach terminal
        eng.step(b, 1, 0)
    assert b.velX == P.max_speed  # clamped per-axis
    assert eng.speed_px_of(b) == P.max_speed / P.motion_scale == P.terminal_px == 2.75


def test_diagonal_terminal_speed_is_sqrt2_times_cardinal():
    eng = _open_engine()
    b = Body(x=20, y=20)
    for _ in range(200):
        eng.step(b, 1, 1)
    assert b.velX == P.max_speed and b.velY == P.max_speed  # both axes clamped independently
    assert eng.speed_px_of(b) == pytest.approx(math.sqrt(2) * P.terminal_px)


def test_diagonal_covers_ground_about_41pct_faster():
    eng = _open_engine()
    card, diag = Body(x=20, y=20), Body(x=20, y=20)
    for _ in range(120):
        eng.step(card, 1, 0)
        eng.step(diag, 1, 1)
    card_dist = math.hypot(card.x - 20, card.y - 20)
    diag_dist = math.hypot(diag.x - 20, diag.y - 20)
    ratio = diag_dist / card_dist
    assert 1.40 < ratio < 1.43  # ~ sqrt(2), the +41% boost


def test_friction_decays_and_stops_below_threshold():
    eng = _open_engine()
    b = Body(x=50, y=50)
    for _ in range(40):  # accelerate right
        eng.step(b, 1, 0)
    assert b.velX == P.max_speed
    for _ in range(60):  # release: friction multiplies by 144/256 each tick, then snaps to 0
        eng.step(b, 0, 0)
    assert b.velX == 0  # came to rest (|v| < stop_threshold -> 0)
    assert P.friction_num / P.friction_den == 0.5625


def test_wall_blocks_and_slides_along_it():
    mask = np.ones((60, 60), dtype=bool)
    mask[:, 30] = False  # vertical wall at x=30 (block the column)
    eng = Engine(NavGrid.from_mask(mask))
    b = Body(x=20, y=20)
    for _ in range(200):
        eng.step(b, 1, 0)  # push straight into the wall
    assert b.x < 30  # never passes through the wall
    assert not eng.can_occupy(30, b.y)


def test_diagonal_into_wall_slides_up_the_free_axis():
    mask = np.ones((80, 80), dtype=bool)
    mask[:, 40] = False  # wall column at x=40
    eng = Engine(NavGrid.from_mask(mask))
    b = Body(x=20, y=40)
    for _ in range(200):
        eng.step(b, 1, -1)  # push up-right into the wall; x blocked, y should slide
    assert b.x < 40  # x stalls at the wall
    assert b.y < 40  # but y kept moving (slid up the wall)


def test_accel_constant_matches_engine():
    eng = _open_engine()
    b = Body(x=20, y=20)
    eng.step(b, 1, 0)
    assert b.velX == P.accel  # one tick of input adds exactly accel


def test_params_are_tunable_and_grid_is_duck_typed():
    # A different profile changes the physics (not byte-faithful, by design).
    slow = InertiaParams(max_speed=256)  # 1 px/tick terminal

    class EverywhereOpen:
        def is_walkable(self, x: int, y: int) -> bool:
            return True

    assert isinstance(EverywhereOpen(), Walkability)
    eng = Engine(EverywhereOpen(), params=slow)
    b = Body(x=0, y=0)
    for _ in range(100):
        eng.step(b, 1, 0)
    assert eng.speed_px_of(b) == 1.0
