from __future__ import annotations

from pathlib import Path

from cogames_rl_researcher.json_io import read_json
from cogames_rl_researcher.research_command import ResearchCommandConfig, run_research_command

from tests.test_startup import _write_fake_cogames


def test_research_command_runs_startup_and_resume_when_skip_train(tmp_path: Path, monkeypatch) -> None:
    fake_cogames = tmp_path / "fake_cogames.py"
    _write_fake_cogames(fake_cogames)

    state_path = tmp_path / "state.json"
    monkeypatch.setenv("FAKE_COGAMES_STATE", str(state_path))

    summary = run_research_command(
        ResearchCommandConfig(
            policy="metta://policy/role_py",
            policy_name="test-policy",
            season="beta-cogsguard",
            mission="arena",
            episodes=1,
            steps=50,
            output_root=tmp_path / "artifacts",
            cogames_bin=str(fake_cogames),
            detect_idle_seconds=10,
            max_step_seconds=30,
            skip_train=True,
            run_resume=True,
        )
    )

    assert summary.overall_status == "success"
    assert summary.startup_status == "success"
    assert summary.resume_status == "success"
    assert summary.next_actions_count > 0

    summary_path = Path(summary.research_run_dir) / "research_command_summary.json"
    assert summary_path.exists()

    state = read_json(state_path)
    assert state["upload_count"] >= 2
    assert state["submit_count"] >= 1


def test_research_command_stops_when_train_fails(tmp_path: Path) -> None:
    summary = run_research_command(
        ResearchCommandConfig(
            policy="metta://policy/role_py",
            policy_name="test-policy",
            output_root=tmp_path / "artifacts",
            train_command="false",
            skip_train=False,
            run_resume=False,
        )
    )

    assert summary.train.status == "failed"
    assert summary.startup_status == "skipped"
    assert summary.resume_status == "skipped"
    assert summary.overall_status == "failed"


def test_research_command_timeout_marks_train_failed_instead_of_raising(tmp_path: Path) -> None:
    summary = run_research_command(
        ResearchCommandConfig(
            policy="metta://policy/role_py",
            policy_name="test-policy",
            output_root=tmp_path / "artifacts",
            train_command="sleep 2",
            skip_train=False,
            train_timeout_seconds=1,
            run_resume=False,
        )
    )

    assert summary.train.status == "failed"
    assert summary.train.return_code is None
    assert summary.startup_status == "skipped"
    assert summary.overall_status == "failed"


def test_research_command_fails_when_startup_fails(tmp_path: Path, monkeypatch) -> None:
    fake_cogames = tmp_path / "fake_cogames.py"
    _write_fake_cogames(fake_cogames)

    state_path = tmp_path / "state.json"
    monkeypatch.setenv("FAKE_COGAMES_STATE", str(state_path))
    monkeypatch.setenv("FAKE_AUTH_FAIL_ONCE", "1")

    summary = run_research_command(
        ResearchCommandConfig(
            policy="metta://policy/role_py",
            policy_name="test-policy",
            season="beta-cogsguard",
            mission="arena",
            episodes=1,
            steps=50,
            output_root=tmp_path / "artifacts",
            cogames_bin=str(fake_cogames),
            detect_idle_seconds=10,
            max_step_seconds=30,
            max_recoveries=0,
            skip_train=True,
            run_resume=True,
        )
    )

    assert summary.startup_status == "failed"
    assert summary.resume_status == "skipped"
    assert summary.overall_status == "failed"


def test_research_command_enforce_gates_fails_on_startup_gate_failure(tmp_path: Path, monkeypatch) -> None:
    fake_cogames = tmp_path / "fake_cogames.py"
    _write_fake_cogames(fake_cogames)

    state_path = tmp_path / "state.json"
    monkeypatch.setenv("FAKE_COGAMES_STATE", str(state_path))
    monkeypatch.setenv("FAKE_AUTH_FAIL_ONCE", "1")

    summary = run_research_command(
        ResearchCommandConfig(
            policy="metta://policy/role_py",
            policy_name="test-policy",
            season="beta-cogsguard",
            mission="arena",
            episodes=1,
            steps=50,
            output_root=tmp_path / "artifacts",
            cogames_bin=str(fake_cogames),
            detect_idle_seconds=10,
            max_step_seconds=30,
            skip_train=True,
            run_resume=True,
            researcher_profile="neophyte",
            allow_interactive_login=True,
            enforce_gates=True,
        )
    )

    assert summary.startup_status == "failed"
    assert summary.resume_status == "skipped"
    assert summary.overall_status == "failed"
