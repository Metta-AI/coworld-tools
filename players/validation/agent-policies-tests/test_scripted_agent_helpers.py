from __future__ import annotations

import pytest
from players.cogsguard.role.role_mix import (
    build_role_plan,
    default_role_counts,
    normalize_counts,
)
from players.cogsguard._shared.utils import move_toward


@pytest.mark.parametrize(
    ("current", "target", "expected"),
    [
        ((5, 5), (7, 5), "move_south"),
        ((5, 5), (3, 5), "move_north"),
        ((5, 5), (5, 7), "move_east"),
        ((5, 5), (5, 3), "move_west"),
        ((5, 5), (6, 5), "move_south"),
        ((5, 5), (5, 6), "move_east"),
        ((5, 5), (5, 5), "move_north"),
    ],
)
def test_move_toward_returns_expected_action(
    current: tuple[int, int],
    target: tuple[int, int],
    expected: str,
) -> None:
    assert move_toward(current, target).name == expected


def test_default_role_counts_matches_expected_mix() -> None:
    assert default_role_counts(1) == {"miner": 1}
    assert default_role_counts(3) == {"scrambler": 1, "miner": 1, "scout": 1}
    assert default_role_counts(8) == {
        "scrambler": 2,
        "aligner": 2,
        "miner": 3,
        "scout": 1,
    }


def test_normalize_counts_fills_and_trims_miners() -> None:
    assert normalize_counts(4, {"scrambler": 1, "aligner": 1}) == {
        "scrambler": 1,
        "aligner": 1,
        "miner": 2,
    }
    assert normalize_counts(3, {"miner": 4, "scout": 1}) == {
        "miner": 2,
        "scout": 1,
    }


def test_build_role_plan_uses_fixed_order_and_miner_padding() -> None:
    assert build_role_plan(5, {"aligner": 1, "scrambler": 2, "scout": 1}) == [
        "scrambler",
        "scrambler",
        "aligner",
        "scout",
        "miner",
    ]
