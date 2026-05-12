"""Real mettagrid rollout of the smoke scenario.

Excluded from default suite via the `scenario` marker (see
pyproject.toml). Run with: `pytest -m scenario`.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import cvc_policy.scenarios.cases.smoke  # noqa: F401 — registers scenario
from cvc_policy.scenarios import registry
from cvc_policy.scenarios.harness import run_scenario


@pytest.mark.scenario
@pytest.mark.timeout(120)
def test_smoke_machina1_runs_passes(tmp_path: Path) -> None:
    s = registry()["smoke_machina1_runs"]
    run = run_scenario(s, runs_root=tmp_path)
    assert run.result["status"] == "passed", run.result["assertions"]
