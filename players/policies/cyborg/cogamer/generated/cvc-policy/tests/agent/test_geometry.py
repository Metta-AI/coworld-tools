"""Tests for cvc.agent.geometry."""

import pytest

from cvc_policy.agent.geometry import (
    direction_from_step,
    explore_offsets,
    format_position,
    greedy_step,
    manhattan,
    unstick_directions,
)

# --- manhattan ---


def test_manhattan_same_point():
    assert manhattan((0, 0), (0, 0)) == 0


def test_manhattan_horizontal():
    assert manhattan((1, 0), (4, 0)) == 3


def test_manhattan_vertical():
    assert manhattan((0, 2), (0, 7)) == 5


def test_manhattan_diagonal():
    assert manhattan((1, 1), (4, 5)) == 7


def test_manhattan_negative_coords():
    assert manhattan((-3, -2), (3, 2)) == 10


def test_manhattan_symmetric():
    assert manhattan((1, 2), (5, 8)) == manhattan((5, 8), (1, 2))


# --- direction_from_step ---


def test_direction_east():
    assert direction_from_step((3, 5), (4, 5)) == "east"


def test_direction_west():
    assert direction_from_step((3, 5), (2, 5)) == "west"


def test_direction_south():
    assert direction_from_step((3, 5), (3, 6)) == "south"


def test_direction_north():
    assert direction_from_step((3, 5), (3, 4)) == "north"


def test_direction_same_point_raises():
    with pytest.raises(ValueError, match="Non-adjacent"):
        direction_from_step((3, 5), (3, 5))


def test_direction_diagonal_returns_east():
    # dx is checked first, so (1,1) yields "east" not an error.
    assert direction_from_step((0, 0), (1, 1)) == "east"


def test_direction_far_away_raises():
    with pytest.raises(ValueError, match="Non-adjacent"):
        direction_from_step((0, 0), (2, 0))


def test_direction_priority_dx_checked_first():
    # If both dx and dy are non-zero and dx==1, east wins (dx checked first).
    assert direction_from_step((0, 0), (1, -1)) == "east"


# --- format_position ---


def test_format_position_basic():
    assert format_position((3, 7)) == "3,7"


def test_format_position_negative():
    assert format_position((-1, -2)) == "-1,-2"


def test_format_position_zero():
    assert format_position((0, 0)) == "0,0"


# --- greedy_step ---


def test_greedy_step_moves_toward_target():
    # Target is east; should step east.
    result = greedy_step((0, 0), (5, 0), set())
    assert result == (1, 0)


def test_greedy_step_moves_south():
    result = greedy_step((0, 0), (0, 5), set())
    assert result == (0, 1)


def test_greedy_step_avoids_blocked():
    # Direct east is blocked, should pick an alternative neighbor.
    result = greedy_step((0, 0), (5, 0), {(1, 0)})
    assert result is not None
    assert result != (1, 0)
    assert result in {(-1, 0), (0, 1), (0, -1)}


def test_greedy_step_all_blocked():
    blocked = {(1, 0), (-1, 0), (0, 1), (0, -1)}
    result = greedy_step((0, 0), (5, 5), blocked)
    assert result is None


def test_greedy_step_already_at_target():
    # All neighbors are equidistant from target (manhattan 1).
    result = greedy_step((5, 5), (5, 5), set())
    assert result is not None
    assert manhattan(result, (5, 5)) == 1


def test_greedy_step_partial_block():
    # Block 3 of 4 neighbors, only one remains.
    blocked = {(1, 0), (-1, 0), (0, -1)}
    result = greedy_step((0, 0), (5, 5), blocked)
    assert result == (0, 1)


# --- explore_offsets ---


def test_explore_offsets_miner():
    offsets = explore_offsets("miner")
    assert isinstance(offsets, tuple)
    assert len(offsets) == 4
    assert offsets[0] == (-28, -28)


def test_explore_offsets_scrambler():
    offsets = explore_offsets("scrambler")
    assert isinstance(offsets, tuple)
    assert len(offsets) == 4
    assert offsets[0] == (36, -36)


def test_explore_offsets_aligner():
    offsets = explore_offsets("aligner")
    assert isinstance(offsets, tuple)
    assert len(offsets) == 8


def test_explore_offsets_unknown_role_returns_aligner():
    # Any unrecognized role falls through to aligner offsets.
    assert explore_offsets("unknown") == explore_offsets("aligner")


# --- unstick_directions ---


def test_unstick_directions_returns_four_directions():
    dirs = unstick_directions(0, 0)
    assert len(dirs) == 4
    assert set(dirs) == {"north", "east", "south", "west"}


def test_unstick_directions_rotation():
    # (0+0)%4=0 -> first order, (1+0)%4=1 -> second order, etc.
    d0 = unstick_directions(0, 0)
    d1 = unstick_directions(1, 0)
    d2 = unstick_directions(2, 0)
    d3 = unstick_directions(3, 0)
    assert d0 == ("north", "east", "south", "west")
    assert d1 == ("east", "south", "west", "north")
    assert d2 == ("south", "west", "north", "east")
    assert d3 == ("west", "north", "east", "south")


def test_unstick_directions_wraps():
    # agent_id=3, step_index=1 -> (3+1)%4=0 -> same as (0,0)
    assert unstick_directions(3, 1) == unstick_directions(0, 0)


def test_unstick_directions_step_index_varies():
    # Incrementing step_index rotates the order.
    d0 = unstick_directions(0, 0)
    d1 = unstick_directions(0, 1)
    assert d0 != d1
    assert d0[0] == d1[3]  # north wraps around
