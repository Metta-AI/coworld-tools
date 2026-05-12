from __future__ import annotations

from pathlib import Path

from cogames_rl_researcher.coverage import (
    CoverageVariant,
    run_submit_coverage_pack,
    write_submit_coverage_pack,
)
from cogames_rl_researcher.json_io import read_json
from cogames_rl_researcher.startup import StartupConfig

from tests.test_startup import _write_fake_cogames


def test_submit_coverage_pack_runs_all_variants(tmp_path: Path, monkeypatch) -> None:
    fake_cogames = tmp_path / "fake_cogames.py"
    _write_fake_cogames(fake_cogames)

    state_path = tmp_path / "state.json"
    monkeypatch.setenv("FAKE_COGAMES_STATE", str(state_path))

    summary = run_submit_coverage_pack(
        base_config=StartupConfig(
            policy="metta://policy/role_py",
            policy_name="unused-base-name",
            season="beta-cogsguard",
            mission="arena",
            episodes=1,
            steps=50,
            output_root=tmp_path / "artifacts",
            cogames_bin=str(fake_cogames),
            detect_idle_seconds=10,
            max_step_seconds=30,
            run_leaderboard=False,
        ),
        variants=[
            CoverageVariant(variant_id="v1", policy_name="test-policy-v1"),
            CoverageVariant(variant_id="v2", policy_name="test-policy-v2", seed=99),
        ],
    )

    assert summary.attempted_variants == 2
    assert summary.successful_submits == 2
    assert summary.valid_submit_coverage_ratio == 1.0
    assert summary.attempted_experiment_families == 1
    assert summary.experiment_family_breadth == 1
    assert summary.experiment_family_breadth_ratio == 1.0
    assert len(summary.results) == 2
    assert all(result.status == "success" for result in summary.results)
    assert all(Path(result.run_dir).exists() for result in summary.results)

    state = read_json(state_path)
    assert state["submit_count"] == 2
    assert state["upload_count"] == 4


def test_submit_coverage_pack_writes_summary_artifact(tmp_path: Path, monkeypatch) -> None:
    fake_cogames = tmp_path / "fake_cogames.py"
    _write_fake_cogames(fake_cogames)

    state_path = tmp_path / "state.json"
    monkeypatch.setenv("FAKE_COGAMES_STATE", str(state_path))

    output_path = tmp_path / "coverage_pack.json"
    summary = write_submit_coverage_pack(
        base_config=StartupConfig(
            policy="metta://policy/role_py",
            policy_name="unused-base-name",
            season="beta-cogsguard",
            mission="arena",
            episodes=1,
            steps=50,
            output_root=tmp_path / "artifacts",
            cogames_bin=str(fake_cogames),
            detect_idle_seconds=10,
            max_step_seconds=30,
            run_leaderboard=False,
        ),
        variants=[CoverageVariant(variant_id="v1", policy_name="test-policy-v1")],
        output_path=output_path,
    )

    assert output_path.exists()
    payload = read_json(output_path)
    assert payload["attempted_variants"] == 1
    assert payload["successful_submits"] == 1
    assert payload["attempted_experiment_families"] == 1
    assert payload["experiment_family_breadth"] == 1
    assert payload["experiment_family_breadth_ratio"] == 1.0
    assert payload["results"][0]["variant_id"] == "v1"
    assert summary.attempted_variants == 1
