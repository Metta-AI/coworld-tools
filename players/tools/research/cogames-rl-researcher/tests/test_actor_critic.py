from __future__ import annotations

from pathlib import Path

from cogames_rl_researcher.actor_critic import analyze_actor_critic, write_actor_critic_report
from cogames_rl_researcher.log_mining import LogMiningReport
from cogames_rl_researcher.startup import AuditBundle, StartupConfig, run_startup

from tests.test_startup import _write_fake_cogames


def test_actor_critic_report_file_written(tmp_path: Path, monkeypatch) -> None:
    fake_cogames = tmp_path / "fake_cogames.py"
    _write_fake_cogames(fake_cogames)

    state_path = tmp_path / "state.json"
    monkeypatch.setenv("FAKE_COGAMES_STATE", str(state_path))

    bundle = run_startup(
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
        )
    )

    current_path = Path(bundle.run_dir) / "audit_bundle.json"
    out_path = tmp_path / "actor_critic_report.json"

    report = write_actor_critic_report(current_bundle_path=current_path, output_path=out_path)

    assert out_path.exists()
    assert report.current_run_id == bundle.run_id
    assert report.critic.verdict in {"keep", "revert", "investigate"}


def test_actor_critic_revert_on_rank_and_reliability_regression(tmp_path: Path, monkeypatch) -> None:
    fake_cogames = tmp_path / "fake_cogames.py"
    _write_fake_cogames(fake_cogames)

    state_path = tmp_path / "state.json"
    monkeypatch.setenv("FAKE_COGAMES_STATE", str(state_path))

    baseline = run_startup(
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
        )
    )

    payload = baseline.model_dump(mode="json")
    payload["run_id"] = "regressed"
    payload["leaderboard_rank"] = (baseline.leaderboard_rank or 1) + 4
    payload["leaderboard_score"] = (baseline.leaderboard_score or 0.0) - 10.0
    payload["reliability_index"]["downtime_minutes"] = baseline.reliability_index.downtime_minutes + 10.0
    payload["friction_index"]["failed_invocations"] = baseline.friction_index.failed_invocations + 3

    regressed = AuditBundle.model_validate(payload)

    report = analyze_actor_critic(regressed, baseline)
    assert report.critic.verdict == "revert"


def test_actor_critic_keep_on_rank_improvement_without_reliability_regression(tmp_path: Path, monkeypatch) -> None:
    fake_cogames = tmp_path / "fake_cogames.py"
    _write_fake_cogames(fake_cogames)

    state_path = tmp_path / "state.json"
    monkeypatch.setenv("FAKE_COGAMES_STATE", str(state_path))

    baseline = run_startup(
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
        )
    )

    payload = baseline.model_dump(mode="json")
    payload["run_id"] = "improved"
    payload["leaderboard_rank"] = max((baseline.leaderboard_rank or 2) - 1, 1)
    payload["leaderboard_score"] = (baseline.leaderboard_score or 0.0) + 2.0

    improved = AuditBundle.model_validate(payload)
    report = analyze_actor_critic(improved, baseline)

    assert report.critic.verdict == "keep"
    assert report.metric_deltas.rank_delta is None or report.metric_deltas.rank_delta >= 0


def test_actor_critic_investigates_when_score_delta_is_not_significant(tmp_path: Path, monkeypatch) -> None:
    fake_cogames = tmp_path / "fake_cogames.py"
    _write_fake_cogames(fake_cogames)

    state_path = tmp_path / "state.json"
    monkeypatch.setenv("FAKE_COGAMES_STATE", str(state_path))

    baseline_bundle = run_startup(
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
        )
    )

    baseline_payload = baseline_bundle.model_dump(mode="json")
    baseline_payload["run_id"] = "baseline-score"
    baseline_payload["leaderboard_rank"] = None
    baseline_payload["leaderboard_score"] = 50.0
    baseline = AuditBundle.model_validate(baseline_payload)

    current_payload = baseline.model_dump(mode="json")
    current_payload["run_id"] = "current-small-score"
    current_payload["leaderboard_score"] = 50.2
    current = AuditBundle.model_validate(current_payload)

    report = analyze_actor_critic(current, baseline)

    assert report.significance.score_change_significant is False
    assert report.critic.verdict == "investigate"


