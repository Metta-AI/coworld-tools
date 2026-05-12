from __future__ import annotations

from pathlib import Path

import pytest
from cogames_rl_researcher.json_io import read_json, write_json
from cogames_rl_researcher.resume import ResumeConfig, run_resume
from cogames_rl_researcher.startup import StartupConfig, run_startup

from tests.test_startup import _write_fake_cogames


def test_resume_invalid_source_path_has_clear_error(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="source must point to a startup/resume run directory"):
        run_resume(ResumeConfig(source=tmp_path / "missing-run-dir"))


def test_resume_runs_missing_submit_and_leaderboard(tmp_path: Path, monkeypatch) -> None:
    fake_cogames = tmp_path / "fake_cogames.py"
    _write_fake_cogames(fake_cogames)

    state_path = tmp_path / "state.json"
    monkeypatch.setenv("FAKE_COGAMES_STATE", str(state_path))

    startup_bundle = run_startup(
        StartupConfig(
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
            run_submit=False,
            run_leaderboard=False,
        )
    )

    state_after_startup = read_json(state_path)
    assert state_after_startup["scrimmage_count"] == 1
    assert state_after_startup.get("submit_count", 0) == 0

    resumed_bundle, next_actions = run_resume(
        ResumeConfig(
            source=Path(startup_bundle.run_dir),
            run_leaderboard=True,
        )
    )

    assert resumed_bundle.status == "success"
    assert (Path(resumed_bundle.run_dir) / "docs_digest.json").exists()
    assert any(step.step_name == "docs_readthrough" and step.status == "success" for step in resumed_bundle.steps)
    assert resumed_bundle.reaper_slo.detect_slo_met is True
    assert resumed_bundle.gates is not None
    assert resumed_bundle.gates.overall_status == "pass"
    assert resumed_bundle.escalation_plan is not None
    assert resumed_bundle.escalation_plan.should_escalate is False
    assert next_actions
    assert (Path(resumed_bundle.run_dir) / "ranked_next_actions.json").exists()
    history_path = Path(resumed_bundle.run_dir) / "history_comparison.json"
    assert history_path.exists()
    history_payload = read_json(history_path)
    assert history_payload["baseline_run_id"] == startup_bundle.run_id
    gates_path = Path(resumed_bundle.run_dir) / "gates_evaluation.json"
    assert gates_path.exists()
    gates_payload = read_json(gates_path)
    assert gates_payload["overall_status"] == "pass"
    escalation_path = Path(resumed_bundle.run_dir) / "escalation_plan.json"
    assert escalation_path.exists()
    escalation_payload = read_json(escalation_path)
    assert escalation_payload["should_escalate"] is False
    actor_critic_path = Path(resumed_bundle.run_dir) / "actor_critic_report.json"
    assert actor_critic_path.exists()
    actor_critic_payload = read_json(actor_critic_path)
    assert actor_critic_payload["critic"]["verdict"] in {"keep", "revert", "investigate"}

    state_after_resume = read_json(state_path)
    assert state_after_resume["scrimmage_count"] == 1
    assert state_after_resume["upload_count"] == 2
    assert state_after_resume["submit_count"] == 1
    assert state_after_resume["leaderboard_count"] == 1


def test_resume_force_scrimmage_reruns_eval(tmp_path: Path, monkeypatch) -> None:
    fake_cogames = tmp_path / "fake_cogames.py"
    _write_fake_cogames(fake_cogames)

    state_path = tmp_path / "state.json"
    monkeypatch.setenv("FAKE_COGAMES_STATE", str(state_path))

    startup_bundle = run_startup(
        StartupConfig(
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
            run_submit=False,
            run_leaderboard=False,
        )
    )

    run_resume(
        ResumeConfig(
            source=Path(startup_bundle.run_dir),
            run_leaderboard=False,
            include_missing_submit=False,
            force_scrimmage=True,
        )
    )

    state_after_resume = read_json(state_path)
    assert state_after_resume["scrimmage_count"] == 2


