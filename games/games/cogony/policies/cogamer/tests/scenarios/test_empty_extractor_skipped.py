from __future__ import annotations

from pathlib import Path

import pytest

import cogony_policy.scenarios.cases.empty_extractor_skipped  # noqa: F401
from cogony_policy.scenarios import registry
from cogony_policy.scenarios.harness import run_scenario


@pytest.mark.scenario
@pytest.mark.timeout(180)
def test_empty_extractor_skipped_passes(tmp_path: Path) -> None:
    s = registry()["empty_extractor_skipped"]
    run = run_scenario(s, runs_root=tmp_path)
    assert run.result["status"] == "passed", run.result["assertions"]
