"""Scenario tests for players.player_sdk.action_names.

Ported from the embedded smoke test of the original ``swgy_action.py``
(sm-policies scripted stack). The original's ``Action``-object checks are
rewritten as name asserts — the module is name-only now; wrapping the name
in an engine action object is the caller's one-liner.
"""

from __future__ import annotations

import pytest

from players.player_sdk.action_names import ActionTable


def check(label: str, cond: bool, detail: str = "") -> None:
    assert cond, f"FAIL {label}: {detail}"


def test_standard_vocabulary() -> None:
    # 1. Standard vocabulary: noop + four moves.
    t = ActionTable(["noop", "move_north", "move_south", "move_east", "move_west"])
    check("1 noop_name", t.noop_name == "noop")
    check("1b has", t.has("move_north") and not t.has("move_diagonal"))
    check("1c name_for", t.name_for("move_east") == "move_east")
    check("1d name_or_noop hit", t.name_or_noop("move_west") == "move_west")
    check("1e name_or_noop miss", t.name_or_noop("teleport") == "noop")
    check("1f move convenience hit", t.move_name_or_noop("south") == "move_south")
    check("1g move convenience miss", t.move_name_or_noop("up") == "noop")
    check("1j model index", t.name_at_index_or_noop(3) == "move_east")
    check("1k model index miss", t.name_at_index_or_noop(99) == "noop")
    check("1l negative model index miss", t.name_at_index_or_noop(-1) == "noop")


def test_permuted_vocabulary() -> None:
    # 2. Permuted vocabulary: noop is not at index 0.
    t = ActionTable(["move_north", "move_south", "noop", "move_east", "move_west"])
    check("2 noop_name permuted", t.noop_name == "noop")
    check("2b name_or_noop miss returns noop", t.name_or_noop("teleport") == "noop")
    check("2c move convenience hit", t.move_name_or_noop("east") == "move_east")
    check("2d model index respects permutation", t.name_at_index_or_noop(0) == "move_north")


def test_subset_vocabulary_degenerate_noop() -> None:
    # 3. Subset vocabulary: north/south only, no east/west, no noop.
    t = ActionTable(["move_north", "move_south"])
    check("3 degenerate noop_name falls to first action", t.noop_name == "move_north")
    check("3b move hit", t.move_name_or_noop("north") == "move_north")
    check("3c move miss returns degenerate fallback", t.move_name_or_noop("east") == "move_north")
    check("3d has detects subset", t.has("move_north") and not t.has("noop"))
    # name_for must still raise: caller might want to know.
    with pytest.raises(KeyError):
        t.name_for("noop")


def test_empty_vocabulary() -> None:
    # 4. Empty vocabulary: degenerate but doesn't crash.
    t = ActionTable([])
    check("4 empty noop_name", t.noop_name == "noop")
    check("4b empty has", not t.has("anything"))
    check("4c empty name_or_noop returns noop", t.name_or_noop("anything") == "noop")


def test_noop_only_vocabulary() -> None:
    # 5. Noop as the only action doesn't get treated as missing.
    t = ActionTable(["noop"])
    check("5 single-action vocab", t.noop_name == "noop" and t.name_or_noop("noop") == "noop")
    check("5b move miss returns noop", t.move_name_or_noop("north") == "noop")
