from __future__ import annotations

from pathlib import Path

import cogames_rl_researcher.startup as startup_module
import pytest
from cogames_rl_researcher.json_io import read_json
from cogames_rl_researcher.startup import AuditBundle, StartupConfig, run_startup


def _write_fake_cogames(path: Path) -> None:
    script = """#!/usr/bin/env python3
import json
import os
import sys
from pathlib import Path

state_path = Path(os.environ[\"FAKE_COGAMES_STATE\"])
if state_path.exists():
    state = json.loads(state_path.read_text())
else:
    state = {}

argv = sys.argv[1:]
if not argv:
    print(\"missing command\", file=sys.stderr)
    sys.exit(1)

cmd = argv[0]
args = argv[1:]

state.setdefault(\"commands\", []).append(cmd)
state[\"last_args\"] = args

if cmd == \"login\":
    state[\"login_count\"] = state.get(\"login_count\", 0) + 1
    if \"--force\" in args:
        state[\"forced_login_count\"] = state.get(\"forced_login_count\", 0) + 1
    state_path.write_text(json.dumps(state))
    print(\"Authentication successful!\")
    sys.exit(0)

if cmd == \"scrimmage\":
    state[\"scrimmage_count\"] = state.get(\"scrimmage_count\", 0) + 1
    state_path.write_text(json.dumps(state))
    if os.environ.get(\"FAKE_AUTH_FAIL_ONCE\") == \"1\" and state[\"scrimmage_count\"] == 1:
        print(\"authentication failed\", file=sys.stderr)
        sys.exit(1)

    payload = {
        \"missions\": [
            {
                \"mission_summary\": {
                    \"avg_game_stats\": {
                        \"junction.held\": 8.0,
                        \"junction.gained\": 2.0,
                    },
                    \"policy_summaries\": [
                        {
                            \"avg_agent_metrics\": {
                                \"heart.gained\": 3.0,
                                \"heart.lost\": 1.0,
                            },
                            \"action_timeouts\": 0.0,
                            \"per_episode_per_policy_avg_rewards\": {
                                \"episode_0\": 11.0,
                                \"episode_1\": 13.0,
                            },
                        }
                    ],
                }
            }
        ]
    }
    print(json.dumps(payload))
    sys.exit(0)

if cmd == \"upload\":
    state[\"upload_count\"] = state.get(\"upload_count\", 0) + 1
    state_path.write_text(json.dumps(state))
    if \"--dry-run\" in args:
        print(\"dry-run validation passed\")
    else:
        print(\"Upload complete\")
    sys.exit(0)

if cmd == \"submit\":
    state[\"submit_count\"] = state.get(\"submit_count\", 0) + 1
    state_path.write_text(json.dumps(state))
    print(\"Submitted\")
    sys.exit(0)

if cmd == \"leaderboard\":
    state[\"leaderboard_count\"] = state.get(\"leaderboard_count\", 0) + 1
    state_path.write_text(json.dumps(state))
    payload = [
        {
            \"rank\": 1,
            \"policy\": {\"name\": \"test-policy\", \"version\": 3},
            \"score\": 99.5,
            \"matches\": 12,
        }
    ]
    print(json.dumps(payload))
    sys.exit(0)

if cmd == \"pickup\":
    state[\"pickup_count\"] = state.get(\"pickup_count\", 0) + 1
    state_path.write_text(json.dumps(state))
    print(\"pickup complete\")
    sys.exit(0)

print(f\"unknown command: {cmd}\", file=sys.stderr)
sys.exit(1)
"""
    path.write_text(script)
    path.chmod(0o755)


def _prepare_fake_cogames(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    state_name: str = "state.json",
    auth_fail_once: bool = False,
) -> tuple[Path, Path]:
    fake_cogames = tmp_path / "fake_cogames.py"
    _write_fake_cogames(fake_cogames)

    state_path = tmp_path / state_name
    monkeypatch.setenv("FAKE_COGAMES_STATE", str(state_path))
    if auth_fail_once:
        monkeypatch.setenv("FAKE_AUTH_FAIL_ONCE", "1")
    else:
        monkeypatch.delenv("FAKE_AUTH_FAIL_ONCE", raising=False)
    return fake_cogames, state_path


