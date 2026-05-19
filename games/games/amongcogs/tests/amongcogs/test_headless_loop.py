import amongcogs.headless as among_us_headless
from amongcogs.headless import (
    AmongUsAuditGateThresholds,
    AmongUsReleaseScenario,
    evaluate_headless_audit_gate,
    format_headless_audit_summary,
    run_headless_audit,
    run_headless_determinism_check,
    run_headless_episode,
    run_headless_release_suite,
)
from amongcogs.runtime import GAMES


def test_among_us_registry_uses_scripted_default_policy() -> None:
    info = GAMES["amongcogs"]
    assert info["policy_uri"] == "metta://policy/amongcogs_agent"
    assert "amongcogs.agent.amongcogs_agent" in info["policy_packages"]


def test_headless_scripted_episode_exercises_core_mechanics() -> None:
    summary = run_headless_episode(
        num_agents=8,
        max_steps=140,
        seed=42,
        log_every=20,
        end_on_winner=False,
        verbose=False,
    )

    assert summary.completed is True
    assert 1 <= summary.steps <= summary.max_steps
    assert summary.completion_reason == "max_steps"
    assert summary.role_counts["crew"] > 0
    assert summary.role_counts["impostor"] > 0
    assert summary.role_counts["crew"] + summary.role_counts["impostor"] == summary.num_agents

    assert summary.totals["tasks_completed"] > 0
    assert summary.totals["repairs"] > 0
    assert summary.totals["kills"] > 0
    assert summary.totals["reports"] > 0

    assert summary.game_stats.get("impostor_sabotages", 0) > 0
    assert summary.game_stats.get("crew_repairs", 0) > 0
    assert any(
        summary.game_stats.get(name, 0) > 0
        for name in ("lights_sabotages", "oxygen_sabotages", "reactor_sabotages", "comms_sabotages")
    )
    assert summary.game_stats.get("meeting_votes", 0) > 0
    assert "vents_used" in summary.totals
    assert "admin_checks" in summary.totals
    assert "camera_checks" in summary.totals
    assert "comms_checks" in summary.totals
    assert summary.actions["move_attempts"] > 0
    assert summary.actions["action_success_rate"] >= 0
    assert summary.actions["talk_actions"] > 0
    assert summary.actions["meeting_talk_actions"] > 0
    assert summary.actions["ballot_talk_actions"] > 0
    assert summary.actions["talk_chars"] >= summary.actions["talk_actions"]
    assert summary.first_steps["first_task"] is not None
    assert summary.first_steps["first_repair"] is not None
    assert summary.first_steps["first_kill"] is not None
    assert summary.first_steps["first_report"] is not None
    assert summary.first_steps["first_meeting"] is not None
    assert summary.timeline
    assert max(point.stations_sabotaged for point in summary.timeline) > 0


def test_headless_amongthem_nottoodumb_policy_uri_runs_full_loop() -> None:
    summary = run_headless_episode(
        num_agents=5,
        max_steps=160,
        seed=73,
        policy_uri="metta://policy/amongthem_nottoodumb",
        log_every=0,
        end_on_winner=True,
        verbose=False,
    )

    assert summary.completed is True
    assert summary.role_counts == {"crew": 4, "impostor": 1}
    assert summary.totals["tasks_completed"] > 0
    assert summary.totals["kills"] > 0
    assert summary.game_stats.get("meeting_called", 0) > 0
    assert summary.game_stats.get("meeting_votes", 0) > 0
    assert summary.game_stats.get("winner_declared", 0) > 0


