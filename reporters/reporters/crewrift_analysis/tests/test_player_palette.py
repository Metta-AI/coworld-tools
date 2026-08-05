"""Tests for the CrewRift player palette."""

from __future__ import annotations

import pytest

from crewrift_analysis.palette import (
    PLAYER_COLOR_NAMES,
    PLAYER_COLORS,
    ROLE_COLORS,
    lifted_player_color,
    player_color,
)
from episode_analysis.palette import NEGATIVE, PRIMARY, lift


def test_sixteen_engine_colors_in_engine_order():
    assert len(PLAYER_COLORS) == 16
    assert PLAYER_COLOR_NAMES[:4] == ("red", "blue", "green", "pink")
    assert PLAYER_COLOR_NAMES[-1] == "gray"
    assert PLAYER_COLORS["red"] == "#c51111"
    assert PLAYER_COLORS["gray"] == "#282a30"
    # The spec-of-legend white/black entries do not exist in the engine.
    assert "white" not in PLAYER_COLORS and "black" not in PLAYER_COLORS


def test_player_color_lookup():
    assert player_color("navy") == "#1b2148"
    with pytest.raises(ValueError, match="red"):
        player_color("chartreuse")


def test_lifted_player_color_delegates_to_lift():
    assert lifted_player_color("navy") == lift(PLAYER_COLORS["navy"])
    assert lifted_player_color("navy") != PLAYER_COLORS["navy"]
    assert lifted_player_color("navy", 0.0) == PLAYER_COLORS["navy"]


def test_role_colors_reuse_house_semantics():
    assert ROLE_COLORS == {"imposter": NEGATIVE, "crew": PRIMARY}
