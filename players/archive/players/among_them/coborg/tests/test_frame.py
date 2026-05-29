"""Tests for ``players.among_them.coborg.perception.frame``.

Covers:
- ``unpack4bpp`` happy path, malformed input.
- ``pack4bpp`` happy path, malformed input, round-trip with ``unpack4bpp``
  on synthetic data and on the 10 checked-in parity fixtures.
- ``black_pixel_count`` exact agreement with the numpy reference.
- ``pixel_at`` in-bounds + out-of-bounds.
- ``new_ignore_mask`` shape, dtype, all-zero.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from players.among_them.coborg.perception.frame import (
    FRAME_LEN,
    PACKED_FRAME_LEN,
    SCREEN_HEIGHT,
    SCREEN_WIDTH,
    black_pixel_count,
    new_ignore_mask,
    pack4bpp,
    pixel_at,
    unpack4bpp,
)

_FIXTURES_DIR = (
    Path(__file__).resolve().parent.parent
    / "perception" / "parity" / "fixtures"
)

_FIXTURE_BIN_NAMES = sorted(p.name for p in _FIXTURES_DIR.glob("*.bin"))


# --- constants --------------------------------------------------------------


def test_screen_constants_match_upstream() -> None:
    assert SCREEN_WIDTH == 128
    assert SCREEN_HEIGHT == 128
    assert FRAME_LEN == 16384
    assert PACKED_FRAME_LEN == 8192


# --- unpack4bpp -------------------------------------------------------------


def test_unpack4bpp_round_trip_zeros() -> None:
    packed = bytes(PACKED_FRAME_LEN)
    out = unpack4bpp(packed)
    assert out.shape == (SCREEN_HEIGHT, SCREEN_WIDTH)
    assert out.dtype == np.uint8
    assert int(out.sum()) == 0


def test_unpack4bpp_low_then_high_nybble_ordering() -> None:
    # One source byte 0xAB -> low nybble 0xB at pixel 0, high nybble 0xA at pixel 1.
    packed = bytes([0xAB]) + bytes(PACKED_FRAME_LEN - 1)
    out = unpack4bpp(packed).reshape(-1)
    assert int(out[0]) == 0x0B
    assert int(out[1]) == 0x0A
    assert int(out[2]) == 0


def test_unpack4bpp_random_round_trip() -> None:
    rng = np.random.default_rng(0xC0BB)
    packed_arr = rng.integers(0, 256, size=PACKED_FRAME_LEN, dtype=np.uint8)
    unpacked = unpack4bpp(packed_arr.tobytes())
    assert unpacked.shape == (SCREEN_HEIGHT, SCREEN_WIDTH)
    # Re-pack should reproduce the original byte string exactly.
    assert pack4bpp(unpacked) == packed_arr.tobytes()


def test_unpack4bpp_accepts_numpy_array_input() -> None:
    rng = np.random.default_rng(0xBEEF)
    packed_arr = rng.integers(0, 256, size=PACKED_FRAME_LEN, dtype=np.uint8)
    assert np.array_equal(unpack4bpp(packed_arr), unpack4bpp(packed_arr.tobytes()))


def test_unpack4bpp_rejects_wrong_length() -> None:
    with pytest.raises(ValueError, match="expected 8192 packed bytes"):
        unpack4bpp(bytes(100))
    with pytest.raises(ValueError, match="expected 8192 packed bytes"):
        unpack4bpp(bytes(PACKED_FRAME_LEN + 1))


# --- pack4bpp ---------------------------------------------------------------


def test_pack4bpp_rejects_wrong_length() -> None:
    with pytest.raises(ValueError, match="expected 16384 pixels"):
        pack4bpp(np.zeros(FRAME_LEN - 1, dtype=np.uint8))


def test_pack4bpp_masks_to_4_bits() -> None:
    # Values >15 should round-trip as their low-nibble equivalent.
    flat = np.zeros(FRAME_LEN, dtype=np.uint8)
    flat[0] = 0xF7  # low nibble 7
    flat[1] = 0x32  # low nibble 2
    packed = pack4bpp(flat)
    assert packed[0] == (2 << 4) | 7


# --- fixture round-trips ----------------------------------------------------


@pytest.mark.parametrize("fixture_name", _FIXTURE_BIN_NAMES)
def test_fixture_pack_unpack_round_trip(fixture_name: str) -> None:
    """Each fixture is an already-unpacked 16384-byte frame (per the upstream
    Nim test convention). pack -> unpack must reproduce the original bytes.
    """
    raw = (_FIXTURES_DIR / fixture_name).read_bytes()
    assert len(raw) == FRAME_LEN
    fixture_frame = np.frombuffer(raw, dtype=np.uint8).reshape(
        (SCREEN_HEIGHT, SCREEN_WIDTH)
    )
    packed = pack4bpp(fixture_frame)
    assert len(packed) == PACKED_FRAME_LEN
    round_trip = unpack4bpp(packed)
    assert np.array_equal(round_trip, fixture_frame)


def test_all_fixtures_have_valid_palette_indices() -> None:
    """Every byte in every fixture must be in [0, 15] - the PICO-8 palette
    range. If a fixture ever ships a byte outside that range, perception
    parity is meaningless and we should fail loudly.
    """
    for name in _FIXTURE_BIN_NAMES:
        raw = (_FIXTURES_DIR / name).read_bytes()
        arr = np.frombuffer(raw, dtype=np.uint8)
        assert int(arr.max()) <= 15, f"{name} contains palette index >15"


# --- black_pixel_count ------------------------------------------------------


def test_black_pixel_count_zero_frame() -> None:
    """An all-zero frame is all "black" (palette index 0)."""
    assert black_pixel_count(np.zeros((SCREEN_HEIGHT, SCREEN_WIDTH), dtype=np.uint8)) == FRAME_LEN


def test_black_pixel_count_agrees_with_numpy_reference() -> None:
    rng = np.random.default_rng(0xFEED)
    frame = rng.integers(0, 16, size=(SCREEN_HEIGHT, SCREEN_WIDTH), dtype=np.uint8)
    assert black_pixel_count(frame) == int(np.count_nonzero(frame == 0))


@pytest.mark.parametrize("fixture_name", _FIXTURE_BIN_NAMES)
def test_black_pixel_count_on_fixtures(fixture_name: str) -> None:
    """black_pixel_count is the seed of the interstitial detector - sanity
    check that interstitial fixtures have substantially more black pixels
    than gameplay fixtures (no exact threshold here; that's S4 territory).
    """
    raw = (_FIXTURES_DIR / fixture_name).read_bytes()
    frame = np.frombuffer(raw, dtype=np.uint8).reshape(
        (SCREEN_HEIGHT, SCREEN_WIDTH)
    )
    count = black_pixel_count(frame)
    assert 0 <= count <= FRAME_LEN
    if fixture_name.startswith("interstitial_"):
        # Loose lower bound: interstitial frames are mostly black.
        assert count > FRAME_LEN // 2, f"{fixture_name} not mostly-black: {count}"


# --- pixel_at ---------------------------------------------------------------


def test_pixel_at_in_bounds() -> None:
    frame = np.arange(FRAME_LEN, dtype=np.uint8).reshape(
        (SCREEN_HEIGHT, SCREEN_WIDTH)
    )
    # (0, 0) -> 0; (1, 0) -> SCREEN_WIDTH (y=1, x=0); (0, 5) -> 5 (y=0, x=5).
    assert pixel_at(frame, 0, 0) == 0
    assert pixel_at(frame, 0, 1) == SCREEN_WIDTH % 256
    assert pixel_at(frame, 5, 0) == 5


def test_pixel_at_out_of_bounds_returns_zero() -> None:
    frame = np.full((SCREEN_HEIGHT, SCREEN_WIDTH), 7, dtype=np.uint8)
    assert pixel_at(frame, -1, 0) == 0
    assert pixel_at(frame, 0, -1) == 0
    assert pixel_at(frame, SCREEN_WIDTH, 0) == 0
    assert pixel_at(frame, 0, SCREEN_HEIGHT) == 0
    assert pixel_at(frame, SCREEN_WIDTH + 1000, 0) == 0


# --- new_ignore_mask --------------------------------------------------------


def test_new_ignore_mask_shape_dtype_zero() -> None:
    mask = new_ignore_mask()
    assert mask.shape == (SCREEN_HEIGHT, SCREEN_WIDTH)
    assert mask.dtype == np.bool_
    assert not mask.any()


def test_new_ignore_mask_returns_independent_arrays() -> None:
    a = new_ignore_mask()
    b = new_ignore_mask()
    a[0, 0] = True
    assert not b[0, 0]
