"""Unit tests for :mod:`players.among_them.coborg.perception.interstitial`.

Whole-fixture parity against the Nim oracle is covered by
``tests/test_perception_parity.py`` (via ``run_parity``). This file
covers focused threshold-boundary cases and dataclass shape.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from players.among_them.coborg.perception.frame import (
    FRAME_LEN,
    SCREEN_HEIGHT,
    SCREEN_WIDTH,
)
from players.among_them.coborg.perception.interstitial import (
    INTERSTITIAL_BLACK_PERCENT,
    INTERSTITIAL_BLACK_THRESHOLD,
    InterstitialKind,
    InterstitialObservation,
    detect_interstitial,
)

_FIXTURES_DIR = (
    Path(__file__).resolve().parent.parent / "perception/parity/fixtures"
)


# --- public API: constants -----------------------------------------------


def test_threshold_matches_upstream_ceiling_formula():
    """The upstream Nim uses ``(percent * FrameLen + 99) div 100`` so the
    rounded threshold is conservative (an exactly-30%-black fixture
    *is* classified as interstitial, not borderline-skipped)."""
    assert INTERSTITIAL_BLACK_PERCENT == 30
    expected = (INTERSTITIAL_BLACK_PERCENT * FRAME_LEN + 99) // 100
    assert INTERSTITIAL_BLACK_THRESHOLD == expected
    # Sanity: with FRAME_LEN = 128*128 = 16384, threshold = 4916.
    assert INTERSTITIAL_BLACK_THRESHOLD == 4916


# --- public API: detect_interstitial -------------------------------------


def _black_frame_with_count(black_count: int) -> np.ndarray:
    """Return a frame with exactly ``black_count`` palette-0 pixels and
    the rest filled with the MapVoidColor sentinel (12). Used to drive
    the threshold from both sides."""
    frame = np.full((SCREEN_HEIGHT, SCREEN_WIDTH), 12, dtype=np.uint8)
    flat = frame.reshape(-1)
    flat[:black_count] = 0
    return frame


def test_all_white_frame_is_gameplay():
    frame = np.full((SCREEN_HEIGHT, SCREEN_WIDTH), 7, dtype=np.uint8)
    obs = detect_interstitial(frame)
    assert obs.is_interstitial is False
    assert obs.kind is InterstitialKind.NOT_INTERSTITIAL
    assert obs.black_pixel_count == 0


def test_all_black_frame_is_interstitial():
    frame = np.zeros((SCREEN_HEIGHT, SCREEN_WIDTH), dtype=np.uint8)
    obs = detect_interstitial(frame)
    assert obs.is_interstitial is True
    assert obs.kind is InterstitialKind.UNKNOWN
    assert obs.black_pixel_count == FRAME_LEN


def test_exactly_at_threshold_is_interstitial():
    """Threshold is inclusive: ``count >= threshold`` triggers."""
    frame = _black_frame_with_count(INTERSTITIAL_BLACK_THRESHOLD)
    obs = detect_interstitial(frame)
    assert obs.is_interstitial is True
    assert obs.kind is InterstitialKind.UNKNOWN
    assert obs.black_pixel_count == INTERSTITIAL_BLACK_THRESHOLD


def test_one_below_threshold_is_gameplay():
    frame = _black_frame_with_count(INTERSTITIAL_BLACK_THRESHOLD - 1)
    obs = detect_interstitial(frame)
    assert obs.is_interstitial is False
    assert obs.kind is InterstitialKind.NOT_INTERSTITIAL
    assert obs.black_pixel_count == INTERSTITIAL_BLACK_THRESHOLD - 1


def test_map_void_pixels_do_not_count_as_black():
    """Gameplay frames pad off-map with MapVoidColor (palette 12), not
    black. The detector must not confuse those with interstitial
    pixels."""
    frame = np.full((SCREEN_HEIGHT, SCREEN_WIDTH), 12, dtype=np.uint8)
    obs = detect_interstitial(frame)
    assert obs.is_interstitial is False
    assert obs.black_pixel_count == 0


def test_detect_returns_dataclass_with_documented_shape():
    obs = detect_interstitial(np.zeros((SCREEN_HEIGHT, SCREEN_WIDTH), dtype=np.uint8))
    assert isinstance(obs, InterstitialObservation)
    # Confirm the three fields the parity rig and downstream belief
    # layer read.
    assert hasattr(obs, "is_interstitial")
    assert hasattr(obs, "kind")
    assert hasattr(obs, "black_pixel_count")
    assert isinstance(obs.kind, InterstitialKind)


# --- public API: enum string values --------------------------------------


def test_kind_string_values_match_oracle_serialisation():
    """The Nim oracle dumper emits these strings; the parity rig
    compares ``obs.kind.value == sidecar['kind']``. Any divergence
    breaks all fixtures, so pin the values explicitly."""
    assert InterstitialKind.NOT_INTERSTITIAL.value == "not_interstitial"
    assert InterstitialKind.UNKNOWN.value == "unknown"
    assert InterstitialKind.ROLE_REVEAL.value == "role_reveal"
    assert InterstitialKind.ROLE_REVEAL_CREWMATE.value == "role_reveal_crewmate"
    assert InterstitialKind.ROLE_REVEAL_IMPOSTER.value == "role_reveal_imposter"
    assert InterstitialKind.VOTING.value == "voting"
    assert InterstitialKind.VOTE_RESULT.value == "vote_result"
    assert InterstitialKind.GAME_OVER.value == "game_over"


# --- public API: smoke on real fixtures -----------------------------------


@pytest.mark.parametrize(
    "fixture_name,expected_is_interstitial",
    [
        # The fixture names already carry the ground-truth label;
        # smoke-check the classification matches expectations and the
        # `kind` field is consistent.
        ("gameplay_131", False),
        ("gameplay_150", False),
        ("gameplay_200", False),
        ("gameplay_274", False),
        ("interstitial_0", True),
        ("interstitial_5", True),
        ("interstitial_100", True),
        ("voting_real_1432", True),
        ("voting_real_1500", True),
        ("gameover_crew_wins_real", True),
    ],
)
def test_smoke_on_fixture(fixture_name: str, expected_is_interstitial: bool):
    raw = (_FIXTURES_DIR / f"{fixture_name}.bin").read_bytes()
    frame = np.frombuffer(raw, dtype=np.uint8).reshape(SCREEN_HEIGHT, SCREEN_WIDTH)
    obs = detect_interstitial(frame)
    assert obs.is_interstitial is expected_is_interstitial, (
        f"{fixture_name}: expected is_interstitial={expected_is_interstitial}, "
        f"got {obs}"
    )
    if expected_is_interstitial:
        assert obs.kind is InterstitialKind.UNKNOWN  # OCR subtypes are S4.5+
    else:
        assert obs.kind is InterstitialKind.NOT_INTERSTITIAL
