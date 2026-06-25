from __future__ import annotations

from pathlib import Path

import pytest

import cogony_policy.scenarios.cases.exploration_small  # noqa: F401 — registers
from cogony_policy.scenarios import registry
from cogony_policy.scenarios.harness import run_scenario


@pytest.mark.scenario
@pytest.mark.timeout(180)
def test_exploration_small_passes(tmp_path: Path) -> None:
    s = registry()["exploration_small"]
    run = run_scenario(s, runs_root=tmp_path)
    assert run.result["status"] == "passed", run.result["assertions"]
