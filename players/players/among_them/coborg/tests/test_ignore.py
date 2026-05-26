"""Unit tests for :mod:`players.among_them.coborg.perception.ignore`.

Whole-fixture parity against the Nim oracle is covered by
``tests/test_perception_parity.py`` (via ``run_parity._check_ignore_phase_1_0``,
which compares a SHA-1 over the 16384-byte mask). This file covers
focused public-API behaviour: stamp geometry, clamping at screen
edges, idempotence under repeated stamps, and the high-level
``build_phase_1_0_ignore_mask`` entry.
"""

from __future__ import annotations

import numpy as np

from players.among_them.coborg.perception.data import RADAR_TASK_COLOR
from players.among_them.coborg.perception.frame import (
    SCREEN_HEIGHT,
    SCREEN_WIDTH,
)
from players.among_them.coborg.perception.ignore import (
    NAMEPLATE_HALF_WIDTH,
    NAMEPLATE_HEIGHT,
    PLAYER_IGNORE_RADIUS,
    PLAYER_SPRITE_ANCHOR_X,
    PLAYER_SPRITE_ANCHOR_Y,
    build_phase_1_0_ignore_mask,
    stamp_nameplate_rect,
    stamp_player_centre_zone,
    stamp_radar_pixels,
    stamp_sprite_rect,
)


def _empty_mask() -> np.ndarray:
    return np.zeros((SCREEN_HEIGHT, SCREEN_WIDTH), dtype=bool)


def _empty_frame() -> np.ndarray:
    return np.zeros((SCREEN_HEIGHT, SCREEN_WIDTH), dtype=np.uint8)


# --- public API: constants -----------------------------------------------


