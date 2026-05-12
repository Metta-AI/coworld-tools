from __future__ import annotations

import pytest
from agent_policies.policies.scripted.cogsguard.scripted_agent.cogsguard.prereq_trace import (
    format_prereq_trace_line,
    prereq_missing,
)


def test_prereq_missing_align() -> None:
    missing = prereq_missing("align", gear=0, heart=1, influence=0)
    assert missing == {"gear": True, "heart": False}


def test_prereq_missing_scramble() -> None:
    missing = prereq_missing("scramble", gear=1, heart=0, influence=10)
    assert missing == {"gear": False, "heart": True}


def test_prereq_missing_invalid_action() -> None:
    with pytest.raises(ValueError, match="Unsupported action_type"):
        prereq_missing("mine", gear=1, heart=1, influence=1)


def test_format_prereq_trace_line() -> None:
    line = format_prereq_trace_line(
        step=7,
        agent_id=3,
        action_type="align",
        gear=1,
        heart=0,
        influence=0,
        missing={"gear": False, "heart": True},
    )
    assert line.startswith("step=7 agent=3 action=align")
    assert "gear=1 heart=0 influence=0" in line
    assert "missing[heart]" in line