def _startup_config(tmp_path: Path, fake_cogames: Path, **overrides: object) -> StartupConfig:
    config: dict[str, object] = {
        "policy": "metta://policy/role_py",
        "policy_name": "test-policy",
        "season": "beta-cogsguard",
        "mission": "arena",
        "episodes": 1,
        "steps": 50,
        "output_root": tmp_path / "artifacts",
        "cogames_bin": str(fake_cogames),
        "detect_idle_seconds": 10,
        "max_step_seconds": 30,
    }
    config.update(overrides)
    return StartupConfig(**config)


def _run_fake_startup(tmp_path: Path, fake_cogames: Path, **overrides: object) -> AuditBundle:
    return run_startup(_startup_config(tmp_path, fake_cogames, **overrides))


def test_startup_workflow_success(tmp_path: Path, monkeypatch) -> None:
    fake_cogames, state_path = _prepare_fake_cogames(tmp_path, monkeypatch)
    bundle = _run_fake_startup(tmp_path, fake_cogames, episodes=2, steps=100)

    assert bundle.status == "success"
    assert bundle.leaderboard_rank == 1
    assert bundle.leaderboard_score == 99.5
    assert bundle.scrimmage_metrics.reward == 12.0
    assert bundle.reaper_slo.detect_slo_met is True
    assert bundle.reaper_slo.recovery_slo_met is True
    assert bundle.gates is not None
    assert bundle.gates.overall_status == "pass"
    assert bundle.escalation_plan is not None
    assert bundle.escalation_plan.should_escalate is False
    assert (Path(bundle.run_dir) / "audit_bundle.json").exists()
    assert (Path(bundle.run_dir) / "docs_digest.json").exists()
    assert (Path(bundle.run_dir) / "daily_report.md").exists()
    assert any(step.step_name == "docs_readthrough" and step.status == "success" for step in bundle.steps)
    history_path = Path(bundle.run_dir) / "history_comparison.json"
    assert history_path.exists()
    history_payload = read_json(history_path)
    assert history_payload["current_run_id"] == bundle.run_id
    gates_path = Path(bundle.run_dir) / "gates_evaluation.json"
    assert gates_path.exists()
    gates_payload = read_json(gates_path)
    assert gates_payload["overall_status"] == "pass"
    escalation_path = Path(bundle.run_dir) / "escalation_plan.json"
    assert escalation_path.exists()
    escalation_payload = read_json(escalation_path)
    assert escalation_payload["should_escalate"] is False

    state = read_json(state_path)
    assert state["login_count"] == 1
    assert state["upload_count"] == 2
    assert state["submit_count"] == 1
    assert state["leaderboard_count"] == 1


def test_startup_recovers_auth_failure(tmp_path: Path, monkeypatch) -> None:
    fake_cogames, state_path = _prepare_fake_cogames(tmp_path, monkeypatch, auth_fail_once=True)
    bundle = _run_fake_startup(tmp_path, fake_cogames, max_recoveries=2, allow_interactive_login=True)

    assert bundle.status == "success"
    assert any(incident.incident_type == "auth_expired" for incident in bundle.incidents)
    assert bundle.reaper_slo.recovery_attempts >= 1
    assert any(item.category == "setup/auth" for item in bundle.diagnosis.friction_items)

    state = read_json(state_path)
    assert state["scrimmage_count"] == 2
    assert state["login_count"] >= 2
    assert state.get("forced_login_count", 0) >= 1


def test_startup_fails_when_run_fails(tmp_path: Path, monkeypatch) -> None:
    fake_cogames, _ = _prepare_fake_cogames(tmp_path, monkeypatch, auth_fail_once=True)
    bundle = _run_fake_startup(tmp_path, fake_cogames, max_recoveries=0)

    assert bundle.status == "failed"
    assert bundle.gates is not None
    assert bundle.gates.overall_status == "fail"
    full_loop = next(check for check in bundle.gates.checks if check.gate_id == "full_loop_success")
    assert full_loop.status == "fail"
    gates_path = Path(bundle.run_dir) / "gates_evaluation.json"
    assert gates_path.exists()


