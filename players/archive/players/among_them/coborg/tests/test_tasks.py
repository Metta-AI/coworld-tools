"""Unit tests for :mod:`players.among_them.coborg.perception.tasks`.

Whole-fixture parity for ``scan_radar_dots`` against the Nim oracle is
covered by ``tests/test_perception_parity.py`` (via ``run_parity``).
This file covers two distinct test surfaces:

1. **Public-API tests** — exercise the documented signatures of
   :func:`scan_radar_dots` and the stubbed :func:`scan_task_icons`.
   Hand-crafted frames for Chebyshev-1 dedup, periphery vs interior,
   wrong-shape frame handling, type defaults.

2. **White-box tests** — assert geometry properties of the
   ``_PERIPHERY_MASK`` precomputed at module import. The mask is an
   optimization specific to the current implementation; a rewrite that
   scans the periphery without precomputing a mask is expected to
   replace these tests as well. They earn their keep because the
   periphery geometry is a subtle invariant of the upstream algorithm
   (``isPeriphery`` with margin = 1 = two-pixel ring) and getting the
   off-by-one wrong silently breaks radar detection.

   Grouped under the ``# --- white-box ... ---`` header below.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from players.among_them.coborg.perception.frame import (
    SCREEN_HEIGHT,
    SCREEN_WIDTH,
)
from players.among_them.coborg.perception.tasks import (
    RADAR_PERIPHERY_MARGIN,
    RADAR_TASK_COLOR,
    IconMatch,
    RadarDotMatch,
    TaskPercept,
    _PERIPHERY_MASK,
    scan_radar_dots,
    scan_task_icons,
)

_FIXTURES_DIR = (
    Path(__file__).resolve().parent.parent.joinpath("perception/parity/fixtures")
)


# --- white-box: periphery mask shape --------------------------------------


def test_periphery_mask_is_two_pixel_border():
    """With ``RADAR_PERIPHERY_MARGIN = 1`` the ring is exactly two pixels
    deep on each edge — upstream `isPeriphery` checks
    ``x <= margin or x >= W-1-margin`` etc."""
    assert RADAR_PERIPHERY_MARGIN == 1
    band = RADAR_PERIPHERY_MARGIN + 1
    # Corner pixels and inner-edge pixels must all be True.
    assert _PERIPHERY_MASK[0, 0]
    assert _PERIPHERY_MASK[band - 1, 0]
    assert _PERIPHERY_MASK[0, band - 1]
    assert _PERIPHERY_MASK[SCREEN_HEIGHT - 1, SCREEN_WIDTH - 1]
    assert _PERIPHERY_MASK[SCREEN_HEIGHT - band, SCREEN_WIDTH - 1]
    # Anything strictly inside the ring must be False.
    assert not _PERIPHERY_MASK[band, band]
    assert not _PERIPHERY_MASK[SCREEN_HEIGHT - band - 1, SCREEN_WIDTH - band - 1]
    # The mask must be a closed ring — the inner rectangle is fully False.
    inner = _PERIPHERY_MASK[band : SCREEN_HEIGHT - band, band : SCREEN_WIDTH - band]
    assert not inner.any()


def test_periphery_mask_is_read_only():
    assert not _PERIPHERY_MASK.flags.writeable


# --- public API: scan_radar_dots ------------------------------------------


def _empty_frame() -> np.ndarray:
    return np.zeros((SCREEN_HEIGHT, SCREEN_WIDTH), dtype=np.uint8)


def test_scan_radar_dots_no_hits_returns_empty():
    assert scan_radar_dots(_empty_frame()) == []


def test_scan_radar_dots_single_corner_hit():
    frame = _empty_frame()
    frame[0, 0] = RADAR_TASK_COLOR
    assert scan_radar_dots(frame) == [RadarDotMatch(x=0, y=0)]


def test_scan_radar_dots_interior_yellow_is_ignored():
    """A yellow pixel inside the periphery ring isn't a radar dot — the
    radar layer only paints the screen edge."""
    frame = _empty_frame()
    frame[64, 64] = RADAR_TASK_COLOR
    assert scan_radar_dots(frame) == []


def test_scan_radar_dots_chebyshev_dedup_keeps_raster_first():
    """Two yellow pixels at Chebyshev distance 1 — the raster-order
    first one wins, the second is suppressed."""
    frame = _empty_frame()
    frame[0, 0] = RADAR_TASK_COLOR
    frame[0, 1] = RADAR_TASK_COLOR
    assert scan_radar_dots(frame) == [RadarDotMatch(x=0, y=0)]


def test_scan_radar_dots_far_apart_dots_all_kept():
    """Three dots, pairwise far apart on the periphery, all survive."""
    frame = _empty_frame()
    coords = [(0, 0), (0, SCREEN_WIDTH - 1), (SCREEN_HEIGHT - 1, 0)]
    for y, x in coords:
        frame[y, x] = RADAR_TASK_COLOR
    out = sorted((d.y, d.x) for d in scan_radar_dots(frame))
    assert out == sorted(coords)


def test_scan_radar_dots_diagonal_at_chebyshev_one_dedupes():
    frame = _empty_frame()
    frame[0, 0] = RADAR_TASK_COLOR
    frame[1, 1] = RADAR_TASK_COLOR  # Chebyshev distance = max(1, 1) = 1
    out = scan_radar_dots(frame)
    assert out == [RadarDotMatch(x=0, y=0)]


def test_scan_radar_dots_chain_dedup_against_first_only():
    """Three dots at x = 0, 2, 4 along the top row. The middle dot is
    within Chebyshev-1 of the first (dx=2 -> no, actually dx=2 > 1 so
    NOT within radius) — wait, distance 2 > 1, so the middle survives.
    Build the actual chain: x = 0, 1, 2."""
    frame = _empty_frame()
    frame[0, 0] = RADAR_TASK_COLOR
    frame[0, 1] = RADAR_TASK_COLOR
    frame[0, 2] = RADAR_TASK_COLOR
    # First (0, 0) kept. (0, 1) within radius -> dropped. (0, 2): distance
    # to (0, 0) is 2 > 1 -> kept.
    assert scan_radar_dots(frame) == [
        RadarDotMatch(x=0, y=0),
        RadarDotMatch(x=2, y=0),
    ]


def test_scan_radar_dots_rejects_wrong_shape_frame():
    bad = np.zeros((16, 16), dtype=np.uint8)
    with pytest.raises(ValueError, match="frame shape"):
        scan_radar_dots(bad)


def test_scan_radar_dots_smoke_on_fixture():
    """End-to-end smoke on a real fixture: the call returns a list of
    ``RadarDotMatch`` records. Concrete value parity is asserted by
    ``test_perception_parity``."""
    raw = (_FIXTURES_DIR / "gameplay_131.bin").read_bytes()
    frame = np.frombuffer(raw, dtype=np.uint8).reshape(SCREEN_HEIGHT, SCREEN_WIDTH)
    out = scan_radar_dots(frame)
    assert isinstance(out, list)
    for d in out:
        assert isinstance(d, RadarDotMatch)


# --- public API: types ----------------------------------------------------


def test_task_percept_defaults_empty_lists():
    p = TaskPercept()
    assert p.task_icons == []
    assert p.radar_dots == []


def test_icon_match_and_radar_dot_match_dataclasses():
    i = IconMatch(x=1, y=2)
    assert (i.x, i.y) == (1, 2)
    r = RadarDotMatch(x=3, y=4)
    assert (r.x, r.y) == (3, 4)


# --- public API: scan_task_icons -----------------------------------------


def _load_atlas():
    from players.among_them.coborg.perception.data import load_sprite_atlas
    return load_sprite_atlas()


def test_scan_task_icons_no_tasks_in_view_returns_empty():
    """A blank frame at a camera far from any task station yields no
    matches — the strict sprite match never clears on empty pixels."""
    frame = _empty_frame()
    # Camera at (0, 0) puts world (0,0) at screen (0,0). The Skeld map's
    # task stations are all at world coords >= 107, so an empty frame
    # produces no matches regardless of camera.
    out = scan_task_icons(_load_atlas(), frame, 0, 0)
    assert out == []


def test_scan_task_icons_returns_list_of_icon_match():
    """Smoke: the function returns the right type on a real fixture even
    when there are zero matches. Concrete value parity is in
    ``test_perception_parity``."""
    frame = np.frombuffer(
        (_FIXTURES_DIR / "gameplay_200.bin").read_bytes(), dtype=np.uint8
    ).reshape(SCREEN_HEIGHT, SCREEN_WIDTH)
    # Camera at the home position (where update_location locks for this fixture).
    out = scan_task_icons(_load_atlas(), frame, 504, 54)
    assert isinstance(out, list)
    for m in out:
        assert isinstance(m, IconMatch)


def test_scan_task_icons_fabricated_icon_matches():
    """Stamp the task icon sprite onto a blank frame at the exact expected
    screen position for one task station. The strict-match scan must find
    it. Choose the task station whose expected screen position falls in
    the middle of the frame for the (camera_x, camera_y) we use."""
    from players.among_them.coborg.perception.data import (
        ATLAS_TASK,
        SPRITE_SIZE,
        TRANSPARENT_INDEX,
        TASK_COORDS,
    )

    atlas = _load_atlas()
    sprite = atlas[ATLAS_TASK]

    # Pick the first task. Compute the camera that puts its expected
    # icon anchor near the centre of the screen.
    tx, ty, tw, _th = TASK_COORDS[0]
    # base_x = tx + tw//2 - SpriteSize//2 - cam_x => set cam_x so base_x = 58
    target_screen_x = 58
    target_screen_y = 58
    cam_x = tx + tw // 2 - SPRITE_SIZE // 2 - target_screen_x
    cam_y = ty - SPRITE_SIZE - 2 - target_screen_y

    frame = _empty_frame()
    # Stamp the sprite at the expected anchor, with TRANSPARENT_INDEX
    # left as palette 0 (frame is all 0; transparent sprite pixels are
    # not matched, so this is consistent with strict-match semantics).
    sh, sw = sprite.shape
    for sy in range(sh):
        for sx in range(sw):
            c = int(sprite[sy, sx])
            if c == TRANSPARENT_INDEX:
                continue
            frame[target_screen_y + sy, target_screen_x + sx] = c

    out = scan_task_icons(atlas, frame, cam_x, cam_y)
    # The probe sweeps 3 bobs × 7×7 anchors around each task. Only the
    # exact anchor (bob=0, dx=dy=0) should match cleanly; the dedup
    # collapses near-by matches within Chebyshev-1.
    assert len(out) >= 1
    # The first kept match must be at the exact stamped anchor.
    found = any(m.x == target_screen_x and m.y == target_screen_y for m in out)
    assert found, f"expected ({target_screen_x}, {target_screen_y}) in {out!r}"
