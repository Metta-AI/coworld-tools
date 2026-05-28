"""Unit tests for :mod:`players.among_them.coborg.perception.localize`.

Whole-fixture parity against the Nim oracle on every fixture is covered
by ``tests/test_perception_parity.py`` (via ``run_parity``). This file
focuses on:

- public-API shape: dataclass defaults, enum values;
- ``score_camera`` semantics on synthetic frames;
- ``hash_frame_patches`` determinism + structural properties;
- ``get_patch_index`` cache behaviour;
- ``update_location`` prev-state threading.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from players.among_them.coborg.perception.data import load_map_pixels
from players.among_them.coborg.perception.frame import SCREEN_HEIGHT, SCREEN_WIDTH
from players.among_them.coborg.perception.ignore import build_phase_1_0_ignore_mask
from players.among_them.coborg.perception.localize import (
    CameraLock,
    CameraScore,
    Candidate,
    FRAME_FIT_MIN_COMPARED,
    FULL_FRAME_FIT_MAX_ERRORS,
    LOCAL_FRAME_FIT_MAX_ERRORS,
    LOCAL_FRAME_SEARCH_RADIUS,
    LocalizerState,
    PATCH_GRID_H,
    PATCH_GRID_W,
    PATCH_HASH_BASE,
    PATCH_HASH_SEED,
    PATCH_SIZE,
    PATCH_TOTAL_COUNT,
    SPIRAL_MAX_RADIUS,
    get_patch_index,
    hash_frame_patches,
    reseed_camera_at_home,
    score_camera,
    update_location,
)

_FIXTURES_DIR = (
    Path(__file__).resolve().parent.parent / "perception/parity/fixtures"
)


def _load_fixture_frame(name: str) -> np.ndarray:
    raw = (_FIXTURES_DIR / f"{name}.bin").read_bytes()
    return np.frombuffer(raw, dtype=np.uint8).reshape(SCREEN_HEIGHT, SCREEN_WIDTH)


# --- constants pin -------------------------------------------------------


def test_localize_constants_match_upstream():
    assert FULL_FRAME_FIT_MAX_ERRORS == 420
    assert LOCAL_FRAME_FIT_MAX_ERRORS == 320
    assert FRAME_FIT_MIN_COMPARED == 12000
    assert LOCAL_FRAME_SEARCH_RADIUS == 8
    assert SPIRAL_MAX_RADIUS == 48
    assert PATCH_SIZE == 8
    assert PATCH_GRID_W == 16
    assert PATCH_GRID_H == 16
    assert PATCH_TOTAL_COUNT == 256
    assert int(PATCH_HASH_BASE) == 16777619
    assert int(PATCH_HASH_SEED) == 0xCBF29CE484222325


# --- LocalizerState / CameraLock / CameraScore ---------------------------


def test_localizer_state_defaults():
    s = LocalizerState()
    assert s.camera_x == 0 and s.camera_y == 0
    assert s.camera_score == 0
    assert s.camera_lock is CameraLock.NO_LOCK
    assert s.localized is False
    assert s.last_localized_tick == -1
    assert s.last_camera_x == 0 and s.last_camera_y == 0
    assert s.home_set is False
    assert s.game_started is False
    assert s.self_x == 0 and s.self_y == 0


def test_camera_lock_enum_string_values_match_oracle():
    """Oracle dumper emits these strings; mismatches would break every
    fixture's localize_first_frame check."""
    assert CameraLock.NO_LOCK.value == "no_lock"
    assert CameraLock.LOCAL_FRAME_MAP_LOCK.value == "local_frame_map_lock"
    assert CameraLock.FRAME_MAP_LOCK.value == "frame_map_lock"


# --- score_camera --------------------------------------------------------


def test_score_camera_at_pathological_camera_returns_all_void_slice():
    """A camera offset so far out of range that even the padded map
    doesn't cover the slice gets an all-MAP_VOID_COLOR=12 fallback.
    With a frame of palette 7 (which neither equals 12 nor shadow-maps
    to it: SHADOW_MAP[12]=0), every considered pixel is an error."""
    map_pixels = load_map_pixels()
    frame = np.full((SCREEN_HEIGHT, SCREEN_WIDTH), 7, dtype=np.uint8)
    mask = np.zeros_like(frame, dtype=bool)
    sc = score_camera(frame, map_pixels, mask, -10_000, -10_000, FULL_FRAME_FIT_MAX_ERRORS)
    assert sc.compared == SCREEN_HEIGHT * SCREEN_WIDTH
    assert sc.errors == SCREEN_HEIGHT * SCREEN_WIDTH
    # Over budget -> score == -errors.
    assert sc.score == -sc.errors


def test_score_camera_with_full_ignore_mask_compares_nothing():
    """Every pixel ignored -> compared=0, errors=0 (no opportunity to
    miss), score=0 (in-budget formula yields 0 - 0*128)."""
    map_pixels = load_map_pixels()
    frame = np.zeros((SCREEN_HEIGHT, SCREEN_WIDTH), dtype=np.uint8)
    mask = np.ones_like(frame, dtype=bool)
    sc = score_camera(frame, map_pixels, mask, 0, 0, FULL_FRAME_FIT_MAX_ERRORS)
    assert sc.compared == 0
    assert sc.errors == 0
    assert sc.score == 0


def test_score_camera_returns_dataclass():
    sc = score_camera(
        np.zeros((SCREEN_HEIGHT, SCREEN_WIDTH), dtype=np.uint8),
        load_map_pixels(),
        np.zeros((SCREEN_HEIGHT, SCREEN_WIDTH), dtype=bool),
        0, 0, FULL_FRAME_FIT_MAX_ERRORS,
    )
    assert isinstance(sc, CameraScore)