def test_actor_critic_keeps_when_score_delta_is_significant(tmp_path: Path, monkeypatch) -> None:
    fake_cogames = tmp_path / "fake_cogames.py"
    _write_fake_cogames(fake_cogames)

    state_path = tmp_path / "state.json"
    monkeypatch.setenv("FAKE_COGAMES_STATE", str(state_path))

    baseline_bundle = run_startup(
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
        )
    )

    baseline_payload = baseline_bundle.model_dump(mode="json")
    baseline_payload["run_id"] = "baseline-score-significant"
    baseline_payload["leaderboard_rank"] = None
    baseline_payload["leaderboard_score"] = 50.0
    baseline = AuditBundle.model_validate(baseline_payload)

    current_payload = baseline.model_dump(mode="json")
    current_payload["run_id"] = "current-large-score"
    current_payload["leaderboard_score"] = 52.5
    current = AuditBundle.model_validate(current_payload)

    report = analyze_actor_critic(current, baseline)

    assert report.significance.score_change_significant is True
    assert report.critic.verdict == "keep"


def test_actor_critic_tiebreak_prefers_reliability_when_rank_is_indistinguishable(tmp_path: Path, monkeypatch) -> None:
    fake_cogames = tmp_path / "fake_cogames.py"
    _write_fake_cogames(fake_cogames)

    state_path = tmp_path / "state.json"
    monkeypatch.setenv("FAKE_COGAMES_STATE", str(state_path))

    baseline_bundle = run_startup(
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
        )
    )

    baseline_payload = baseline_bundle.model_dump(mode="json")
    baseline_payload["run_id"] = "baseline-tiebreak"
    baseline_payload["leaderboard_rank"] = 3
    baseline_payload["leaderboard_score"] = 100.0
    baseline = AuditBundle.model_validate(baseline_payload)

    current_payload = baseline.model_dump(mode="json")
    current_payload["run_id"] = "current-tiebreak"
    current_payload["leaderboard_rank"] = 3
    current_payload["leaderboard_score"] = 100.0
    current_payload["reliability_index"]["full_loop_completion_rate_percent"] = (
        baseline.reliability_index.full_loop_completion_rate_percent + 2.0
    )
    current = AuditBundle.model_validate(current_payload)

    report = analyze_actor_critic(current, baseline)

    assert report.significance.rank_change_significant is False
    assert report.significance.score_change_significant is False
    assert report.significance.reliability_change_significant is True
    assert report.critic.verdict == "keep"


def test_actor_critic_uses_log_mining_for_bottlenecks_and_fix_pack(tmp_path: Path, monkeypatch) -> None:
    fake_cogames = tmp_path / "fake_cogames.py"
    _write_fake_cogames(fake_cogames)

    state_path = tmp_path / "state.json"
    monkeypatch.setenv("FAKE_COGAMES_STATE", str(state_path))

    bundle = run_startup(
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
        )
    )

    log_mining_report = LogMiningReport.model_validate(
        {
            "generated_at": "2026-02-13T00:00:00Z",
            "roots": [str(tmp_path / "logs")],
            "agents": ["gastown", "claude", "codex"],
            "files_scanned": 1,
            "total_failures": 3,
            "failures_by_agent": {"gastown": 0, "claude": 2, "codex": 1},
            "top_failures": [
                {
                    "signature": "cogames upload --name test-policy :: authentication failed: token expired",
                    "count": 2,
                    "likely_owner": "auth",
                    "category": "setup/auth",
                }
            ],
            "failures": [],
        }
    )

    report = analyze_actor_critic(bundle, None, log_mining_report=log_mining_report, log_mining_report_path="x.json")

    assert report.log_mining_context is not None
    assert report.log_mining_context.total_failures == 3
    assert report.critic.bottlenecks[0].category == "setup/auth"
    assert report.fix_pack_proposals
    assert report.fix_pack_proposals[0].command.startswith("cogames upload")