def test_resume_emit_swarm_plan_writes_artifact(tmp_path: Path, monkeypatch) -> None:
    fake_cogames = tmp_path / "fake_cogames.py"
    _write_fake_cogames(fake_cogames)

    state_path = tmp_path / "state.json"
    monkeypatch.setenv("FAKE_COGAMES_STATE", str(state_path))

    startup_bundle = run_startup(
        StartupConfig(
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
            run_submit=False,
            run_leaderboard=False,
        )
    )

    resumed_bundle, _ = run_resume(
        ResumeConfig(
            source=Path(startup_bundle.run_dir),
            run_leaderboard=True,
            emit_swarm_plan=True,
            swarm_workers=2,
            swarm_max_tasks_per_worker=1,
            swarm_timeout_seconds=300,
        )
    )

    swarm_plan_path = Path(resumed_bundle.run_dir) / "swarm_plan.json"
    assert swarm_plan_path.exists()
    swarm_payload = read_json(swarm_plan_path)
    assert len(swarm_payload["workers"]) == 2
    assert len(swarm_payload["tasks"]) <= 2


def test_resume_can_override_researcher_profile(tmp_path: Path, monkeypatch) -> None:
    fake_cogames = tmp_path / "fake_cogames.py"
    _write_fake_cogames(fake_cogames)

    state_path = tmp_path / "state.json"
    monkeypatch.setenv("FAKE_COGAMES_STATE", str(state_path))

    startup_bundle = run_startup(
        StartupConfig(
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
            run_submit=False,
            run_leaderboard=False,
            researcher_profile="experienced",
        )
    )

    resumed_bundle, _ = run_resume(
        ResumeConfig(
            source=Path(startup_bundle.run_dir),
            run_leaderboard=True,
            researcher_profile="neophyte",
        )
    )

    assert resumed_bundle.config.researcher_profile == "neophyte"


def test_resume_neophyte_profile_rejects_non_happy_path_overrides(tmp_path: Path, monkeypatch) -> None:
    fake_cogames = tmp_path / "fake_cogames.py"
    _write_fake_cogames(fake_cogames)

    state_path = tmp_path / "state.json"
    monkeypatch.setenv("FAKE_COGAMES_STATE", str(state_path))

    startup_bundle = run_startup(
        StartupConfig(
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
            run_submit=False,
            run_leaderboard=False,
        )
    )

    resumed_bundle, _ = run_resume(
        ResumeConfig(
            source=Path(startup_bundle.run_dir),
            researcher_profile="neophyte",
            force_scrimmage=True,
            emit_swarm_plan=True,
        )
    )

    assert resumed_bundle.status == "failed"
    guard_step = next(step for step in resumed_bundle.steps if step.step_name == "neophyte_happy_path_guard")
    assert guard_step.status == "failed"
    assert "force-* resume overrides are not allowed for neophyte profile" in guard_step.stderr_tail
    assert not (Path(resumed_bundle.run_dir) / "swarm_plan.json").exists()


def test_resume_uses_log_mining_for_fix_pack_actions(tmp_path: Path, monkeypatch) -> None:
    fake_cogames = tmp_path / "fake_cogames.py"
    _write_fake_cogames(fake_cogames)

    state_path = tmp_path / "state.json"
    monkeypatch.setenv("FAKE_COGAMES_STATE", str(state_path))

    output_root = tmp_path / "artifacts"
    startup_bundle = run_startup(
        StartupConfig(
            policy="metta://policy/role_py",
            policy_name="test-policy",
            season="beta-cogsguard",
            mission="arena",
            episodes=1,
            steps=50,
            output_root=output_root,
            cogames_bin=str(fake_cogames),
            detect_idle_seconds=10,
            max_step_seconds=30,
            run_submit=False,
            run_leaderboard=False,
        )
    )

    log_mining_payload = {
        "generated_at": "2026-02-13T00:00:00Z",
        "roots": [str(tmp_path / "logs")],
        "agents": ["gastown", "claude", "codex"],
        "files_scanned": 1,
        "total_failures": 2,
        "failures_by_agent": {"gastown": 0, "claude": 2, "codex": 0},
        "top_failures": [
            {
                "signature": "cogames submit test-policy --season beta-cogsguard :: error: submit failed",
                "count": 2,
                "likely_owner": "cogames-cli",
                "category": "submission workflow",
            }
        ],
        "failures": [],
    }
    write_json(output_root / "log_mining_report.json", log_mining_payload)

    resumed_bundle, actions = run_resume(
        ResumeConfig(
            source=Path(startup_bundle.run_dir),
            run_leaderboard=True,
        )
    )

    assert actions
    assert actions[0].action.startswith("Apply fix pack for submission workflow")
    fix_pack_path = Path(resumed_bundle.run_dir) / "fix_pack_plan.json"
    assert fix_pack_path.exists()
    actor_critic_payload = read_json(Path(resumed_bundle.run_dir) / "actor_critic_report.json")
    assert actor_critic_payload["log_mining_context"]["total_failures"] == 2
