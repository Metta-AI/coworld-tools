from __future__ import annotations

import importlib.util
import sys
from functools import cache
from pathlib import Path

from agent_policies.tools.eval.cogsguard.evals.planky_evals import PlankyMultiRole

from mettagrid.policy.loader import discover_and_register_policies
from mettagrid.policy.policy import PolicySpec

discover_and_register_policies("policies.scripted.cogsguard")

SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "run_scripted_baselines_report.py"


@cache
def _load_report_module():
    spec = importlib.util.spec_from_file_location("test_run_scripted_baselines_report", SCRIPT_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@cache
def _gap_filler_role_switch_metrics(*, seed: int = 42, max_steps: int = 240):
    report = _load_report_module()
    mission = PlankyMultiRole()
    env_cfg = mission.make_env()
    env_cfg.game.max_steps = max_steps
    policy_spec = PolicySpec(class_path="role", data_path=None, init_kwargs={"gear": 4})

    return report._run_episode_local_with_role_switches(
        policy_spec=policy_spec,
        env_cfg=env_cfg,
        seed=seed,
        device="cpu",
    )


def test_gap_filler_ignores_startup_role_assignment_transitions() -> None:
    results, role_switch_events, transitions = _gap_filler_role_switch_metrics()
    startup_transitions = transitions[:4]

    assert [(transition.step, transition.agent_id) for transition in startup_transitions] == [
        (3, 0),
        (3, 1),
        (3, 2),
        (3, 3),
    ]
    assert [
        (transition.previous_role, transition.current_role, transition.counted) for transition in startup_transitions
    ] == [
        (None, "scout", False),
        (None, "miner", False),
        (None, "aligner", False),
        (None, "scrambler", False),
    ]
    assert role_switch_events == sum(1.0 for transition in transitions if transition.counted)
    assert results.time_averaged_game_stats


def test_scripted_report_uses_true_role_switches_for_gap_filler() -> None:
    report = _load_report_module()
    results, role_switch_events, _transitions = _gap_filler_role_switch_metrics()
    target = next(target for target in report.TARGETS if target.key == "adaptive_gap_filler")

    run = report._run_target_seed(target, seed=42)
    role_switch_check = next(
        check for check in run["thresholds"]["kpis"]["checks"] if check["metric"] == "role_switch_events"
    )
    vibe_change_events = sum(
        float(agent.get("action.change_vibe.success", 0.0)) for agent in (results.stats.get("agent") or [])
    )

    assert run["kpis"]["role_switch_events"] == role_switch_events
    assert role_switch_check["value"] == role_switch_events
    assert run["kpis"]["role_switch_events"] < vibe_change_events
    assert role_switch_check["pass"] is True


def test_collect_role_conditional_reward_keys_supports_current_cvc_mission_api() -> None:
    report = _load_report_module()
    reward_keys_by_role = report._collect_role_conditional_reward_keys()

    assert set(reward_keys_by_role) == set(report.SHAPED_REWARD_ALIGNMENT_RULES)
    assert "gain_diversity" in reward_keys_by_role["miner"]
    assert "junction_aligned_by_agent" in reward_keys_by_role["aligner"]
    assert "junction_scrambled_by_agent" in reward_keys_by_role["scrambler"]
    assert "cell_visited" in reward_keys_by_role["scout"]


def test_shaped_reward_alignment_audit_uses_current_mission_api() -> None:
    report = _load_report_module()

    shaped_reward_alignment = report._compute_shaped_reward_alignment()

    assert shaped_reward_alignment["overall_pass"] is True
    assert shaped_reward_alignment["roles_passing"] == shaped_reward_alignment["total_roles"]
