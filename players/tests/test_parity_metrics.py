from __future__ import annotations

from collections import Counter

from cogames_agents.policy.scripted_agent.cogsguard.parity_metrics import (
    diff_action_counts,
    move_success_rate,
    update_action_counts,
    update_move_stats,
)


def test_update_action_counts() -> None:
    counts: Counter[str] = Counter()
    update_action_counts(counts, "move_north")
    update_action_counts(counts, "move_north")
    update_action_counts(counts, "noop")
    assert counts["move_north"] == 2
    assert counts["noop"] == 1


def test_update_move_stats() -> None:
    move_stats = {"attempts": 0, "success": 0, "fail": 0}
    update_move_stats(move_stats, "noop", True)
    update_move_stats(move_stats, "move_north", True)
    update_move_stats(move_stats, "move_south", False)
    assert move_stats == {"attempts": 2, "success": 1, "fail": 1}
    assert move_success_rate(move_stats) == 0.5


def test_diff_action_counts() -> None:
    first = Counter({"move_north": 3, "noop": 1})
    second = Counter({"move_north": 1, "noop": 4})
    deltas = diff_action_counts(first, second, top_n=2)
    assert deltas[0] == ("noop", -3)
    assert deltas[1] == ("move_north", 2)