# --- hash_frame_patches --------------------------------------------------


def test_hash_frame_patches_shape_and_dtype():
    frame = np.zeros((SCREEN_HEIGHT, SCREEN_WIDTH), dtype=np.uint8)
    mask = np.zeros_like(frame, dtype=bool)
    hashes, valid = hash_frame_patches(frame, mask)
    assert hashes.shape == (PATCH_TOTAL_COUNT,)
    assert hashes.dtype == np.uint64
    assert valid.shape == (PATCH_TOTAL_COUNT,)
    assert valid.dtype == bool


def test_hash_frame_patches_uniform_frame_yields_uniform_hashes():
    """A constant-palette frame produces 256 identical hashes (every
    patch is the same 64 pixels)."""
    frame = np.full((SCREEN_HEIGHT, SCREEN_WIDTH), 7, dtype=np.uint8)
    mask = np.zeros_like(frame, dtype=bool)
    hashes, valid = hash_frame_patches(frame, mask)
    assert (hashes == hashes[0]).all()
    assert valid.all()


def test_hash_frame_patches_ignored_pixel_invalidates_one_patch():
    frame = np.zeros((SCREEN_HEIGHT, SCREEN_WIDTH), dtype=np.uint8)
    mask = np.zeros_like(frame, dtype=bool)
    # Mark a single pixel in patch (0, 0).
    mask[0, 0] = True
    hashes, valid = hash_frame_patches(frame, mask)
    assert not valid[0]            # patch (0, 0)
    assert valid[1:].all()         # everything else still valid


def test_hash_frame_patches_deterministic():
    frame = _load_fixture_frame("gameplay_200")
    mask = build_phase_1_0_ignore_mask(frame)
    h1, v1 = hash_frame_patches(frame, mask)
    h2, v2 = hash_frame_patches(frame, mask)
    assert np.array_equal(h1, h2)
    assert np.array_equal(v1, v2)


# --- patch index ---------------------------------------------------------


def test_patch_index_is_sorted_and_cached():
    idx1 = get_patch_index()
    assert (idx1.hashes[:-1] <= idx1.hashes[1:]).all()
    assert idx1.hashes.dtype == np.uint64
    assert idx1.cam_xs.dtype == np.int32
    assert idx1.cam_ys.dtype == np.int32
    assert len(idx1.hashes) == idx1.width * idx1.height
    # lru_cache returns the same object each call.
    idx2 = get_patch_index()
    assert idx1 is idx2


# --- update_location -----------------------------------------------------


def test_update_location_from_fresh_state_does_not_mutate_input():
    """``prev_state=None`` builds a fresh state; passing a prior state
    must not mutate it (the caller still owns the original reference)."""
    frame = _load_fixture_frame("gameplay_200")
    mask = build_phase_1_0_ignore_mask(frame)
    prev = LocalizerState(camera_x=42, camera_y=43, localized=True)
    snapshot = (prev.camera_x, prev.camera_y, prev.localized)
    update_location(prev, frame, mask, tick=0)
    assert (prev.camera_x, prev.camera_y, prev.localized) == snapshot


def test_update_location_threads_prev_camera_into_last_camera():
    """`last_camera_x/y` should always be set to the prior frame's
    camera, regardless of whether localization succeeded this tick."""
    frame = _load_fixture_frame("gameplay_200")
    mask = build_phase_1_0_ignore_mask(frame)
    prev = LocalizerState(camera_x=123, camera_y=456)
    new = update_location(prev, frame, mask, tick=7)
    assert new.last_camera_x == 123
    assert new.last_camera_y == 456


def test_update_location_on_gameplay_fixture_locks():
    """gameplay_200 is one of the fixtures the parity oracle expects to
    localize successfully — confirm the Python orchestrator agrees."""
    frame = _load_fixture_frame("gameplay_200")
    mask = build_phase_1_0_ignore_mask(frame)
    state = update_location(None, frame, mask, tick=0)
    assert state.localized
    assert state.camera_lock is not CameraLock.NO_LOCK
    assert state.home_set
    # self_x / self_y derived from the locked camera.
    assert state.self_x != 0 or state.self_y != 0


def test_update_location_on_interstitial_fixture_does_not_lock():
    """Black-screen interstitials have nothing to match; the orchestrator
    should report ``localized=False`` (callers gate at the
    ``detect_interstitial`` step in production but the localizer must
    handle the case anyway)."""
    frame = _load_fixture_frame("interstitial_0")
    mask = build_phase_1_0_ignore_mask(frame)
    state = update_location(None, frame, mask, tick=0)
    assert not state.localized
    assert state.camera_lock is CameraLock.NO_LOCK


# --- reseed_camera_at_home ----------------------------------------------


def test_reseed_uses_button_when_home_not_set():
    from players.among_them.coborg.perception.geometry import (
        button_camera_x,
        button_camera_y,
    )

    state = LocalizerState()
    new = reseed_camera_at_home(state)
    assert new.camera_x == button_camera_x()
    assert new.camera_y == button_camera_y()
    assert new.camera_lock is CameraLock.NO_LOCK
    assert not new.localized


def test_reseed_uses_home_when_set():
    from players.among_them.coborg.perception.geometry import (
        camera_x_for_world,
        camera_y_for_world,
    )

    state = LocalizerState(home_x=500, home_y=200, home_set=True)
    new = reseed_camera_at_home(state)
    assert new.camera_x == camera_x_for_world(500)
    assert new.camera_y == camera_y_for_world(200)


# --- Candidate dataclass ------------------------------------------------


def test_candidate_dataclass():
    c = Candidate(cx=10, cy=20, votes=5)
    assert (c.cx, c.cy, c.votes) == (10, 20, 5)