def test_startup_neophyte_profile_applies_stricter_gate_budgets(tmp_path: Path, monkeypatch) -> None:
    fake_cogames, _ = _prepare_fake_cogames(tmp_path, monkeypatch, auth_fail_once=True)
    bundle = _run_fake_startup(
        tmp_path,
        fake_cogames,
        max_recoveries=2,
        researcher_profile="neophyte",
        allow_interactive_login=True,
    )

    assert bundle.status == "success"
    assert bundle.gates is not None
    assert bundle.gates.overall_status == "fail"
    failed_budget = next(check for check in bundle.gates.checks if check.gate_id == "failed_invocations_budget")
    assert failed_budget.status == "fail"
    assert bundle.escalation_plan is not None
    assert bundle.escalation_plan.should_escalate is False


def test_startup_escalates_after_consecutive_failed_gate_runs(tmp_path: Path, monkeypatch) -> None:
    fake_cogames, _ = _prepare_fake_cogames(tmp_path, monkeypatch, auth_fail_once=True)
    output_root = tmp_path / "artifacts"
    monkeypatch.setenv("FAKE_COGAMES_STATE", str(tmp_path / "state_first.json"))
    first_bundle = _run_fake_startup(
        tmp_path,
        fake_cogames,
        output_root=output_root,
        max_recoveries=2,
        researcher_profile="neophyte",
        allow_interactive_login=True,
    )
    assert first_bundle.gates is not None
    assert first_bundle.gates.overall_status == "fail"

    monkeypatch.setenv("FAKE_COGAMES_STATE", str(tmp_path / "state_second.json"))
    second_bundle = _run_fake_startup(
        tmp_path,
        fake_cogames,
        output_root=output_root,
        max_recoveries=2,
        researcher_profile="neophyte",
        allow_interactive_login=True,
    )

    assert second_bundle.gates is not None
    assert second_bundle.gates.overall_status == "fail"
    assert second_bundle.escalation_plan is not None
    assert second_bundle.escalation_plan.consecutive_failed_gate_runs == 2
    assert second_bundle.escalation_plan.escalation_threshold == 2
    assert second_bundle.escalation_plan.should_escalate is True


def test_startup_tracks_experiment_family_breadth_across_runs(tmp_path: Path, monkeypatch) -> None:
    fake_cogames, _ = _prepare_fake_cogames(tmp_path, monkeypatch)
    output_root = tmp_path / "artifacts"

    monkeypatch.setenv("FAKE_COGAMES_STATE", str(tmp_path / "state_a.json"))
    first_bundle = _run_fake_startup(tmp_path, fake_cogames, output_root=output_root, policy_name="family-a-v1")

    monkeypatch.setenv("FAKE_COGAMES_STATE", str(tmp_path / "state_b.json"))
    second_bundle = _run_fake_startup(tmp_path, fake_cogames, output_root=output_root, policy_name="family-b-v1")

    assert first_bundle.submit_coverage_index.experiment_family_breadth == 1
    assert second_bundle.submit_coverage_index.experiment_family_breadth >= 2


