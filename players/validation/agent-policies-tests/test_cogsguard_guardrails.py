from __future__ import annotations

import pytest
from agent_policies.tools.eval.cogsguard.evals.planky_evals import (
    PlankyMinerGear,
    PlankyMultiRole,
    PlankyScoutExplore,
    PlankyScramblerTarget,
)

from mettagrid.policy.loader import discover_and_register_policies
from mettagrid.policy.policy import PolicySpec
from mettagrid.runner.rollout import run_episode_local

# CI smoke coverage for scripted teammate reliability checks. The full stable
# acceptance matrix belongs in the stable-check jobs, not every Python CI run.
ACCEPTANCE_CASES: tuple[tuple[type, int, int], ...] = (
    (PlankyMinerGear, 100, 11),
    (PlankyScoutExplore, 120, 23),
    (PlankyScramblerTarget, 140, 42),
    (PlankyMultiRole, 120, 42),
)
MAX_MOVE_FAIL_RATE = 0.25
MAX_NOOP_RATE = 0.40

# Ensure scripted policy registration in test process.
discover_and_register_policies("agent_policies.policies.scripted.cogsguard")


def _run_role_episode(mission_cls: type, *, max_steps: int, seed: int) -> tuple[int, list[dict[str, float]]]:
    mission = mission_cls()
    env_cfg = mission.make_env()
    env_cfg.game.max_steps = max_steps

    spec = PolicySpec(class_path="role", data_path=None, init_kwargs={"gear": 1})
    results, _replay = run_episode_local(
        policy_specs=[spec],
        assignments=[0] * env_cfg.game.num_agents,
        env=env_cfg,
        seed=seed,
        device="cpu",
        render_mode="none",
    )

    agent_stats = [dict(stats) for stats in (results.stats.get("agent") or [])]
    return int(results.steps), agent_stats


@pytest.mark.parametrize(("mission_cls", "max_steps", "seed"), ACCEPTANCE_CASES)
def test_role_guardrails_hold_on_week1_acceptance_matrix(
    mission_cls: type,
    max_steps: int,
    seed: int,
) -> None:
    steps, agent_stats = _run_role_episode(mission_cls, max_steps=max_steps, seed=seed)

    assert steps == max_steps
    assert agent_stats

    for stats in agent_stats:
        move_success = float(stats.get("action.move.success", 0.0))
        move_failed = float(stats.get("action.move.failed", 0.0))
        noop_success = float(stats.get("action.noop.success", 0.0))
        timeout_count = float(stats.get("action.timeout", 0.0))

        total_actions = max(1.0, move_success + move_failed + noop_success)
        move_fail_rate = move_failed / total_actions
        noop_rate = noop_success / total_actions

        assert timeout_count == 0.0
        assert move_success > 0.0
        assert move_fail_rate <= MAX_MOVE_FAIL_RATE
        assert noop_rate <= MAX_NOOP_RATE
