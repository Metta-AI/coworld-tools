from __future__ import annotations

import pytest
from cogames_agents.policy.scripted_agent.cogsguard.role_trace import (
    count_role_transitions,
    count_steps_with_roles,
    format_role_trace_line,
    summarize_role_counts,
)


def test_summarize_role_counts() -> None:
    history = [
        {"miner": 2, "aligner": 0},
        {"miner": 1, "aligner": 1},
        {"miner": 3, "aligner": 2},
    ]
    summary = summarize_role_counts(history, ["miner", "aligner"])
    assert summary["miner"]["min"] == 1
    assert summary["miner"]["max"] == 3
    assert summary["miner"]["avg"] == pytest.approx(2.0)
    assert summary["aligner"]["min"] == 0
    assert summary["aligner"]["max"] == 2
    assert summary["aligner"]["avg"] == pytest.approx(1.0)


def test_count_steps_with_roles() -> None:
    history = [
        {"miner": 1, "aligner": 0},
        {"miner": 1, "aligner": 1},
        {"miner": 0, "aligner": 2},
    ]
    assert count_steps_with_roles(history, ["miner", "aligner"]) == 1
    assert count_steps_with_roles(history, ["aligner"]) == 2


def test_count_role_transitions() -> None:
    transitions = [("miner", "aligner"), ("miner", "aligner"), ("aligner", "miner")]
    counts = count_role_transitions(transitions)
    assert counts == {("miner", "aligner"): 2, ("aligner", "miner"): 1}


def test_format_role_trace_line() -> None:
    line = format_role_trace_line(
        step=3,
        role_counts={"miner": 2, "aligner": 1, "scrambler": 0},
        roles=["miner", "aligner", "scrambler"],
        transitions=1,
    )
    assert line.startswith("step=3 roles[")
    assert "miner=2 aligner=1 scrambler=0" in line
    assert "present[miner,aligner]" in line
    assert line.endswith("transitions=1")