def test_startup_noninteractive_mode_fails_without_saved_token(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(startup_module, "_has_saved_auth_token", lambda *_: False)

    bundle = run_startup(
        StartupConfig(
            policy="metta://policy/role_py",
            policy_name="test-policy",
            output_root=tmp_path / "artifacts",
            cogames_bin="cogames",
            detect_idle_seconds=10,
            max_step_seconds=30,
            allow_interactive_login=False,
        )
    )

    assert bundle.status == "failed"
    login_step = next(step for step in bundle.steps if step.step_name == "login_auth_check")
    assert login_step.status == "failed"
    assert "No saved CoGames auth token found for non-interactive mode" in login_step.stderr_tail


def test_startup_neophyte_profile_rejects_non_happy_path_config(tmp_path: Path, monkeypatch) -> None:
    fake_cogames, _ = _prepare_fake_cogames(tmp_path, monkeypatch)
    bundle = _run_fake_startup(tmp_path, fake_cogames, run_submit=False, researcher_profile="neophyte")

    assert bundle.status == "failed"
    guard_step = next(step for step in bundle.steps if step.step_name == "neophyte_happy_path_guard")
    assert guard_step.status == "failed"
    assert "run_submit must remain enabled for neophyte profile" in guard_step.stderr_tail
    assert bundle.gates is not None
    assert bundle.gates.overall_status == "fail"


def test_startup_trend_gates_fail_when_reliability_and_friction_regress(tmp_path: Path, monkeypatch) -> None:
    fake_cogames, _ = _prepare_fake_cogames(tmp_path, monkeypatch)
    output_root = tmp_path / "artifacts"

    monkeypatch.setenv("FAKE_COGAMES_STATE", str(tmp_path / "state_baseline.json"))
    baseline = _run_fake_startup(tmp_path, fake_cogames, output_root=output_root, allow_interactive_login=True)
    assert baseline.gates is not None
    assert baseline.gates.overall_status == "pass"

    monkeypatch.setenv("FAKE_COGAMES_STATE", str(tmp_path / "state_regressed.json"))
    monkeypatch.setenv("FAKE_AUTH_FAIL_ONCE", "1")
    regressed = _run_fake_startup(tmp_path, fake_cogames, output_root=output_root, allow_interactive_login=True)

    assert regressed.history_comparison is not None
    assert regressed.history_comparison.baseline_run_id == baseline.run_id
    assert regressed.history_comparison.reliability_delta is not None
    assert regressed.history_comparison.reliability_delta < 0.0
    assert regressed.history_comparison.friction_delta is not None
    assert regressed.history_comparison.friction_delta > 0.0
    assert regressed.gates is not None
    gate_map = {check.gate_id: check.status for check in regressed.gates.checks}
    assert gate_map["reliability_trend"] == "fail"
    assert gate_map["friction_trend"] == "fail"


def test_parse_successful_step_output_json_returns_none_for_non_json_output(tmp_path: Path) -> None:
    stdout_log = tmp_path / "leaderboard.stdout.log"
    stderr_log = tmp_path / "leaderboard.stderr.log"
    stdout_log.write_text("INFO starting leaderboard check\nnot-json\n", encoding="utf-8")
    stderr_log.write_text("", encoding="utf-8")
    now = startup_module._utc_now()

    step = startup_module.StepResult(
        step_name="leaderboard_check",
        attempt=1,
        command=["cogames", "leaderboard", "--json"],
        status="success",
        return_code=0,
        started_at=now,
        ended_at=now,
        duration_seconds=0.0,
        stdout_log=str(stdout_log),
        stderr_log=str(stderr_log),
        stdout_tail="",
        stderr_tail="",
    )

    parsed = startup_module._parse_successful_step_output_json([step], "leaderboard_check")
    assert parsed is None


def test_infer_upload_include_files_returns_local_policy_file(monkeypatch, tmp_path: Path) -> None:
    policy_file = tmp_path / "generated_policy.py"
    policy_file.write_text("class MyTrainablePolicy:\n    pass\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    include_files = startup_module._infer_upload_include_files(
        "class=generated_policy.MyTrainablePolicy,data=artifacts/model_000001.pt"
    )
    assert include_files == ["generated_policy.py"]


def test_build_step_catalog_adds_include_files_for_upload_steps(monkeypatch, tmp_path: Path) -> None:
    policy_file = tmp_path / "generated_policy.py"
    policy_file.write_text("class MyTrainablePolicy:\n    pass\n", encoding="utf-8")
    replay_dir = tmp_path / "replays"
    replay_dir.mkdir()
    monkeypatch.chdir(tmp_path)

    config = StartupConfig(
        policy="class=generated_policy.MyTrainablePolicy,data=artifacts/model_000001.pt",
        policy_name="generated-policy",
    )
    catalog = startup_module._build_step_catalog(config, replay_dir)

    dry_run_cmd = catalog["upload_dry_run_validation"].command
    upload_cmd = catalog["upload"].command
    assert "--include-files" in dry_run_cmd
    assert "--include-files" in upload_cmd
    assert dry_run_cmd[dry_run_cmd.index("--include-files") + 1] == "generated_policy.py"
    assert upload_cmd[upload_cmd.index("--include-files") + 1] == "generated_policy.py"
