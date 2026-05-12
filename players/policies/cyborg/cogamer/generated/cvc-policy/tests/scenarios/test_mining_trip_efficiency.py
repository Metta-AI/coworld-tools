from __future__ import annotations

from pathlib import Path

import pytest

import cvc_policy.scenarios.cases.mining_trip_efficiency  # noqa: F401
from cvc_policy.scenarios import registry
from cvc_policy.scenarios.harness import run_scenario


@pytest.mark.scenario
@pytest.mark.timeout(180)
def test_mining_trip_efficiency_passes(tmp_path: Path) -> None:
    s = registry()["mining_trip_efficiency"]
    run = run_scenario(s, runs_root=tmp_path)
    assert run.result["status"] == "passed", run.result["assertions"]