def test_player_anchor_constants_match_upstream_formula():
    assert PLAYER_IGNORE_RADIUS == 9
    assert PLAYER_SPRITE_ANCHOR_X == (SCREEN_WIDTH // 2) - 1   # 63
    assert PLAYER_SPRITE_ANCHOR_Y == (SCREEN_HEIGHT // 2) - 4  # 60


def test_nameplate_geometry_constants():
    assert NAMEPLATE_HEIGHT == 7
    assert NAMEPLATE_HALF_WIDTH == 40


# --- public API: stamp_player_centre_zone ---------------------------------


def test_player_centre_zone_is_19_square_at_anchor():
    mask = _empty_mask()
    stamp_player_centre_zone(mask)
    side = 2 * PLAYER_IGNORE_RADIUS + 1  # 19
    assert int(mask.sum()) == side * side  # 361
    # Inner stamp corners should all be True; outside the square False.
    assert mask[
        PLAYER_SPRITE_ANCHOR_Y - PLAYER_IGNORE_RADIUS,
        PLAYER_SPRITE_ANCHOR_X - PLAYER_IGNORE_RADIUS,
    ]
    assert mask[
        PLAYER_SPRITE_ANCHOR_Y + PLAYER_IGNORE_RADIUS,
        PLAYER_SPRITE_ANCHOR_X + PLAYER_IGNORE_RADIUS,
    ]
    assert not mask[
        PLAYER_SPRITE_ANCHOR_Y + PLAYER_IGNORE_RADIUS + 1,
        PLAYER_SPRITE_ANCHOR_X,
    ]
    assert not mask[
        PLAYER_SPRITE_ANCHOR_Y,
        PLAYER_SPRITE_ANCHOR_X - PLAYER_IGNORE_RADIUS - 1,
    ]


def test_player_centre_zone_is_idempotent():
    a = _empty_mask()
    stamp_player_centre_zone(a)
    b = a.copy()
    stamp_player_centre_zone(a)
    assert np.array_equal(a, b)


# --- public API: stamp_radar_pixels ---------------------------------------


def test_radar_pixels_stamps_every_yellow_pixel():
    frame = _empty_frame()
    frame[3, 10] = RADAR_TASK_COLOR
    frame[120, 120] = RADAR_TASK_COLOR
    mask = _empty_mask()
    stamp_radar_pixels(mask, frame)
    assert mask[3, 10] and mask[120, 120]
    assert int(mask.sum()) == 2


def test_radar_pixels_does_not_stamp_non_radar_palette():
    frame = _empty_frame()
    for c in [0, 1, 2, 3, 4, 5, 6, 7, 9, 10, 11, 12, 13, 14, 15]:
        frame[c, c] = c
    mask = _empty_mask()
    stamp_radar_pixels(mask, frame)
    assert int(mask.sum()) == 0


def test_radar_pixels_accumulates_with_other_stamps():
    """stamp_radar_pixels ORs into the existing mask; previously-stamped
    pixels stay True even if the frame pixel is non-radar."""
    frame = _empty_frame()
    frame[0, 0] = RADAR_TASK_COLOR
    mask = _empty_mask()
    mask[10, 10] = True  # pre-existing stamp
    stamp_radar_pixels(mask, frame)
    assert mask[10, 10]
    assert mask[0, 0]
    assert int(mask.sum()) == 2


# --- public API: stamp_sprite_rect ---------------------------------------


def test_sprite_rect_stamps_exact_rect():
    mask = _empty_mask()
    stamp_sprite_rect(mask, x=5, y=10, w=3, h=4)
    assert mask[10:14, 5:8].all()
    assert int(mask.sum()) == 12


def test_sprite_rect_clamps_to_screen():
    mask = _empty_mask()
    stamp_sprite_rect(mask, x=-2, y=-2, w=5, h=5)
    # Only the (0..2, 0..2) intersection lands on screen — 9 pixels.
    assert int(mask.sum()) == 9
    assert mask[:3, :3].all()


def test_sprite_rect_fully_offscreen_is_noop():
    mask = _empty_mask()
    stamp_sprite_rect(mask, x=200, y=200, w=10, h=10)
    assert int(mask.sum()) == 0
    stamp_sprite_rect(mask, x=-100, y=-100, w=10, h=10)
    assert int(mask.sum()) == 0


# --- public API: stamp_nameplate_rect ------------------------------------


def test_nameplate_above_sprite_ends_above_sprite_top():
    """The nameplate rect must end at sprite_y - 1; sprite_y itself
    isn't part of the nameplate (it's the sprite's top row)."""
    mask = _empty_mask()
    sprite_y = 40
    sprite_x = 60
    sprite_w = 12
    stamp_nameplate_rect(mask, sprite_x=sprite_x, sprite_y=sprite_y, sprite_w=sprite_w)
    # Nameplate covers rows (sprite_y - NAMEPLATE_HEIGHT) ... (sprite_y - 1).
    assert mask[sprite_y - 1, sprite_x + sprite_w // 2]
    assert not mask[sprite_y, sprite_x + sprite_w // 2]  # one row below = sprite itself
    assert mask[sprite_y - NAMEPLATE_HEIGHT, sprite_x + sprite_w // 2]


def test_nameplate_centred_on_sprite_centre():
    mask = _empty_mask()
    sprite_y = 30
    sprite_w = 12
    sprite_x = 60
    stamp_nameplate_rect(mask, sprite_x=sprite_x, sprite_y=sprite_y, sprite_w=sprite_w)
    cx = sprite_x + sprite_w // 2
    # Within NAMEPLATE_HALF_WIDTH of cx is stamped.
    assert mask[sprite_y - 3, cx - NAMEPLATE_HALF_WIDTH]
    assert mask[sprite_y - 3, cx + NAMEPLATE_HALF_WIDTH]
    # Just outside the half-width is not.
    assert not mask[sprite_y - 3, max(0, cx - NAMEPLATE_HALF_WIDTH - 1)]


def test_nameplate_near_top_of_screen_clamps():
    mask = _empty_mask()
    stamp_nameplate_rect(mask, sprite_x=60, sprite_y=2, sprite_w=12)
    # sprite_y = 2 means nameplate would extend up to -5; clamps to 0.
    # Rows 0..1 are stamped (rows 2..sprite_y-1 = nothing above 1 in-bounds).
    assert mask[0, 60 + 6]
    assert mask[1, 60 + 6]
    assert not mask[2, 60 + 6]  # sprite's own row


# --- public API: build_phase_1_0_ignore_mask -----------------------------


def test_phase_1_0_mask_includes_player_centre_zone_on_empty_frame():
    mask = build_phase_1_0_ignore_mask(_empty_frame())
    side = 2 * PLAYER_IGNORE_RADIUS + 1
    assert int(mask.sum()) == side * side
    assert mask[PLAYER_SPRITE_ANCHOR_Y, PLAYER_SPRITE_ANCHOR_X]


def test_phase_1_0_mask_picks_up_radar_pixels_in_addition_to_centre():
    frame = _empty_frame()
    frame[0, 0] = RADAR_TASK_COLOR
    frame[127, 127] = RADAR_TASK_COLOR
    mask = build_phase_1_0_ignore_mask(frame)
    side = 2 * PLAYER_IGNORE_RADIUS + 1
    assert int(mask.sum()) == side * side + 2
    assert mask[0, 0]
    assert mask[127, 127]


def test_phase_1_0_mask_returns_fresh_array_each_call():
    """The high-level entry must not return a cached mask — each call
    starts from a fresh zero array. A caller mutating the returned mask
    must not affect the next call."""
    a = build_phase_1_0_ignore_mask(_empty_frame())
    a[0, 0] = True
    b = build_phase_1_0_ignore_mask(_empty_frame())
    assert not b[0, 0]
