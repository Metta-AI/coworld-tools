"""Unit tests for :mod:`players.among_them.coborg.perception.geometry`.

All public functions are pure scalar arithmetic over the baked map
metadata and screen/sprite constants. These tests pin the formulas
upstream uses; if any constant drifts, the parity rig in
``test_perception_parity`` would also fail, but a focused failure here
localises the cause."""

from __future__ import annotations

from players.among_them.coborg.perception import geometry
from players.among_them.coborg.perception.data import (
    BUTTON_H,
    BUTTON_W,
    BUTTON_X,
    BUTTON_Y,
    MAP_HEIGHT,
    MAP_WIDTH,
    SPRITE_DRAW_OFF_X,
    SPRITE_DRAW_OFF_Y,
    SPRITE_SIZE,
)
from players.among_them.coborg.perception.frame import (
    SCREEN_HEIGHT,
    SCREEN_WIDTH,
)


# --- constants -----------------------------------------------------------


def test_player_world_off_matches_upstream_formula():
    assert geometry.PLAYER_WORLD_OFF_X == SPRITE_DRAW_OFF_X + (SCREEN_WIDTH // 2) - (SPRITE_SIZE // 2)
    assert geometry.PLAYER_WORLD_OFF_Y == SPRITE_DRAW_OFF_Y + (SCREEN_HEIGHT // 2) - (SPRITE_SIZE // 2)
    # With current constants: 2 + 64 - 6 = 60, 8 + 64 - 6 = 66.
    assert geometry.PLAYER_WORLD_OFF_X == 60
    assert geometry.PLAYER_WORLD_OFF_Y == 66


def test_camera_bounds_formulas():
    assert geometry.min_camera_x() == -SCREEN_WIDTH // 2 - SPRITE_SIZE
    assert geometry.max_camera_x() == MAP_WIDTH - SCREEN_WIDTH // 2 + SPRITE_SIZE
    assert geometry.min_camera_y() == -SCREEN_HEIGHT // 2 - SPRITE_SIZE
    assert geometry.max_camera_y() == MAP_HEIGHT - SCREEN_HEIGHT // 2 + SPRITE_SIZE
    assert geometry.camera_width() == geometry.max_camera_x() - geometry.min_camera_x() + 1
    assert geometry.camera_height() == geometry.max_camera_y() - geometry.min_camera_y() + 1


# --- button + clamping --------------------------------------------------


def test_button_camera_centres_on_button():
    # Upstream: target = button.x + button.w // 2 - PLAYER_WORLD_OFF_X
    expected_x = BUTTON_X + BUTTON_W // 2 - geometry.PLAYER_WORLD_OFF_X
    expected_y = BUTTON_Y + BUTTON_H // 2 - geometry.PLAYER_WORLD_OFF_Y
    assert geometry.button_camera_x() == expected_x
    assert geometry.button_camera_y() == expected_y


def test_camera_x_for_world_clamps_to_range():
    # Far-positive world coord clamps to max_camera_x.
    assert geometry.camera_x_for_world(10_000) == geometry.max_camera_x()
    # Far-negative clamps to min_camera_x.
    assert geometry.camera_x_for_world(-10_000) == geometry.min_camera_x()


def test_camera_y_for_world_clamps_to_range():
    assert geometry.camera_y_for_world(10_000) == geometry.max_camera_y()
    assert geometry.camera_y_for_world(-10_000) == geometry.min_camera_y()


# --- camera_can_hold_player ---------------------------------------------


def test_camera_can_hold_player_inside_map():
    # A camera near (0, 0) puts the player at (PLAYER_WORLD_OFF_X, ...),
    # which is inside the 952x534 map.
    assert geometry.camera_can_hold_player(0, 0)
    assert geometry.camera_can_hold_player(400, 200)


def test_camera_can_hold_player_outside_map():
    # Far-negative camera puts the player off the map's top-left.
    assert not geometry.camera_can_hold_player(-200, -200)
    # Far-positive puts them off the bottom-right.
    assert not geometry.camera_can_hold_player(MAP_WIDTH + 100, MAP_HEIGHT + 100)


# --- world <-> camera round-trip ----------------------------------------


def test_player_world_round_trip():
    """A camera at offset (cx, cy) puts the player at world
    (cx + PLAYER_WORLD_OFF_X, cy + PLAYER_WORLD_OFF_Y). The inverse
    works as long as the world coord is in the clamping range."""
    for cx in [0, 100, 400, geometry.min_camera_x()]:
        wx = geometry.player_world_x(cx)
        # When wx is in range, going back gives the same cx.
        # When cx is clamped at min_camera_x, wx might land outside the
        # naive inverse range; only check the round-trip for in-range
        # cameras.
        if geometry.min_camera_x() <= cx <= geometry.max_camera_x():
            assert geometry.camera_x_for_world(wx) == cx