def test_headless_amongthem_nottoodumb_policy_exercises_parity_surface() -> None:
    audit = run_headless_audit(
        episodes=8,
        num_agents=5,
        max_steps=240,
        base_seed=73,
        policy_uri="metta://policy/amongthem_nottoodumb",
        log_every=0,
        end_on_winner=False,
        include_episodes=False,
    )
    coverage = audit["coverage"]
    winners = audit["winners"]

    assert audit["completion_rate"] == 1.0
    assert coverage["winner_declared_rate"] == 1.0
    for coverage_key in (
        "tasks_completed_rate",
        "kills_rate",
        "reports_rate",
        "ejections_rate",
        "meeting_calls_rate",
        "meeting_skips_rate",
        "emergency_meeting_calls_rate",
        "sabotages_rate",
        "repairs_rate",
        "vents_used_rate",
        "admin_checks_rate",
        "camera_checks_rate",
        "comms_checks_rate",
        "lights_sabotages_rate",
        "oxygen_sabotages_rate",
        "reactor_sabotages_rate",
        "talk_actions_rate",
        "meeting_talk_actions_rate",
        "ballot_talk_actions_rate",
    ):
        assert coverage[coverage_key] > 0, coverage_key
    assert audit["actions"]["meeting_talk_actions"] > 0
    assert audit["actions"]["ballot_talk_actions"] > 0
    assert winners["crew"] > 0
    assert winners["impostor"] > 0


def test_headless_can_end_early_on_winner() -> None:
    summary = run_headless_episode(
        num_agents=12,
        max_steps=220,
        seed=0,
        log_every=0,
        end_on_winner=True,
        verbose=False,
    )

    assert summary.completed is True
    assert summary.steps < summary.max_steps
    assert summary.completion_reason == "winner_declared"
    assert summary.game_stats.get("winner_declared", 0) > 0
    assert summary.winner in {"crew", "impostor"}


def test_headless_timeout_resolution_declares_winner_at_max_steps() -> None:
    summary = run_headless_episode(
        num_agents=12,
        max_steps=220,
        seed=0,
        log_every=0,
        end_on_winner=False,
        verbose=False,
    )

    assert summary.completed is True
    assert summary.steps == summary.max_steps
    assert summary.completion_reason == "max_steps"
    assert summary.game_stats.get("winner_declared", 0) > 0
    assert summary.winner in {"crew", "impostor"}
    assert any(
        summary.game_stats.get(name, 0) > 0
        for name in (
            "crew_win_tasks",
            "crew_win_elimination",
            "impostor_win_timeout",
            "impostor_win_elimination",
            "impostor_win_reactor",
            "impostor_win_oxygen",
        )
    )


def test_headless_audit_aggregates_reliability_metrics() -> None:
    audit = run_headless_audit(
        episodes=3,
        num_agents=8,
        max_steps=120,
        base_seed=4,
        end_on_winner=False,
        include_episodes=False,
    )

    assert audit["episodes"] == 3
    assert audit["completion_rate"] == 1.0
    coverage = audit["coverage"]
    assert isinstance(coverage, dict)
    expected_coverage = {
        "tasks_completed_rate",
        "repairs_rate",
        "kills_rate",
        "reports_rate",
        "ejections_rate",
        "vents_used_rate",
        "admin_checks_rate",
        "camera_checks_rate",
        "comms_checks_rate",
        "lights_sabotages_rate",
        "oxygen_sabotages_rate",
        "reactor_sabotages_rate",
    }
    assert expected_coverage.issubset(coverage)
    for rate_name in expected_coverage:
        assert 0.0 <= coverage[rate_name] <= 1.0
    role_adoption = audit["role_adoption"]
    assert isinstance(role_adoption, dict)
    assert role_adoption["min"] == role_adoption["expected"]
    episode_profiles = audit["episode_profiles"]
    assert isinstance(episode_profiles, dict)
    assert set(episode_profiles) == {"steps", "sps", "wall_time_s"}
    for metrics in episode_profiles.values():
        assert isinstance(metrics, dict)
        assert set(metrics) == {"min", "p50", "p95", "max", "mean"}
    win_conditions = audit["win_conditions"]
    assert isinstance(win_conditions, dict)
    counts = win_conditions["counts"]
    rates = win_conditions["rates"]
    assert isinstance(counts, dict)
    assert isinstance(rates, dict)
    assert set(counts) == {"crew_tasks", "crew_elimination", "impostor_sabotage", "impostor_elimination"}
    assert set(rates) == {"crew_tasks", "crew_elimination", "impostor_sabotage", "impostor_elimination"}
    assert sum(counts.values()) <= audit["episodes"]  # type: ignore[arg-type]

    gate = evaluate_headless_audit_gate(audit, profile="baseline")
    assert "passed" in gate
    assert isinstance(gate["passed"], bool)
    assert "checks" in gate
    assert isinstance(gate["checks"], list)
    assert len(gate["checks"]) > 0  # type: ignore[arg-type]
    assert gate["profile"] == "baseline"
    # Verify each check has the expected structure
    for check in gate["checks"]:  # type: ignore[union-attr]
        assert "name" in check
        assert "value" in check
        assert "passed" in check


