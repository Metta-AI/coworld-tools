from __future__ import annotations

from pathlib import Path

import pytest

import cogony_policy.scenarios.cases.mining_discovers_cap  # noqa: F401
from cogony_policy.scenarios import registry
from cogony_policy.scenarios.harness import run_scenario


@pytest.mark.scenario
@pytest.mark.timeout(120)
def test_mining_discovers_cap_passes(tmp_path: Path) -> None:
    s = registry()["mining_discovers_cap"]
    run = run_scenario(s, runs_root=tmp_path)
    assert run.result["status"] == "passed", run.result["assertions"]
