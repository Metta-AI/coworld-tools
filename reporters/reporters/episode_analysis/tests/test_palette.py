"""Tests for the matplotlib-free parts of the palette module."""

from __future__ import annotations

import pytest

from episode_analysis.palette import lift


def test_lift_black_by_default_amount():
    assert lift("#000000") == "#575757"  # 0.34 * 255 rounds to 87 = 0x57


def test_lift_white_is_fixed_point():
    assert lift("#ffffff", 0.9) == "#ffffff"


def test_lift_zero_amount_is_identity():
    assert lift("#c51111", 0.0) == "#c51111"


def test_lift_accepts_bare_hex():
    assert lift("c51111") == lift("#c51111")


def test_lift_preserves_channel_ordering():
    # Red's dominant channel stays dominant: hue preserved, not substituted.
    lifted = lift("#c51111")
    assert lifted == "#d96262"
    r, g, b = (int(lifted[i : i + 2], 16) for i in (1, 3, 5))
    assert r > g == b


@pytest.mark.parametrize("bad", ["#12", "#12345", "zzzzzz", ""])
def test_lift_rejects_malformed_hex(bad):
    with pytest.raises(ValueError):
        lift(bad)


def test_lift_rejects_out_of_range_amount():
    with pytest.raises(ValueError):
        lift("#000000", 1.5)
    with pytest.raises(ValueError):
        lift("#000000", -0.1)