def test_headless_audit_visits_extended_among_us_mechanics() -> None:
    audit = run_headless_audit(
        episodes=4,
        num_agents=12,
        max_steps=220,
        base_seed=0,
        end_on_winner=False,
        include_episodes=False,
    )

    coverage = audit["coverage"]
    assert isinstance(coverage, dict)
    assert coverage["vents_used_rate"] > 0
    assert coverage["admin_checks_rate"] > 0
    assert coverage["camera_checks_rate"] > 0
    assert coverage["comms_checks_rate"] > 0
    assert coverage["oxygen_sabotages_rate"] > 0 or coverage["reactor_sabotages_rate"] > 0


def test_format_headless_audit_summary_includes_gate_and_determinism_status() -> None:
    payload = {
        "audit": {
            "episodes": 3,
            "completion_rate": 1.0,
            "coverage": {
                "winner_declared_rate": 1.0,
                "tasks_completed_rate": 1.0,
                "sabotages_rate": 0.66,
                "repairs_rate": 0.66,
            },
            "winners": {"crew": 2, "impostor": 1, "none": 0},
            "episode_profiles": {
                "steps": {"p50": 110.0, "p95": 120.0},
                "sps": {"p50": 45.0, "p95": 40.0},
            },
        },
        "gate": {
            "profile": "ship_strict",
            "passed": False,
            "checks": [{"name": "coverage.reports_rate", "passed": False}],
        },
        "determinism": {
            "checked": True,
            "passed": True,
            "repeats": 2,
            "episodes": 4,
        },
    }
    summary = format_headless_audit_summary(payload)
    assert "amongcogs.audit" in summary
    assert "mechanics" in summary
    assert "gate[ship_strict]=FAIL" in summary
    assert "determinism=PASS" in summary


def test_format_headless_audit_summary_handles_release_suite_payload() -> None:
    summary = format_headless_audit_summary(
        {
            "release_suite": {
                "suite_name": "default",
                "passed": True,
                "pass_rate": 1.0,
                "scenario_results": [{}, {}],
                "failures": [],
            }
        }
    )

    assert summary == "amongcogs.release suite=default passed=True pass_rate=1.000 scenarios=2"


def test_headless_audit_gate_ship_strict_fails_on_unbalanced_winners() -> None:
    audit = {
        "completion_rate": 1.0,
        "coverage": {
            "winner_declared_rate": 1.0,
            "tasks_completed_rate": 1.0,
            "kills_rate": 1.0,
            "reports_rate": 1.0,
            "ejections_rate": 1.0,
            "repairs_rate": 1.0,
            "sabotages_rate": 1.0,
        },
        "role_adoption": {
            "min": 8,
            "expected": 8,
        },
        "sps": {"mean": 500.0},
        "winners": {"crew": 50, "impostor": 0},
    }
    gate = evaluate_headless_audit_gate(audit, profile="ship_strict")
    assert gate["passed"] is False
    assert any(
        check["name"] == "winner_rates.impostor" and check["passed"] is False
        for check in gate["checks"]  # type: ignore[index]
    )


