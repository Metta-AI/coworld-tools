from __future__ import annotations

from typing import TypedDict

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

# Ensure scripted policy registration in test process.
discover_and_register_policies("players.cogsguard")

DETERMINISM_CASES: tuple[tuple[type, int, int], ...] = (
    (PlankyMinerGear, 100, 11),
    (PlankyScoutExplore, 120, 23),
    (PlankyScramblerTarget, 140, 42),
    (PlankyMultiRole, 120, 42),
)


class EpisodeSignature(TypedDict):
    steps: int
    rewards: list[float]
    stats: dict[str, object]


def _run_episode_signature(
    mission_cls: type,
    *,
    max_steps: int,
    seed: int,
    init_kwargs: dict[str, int],
) -> EpisodeSignature:
    mission = mission_cls()
    env_cfg = mission.make_env()
    env_cfg.game.max_steps = max_steps

    spec = PolicySpec(class_path="role", data_path=None, init_kwargs=init_kwargs)
    results, _replay = run_episode_local(
        policy_specs=[spec],
        assignments=[0] * env_cfg.game.num_agents,
        env=env_cfg,
        seed=seed,
        device="cpu",
        render_mode="none",
    )
    return {
        "steps": int(results.steps),
        "rewards": [float(r) for r in results.rewards],
        "stats": results.stats,
    }


@pytest.mark.parametrize(("mission_cls", "max_steps", "seed"), DETERMINISM_CASES)
def test_role_deterministic_across_seed_mission_matrix(
    mission_cls: type,
    max_steps: int,
    seed: int,
) -> None:
    first = _run_episode_signature(mission_cls, max_steps=max_steps, seed=seed, init_kwargs={"gear": 1})
    second = _run_episode_signature(mission_cls, max_steps=max_steps, seed=seed, init_kwargs={"gear": 1})

    assert first == second