def test_headless_audit_gate_perf_floor_is_optional_and_overridable() -> None:
    audit = {
        "completion_rate": 1.0,
        "coverage": {
            "winner_declared_rate": 1.0,
            "tasks_completed_rate": 1.0,
            "kills_rate": 1.0,
            "reports_rate": 1.0,
            "ejections_rate": 1.0,
            "repairs_rate": 1.0,
            "sabotages_rate": 1.0,
        },
        "role_adoption": {
            "min": 8,
            "expected": 8,
        },
        "sps": {"mean": 10.0},
        "winners": {"crew": 4, "impostor": 2},
    }
    baseline_gate = evaluate_headless_audit_gate(audit, profile="baseline")
    assert baseline_gate["passed"] is True

    strict_perf = AmongUsAuditGateThresholds(min_sps_mean=500.0)
    perf_gate = evaluate_headless_audit_gate(audit, profile="baseline", thresholds=strict_perf)
    assert perf_gate["passed"] is False
    assert any(
        check["name"] == "sps.mean" and check["passed"] is False
        for check in perf_gate["checks"]  # type: ignore[index]
    )


def test_headless_determinism_check_detects_mismatch(monkeypatch) -> None:
    call_idx = {"value": 0}

    stable_audit = {
        "episodes": 2,
        "num_agents": 8,
        "max_steps": 100,
        "end_on_winner": False,
        "completion_rate": 1.0,
        "completion_reasons": {"max_steps": 2},
        "coverage": {"tasks_completed_rate": 1.0},
        "winners": {"crew": 1, "impostor": 1},
        "win_conditions": {"counts": {"crew_tasks": 1}},
        "role_adoption": {"min": 8, "max": 8, "mean": 8.0, "expected": 8},
        "first_steps": {"first_task": 12.0, "first_repair": None},
    }
    changed_audit = {
        **stable_audit,
        "winners": {"crew": 2, "impostor": 0},
    }

    def _fake_run_headless_audit(**kwargs):
        del kwargs
        call_idx["value"] += 1
        return stable_audit if call_idx["value"] == 1 else changed_audit

    monkeypatch.setattr(among_us_headless, "run_headless_audit", _fake_run_headless_audit)
    result = run_headless_determinism_check(episodes=2, repeats=2, num_agents=8, max_steps=100, base_seed=0)
    assert result["checked"] is True
    assert result["passed"] is False
    assert result["mismatch_repeats"] == [1]


def test_headless_release_suite_reports_pass_rate_failures(monkeypatch) -> None:
    monkeypatch.setattr(
        among_us_headless,
        "RELEASE_SCENARIO_SUITES",
        {
            "test_suite": (
                AmongUsReleaseScenario(
                    name="scenario_pass",
                    episodes=2,
                    num_agents=8,
                    max_steps=100,
                    gate_profile="baseline",
                    end_on_winner=False,
                ),
                AmongUsReleaseScenario(
                    name="scenario_fail",
                    episodes=2,
                    num_agents=8,
                    max_steps=100,
                    gate_profile="ship_strict",
                    end_on_winner=False,
                ),
            )
        },
    )

    def _fake_run_headless_audit(**kwargs):
        del kwargs
        return {"coverage": {}, "winners": {}, "role_adoption": {}, "completion_rate": 1.0, "sps": {"mean": 999.0}}

    def _fake_evaluate_headless_audit_gate(audit, *, profile, thresholds):
        del audit, thresholds
        passed = profile == "baseline"
        checks = [{"name": "winner_rates.impostor", "passed": passed, "value": 0.2}]
        return {"profile": profile, "passed": passed, "failed_count": 0 if passed else 1, "checks": checks}

    monkeypatch.setattr(among_us_headless, "run_headless_audit", _fake_run_headless_audit)
    monkeypatch.setattr(among_us_headless, "evaluate_headless_audit_gate", _fake_evaluate_headless_audit_gate)

    suite = run_headless_release_suite(suite_name="test_suite", min_pass_rate=1.0, include_audits=False)
    assert suite["passed"] is False
    assert suite["pass_rate"] == 0.5
    assert any("scenario_fail" in failure for failure in suite["failures"])  # type: ignore[index]
