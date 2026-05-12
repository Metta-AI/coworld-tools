"""Smoke tests for scripted policies implemented in Nim and Python.

These tests ensure scripted agents can 1) act as supervisor teachers inside the
training environment and 2) run through a short `cogames.play` rollout. This
prevents regressions like missing bindings or policy registration mistakes.
"""

import io
from dataclasses import dataclass
from functools import cache

import numpy as np
import pytest
from rich.console import Console

from cogames.cli.mission import get_mission
from cogames.cli.policy import PolicySpecWithProportion
from cogames.play import play as play_episode
from mettagrid.envs.mettagrid_puffer_env import MettaGridPufferEnv
from mettagrid.policy.loader import discover_and_register_policies
from mettagrid.policy.policy import PolicySpec
from mettagrid.runner.rollout import run_episode_local
from mettagrid.simulator import Simulator


@dataclass(frozen=True)
class PolicyUnderTest:
    reference: str
    requires_nim: bool = False
    supports_supervisor: bool = False


# Policy discovery imports a large surface area and may mutate module state.
# Keep it below the module-level dataclass definitions to avoid subtle
# interpreter/pytest import-mode interactions during collection.
discover_and_register_policies("cogames.policy")
discover_and_register_policies("agent_policies.policies.scripted.cogsguard")


@cache
def _nim_bindings_available() -> bool:
    try:
        import agent_policies.policies.scripted.cogsguard.nim_agents.agents as _  # noqa: F401, PLC0415
    except ModuleNotFoundError:
        return False
    return True


POLICIES_UNDER_TEST: tuple[PolicyUnderTest, ...] = (
    PolicyUnderTest("thinky", requires_nim=True, supports_supervisor=True),
    PolicyUnderTest("nim_random", requires_nim=True, supports_supervisor=True),
    PolicyUnderTest("race_car", requires_nim=True, supports_supervisor=True),
    PolicyUnderTest("role", requires_nim=True, supports_supervisor=True),
    PolicyUnderTest("alignall", requires_nim=True, supports_supervisor=True),
    PolicyUnderTest("nlanky", requires_nim=True, supports_supervisor=True),
    PolicyUnderTest("teacher", requires_nim=True, supports_supervisor=True),
    PolicyUnderTest("starter"),
    PolicyUnderTest("buggy"),
    PolicyUnderTest("cranky"),
    PolicyUnderTest(
        "agent_policies.policies.scripted.cogsguard.nim_agents.agents.ThinkyAgentsMultiPolicy",
        requires_nim=True,
        supports_supervisor=True,
    ),
    PolicyUnderTest(
        "agent_policies.policies.scripted.cogsguard.nim_agents.agents.RandomAgentsMultiPolicy",
        requires_nim=True,
        supports_supervisor=True,
    ),
    PolicyUnderTest(
        "agent_policies.policies.scripted.cogsguard.nim_agents.agents.RaceCarAgentsMultiPolicy",
        requires_nim=True,
        supports_supervisor=True,
    ),
    PolicyUnderTest(
        "agent_policies.policies.scripted.cogsguard.nim_agents.agents.CogsguardAgentsMultiPolicy",
        requires_nim=True,
        supports_supervisor=True,
    ),
    PolicyUnderTest(
        "agent_policies.policies.scripted.cogsguard.nim_agents.agents.NlankyAgentsMultiPolicy",
        requires_nim=True,
        supports_supervisor=True,
    ),
    PolicyUnderTest(
        "agent_policies.policies.scripted.cogsguard.scripted_agent.cogsguard.teacher.CogsguardTeacherPolicy",
        requires_nim=True,
        supports_supervisor=True,
    ),
    PolicyUnderTest("cogames.policy.starter_agent.StarterPolicy"),
)

SUPERVISOR_POLICIES: tuple[PolicyUnderTest, ...] = tuple(p for p in POLICIES_UNDER_TEST if p.supports_supervisor)


def _policy_param(policy: PolicyUnderTest):  # -> pytest.ParameterSet
    marks = ()
    if policy.requires_nim and not _nim_bindings_available():
        marks = pytest.mark.skip(
            "Nim bindings missing. Run `nim c nim_agents.nim` in src/agent_policies/policies/scripted/cogsguard/nim_agents."
        )
    policy_id = policy.reference.replace("cogames.policy.", "").replace("agent_policies.policies.scripted.cogsguard.", "").replace(".", "_")
    return pytest.param(policy, id=policy_id, marks=marks)


POLICY_PARAMS = tuple(_policy_param(policy) for policy in POLICIES_UNDER_TEST)
SUPERVISOR_PARAMS = tuple(_policy_param(policy) for policy in SUPERVISOR_POLICIES)


@pytest.fixture(scope="module")
def simulator() -> Simulator:
    return Simulator()


@pytest.fixture
def env_config():
    _, env_cfg, _ = get_mission("evals.diagnostic_chest_navigation1", variants_arg=None, cogs=2)
    env_cfg.game.max_steps = 8
    return env_cfg


@pytest.mark.parametrize("policy", SUPERVISOR_PARAMS)
def test_scripted_policies_work_as_supervisors(policy: PolicyUnderTest, simulator: Simulator, env_config) -> None:
    """Supervisor policies must load and generate teacher actions for training."""

    env = MettaGridPufferEnv(simulator, env_config, supervisor_policy_spec=PolicySpec(class_path=policy.reference))
    try:

        def assert_split_action_supervisor_outputs() -> None:
            teacher_actions = env.teacher_actions
            assert teacher_actions.shape == (env_config.game.num_agents,)

            num_primary_actions = len(env._policy_env_info.action_names)
            num_vibe_actions = len(env._policy_env_info.vibe_action_names)
            full_action_count = num_primary_actions + num_vibe_actions

            teacher_actions_i64 = teacher_actions.astype(np.int64, copy=False)
            assert bool((teacher_actions_i64 >= 0).all())
            assert bool((teacher_actions_i64 < full_action_count).all())

            # For vibe labels, env.vibe_actions must contain simulator action ids
            # mapped from split-action vibe indices.
            expected_vibe_actions = np.zeros_like(teacher_actions, dtype=np.int32)
            if num_vibe_actions > 0:
                assert env._sim is not None
                vibe_action_ids_by_index = np.array(
                    [env._sim.action_names.index(name) for name in env._policy_env_info.vibe_action_names],
                    dtype=np.int32,
                )
                vibe_mask = teacher_actions_i64 >= num_primary_actions
                vibe_indices = teacher_actions_i64[vibe_mask] - num_primary_actions
                expected_vibe_actions[vibe_mask] = vibe_action_ids_by_index[vibe_indices]

            np.testing.assert_array_equal(env.vibe_actions, expected_vibe_actions)

        observations, _ = env.reset(seed=123)
        assert observations.shape[0] == env_config.game.num_agents

        assert_split_action_supervisor_outputs()

        assert env._sim is not None
        noop_idx = env._sim.action_names.index("noop")
        noop_actions = np.full(env_config.game.num_agents, noop_idx, dtype=np.int32)

        next_obs, rewards, terminals, truncations, _ = env.step(noop_actions)
        assert next_obs.shape == observations.shape
        assert rewards.shape == (env_config.game.num_agents,)
        assert terminals.shape == (env_config.game.num_agents,)
        assert truncations.shape == (env_config.game.num_agents,)
        assert_split_action_supervisor_outputs()
    finally:
        env.close()


@pytest.mark.parametrize("policy", POLICY_PARAMS)
def test_scripted_policies_can_play_short_episode(policy: PolicyUnderTest, env_config) -> None:
    """Policies should run through a short cogames.play session."""

    console = Console(file=io.StringIO(), force_terminal=False, soft_wrap=True, width=80)
    policy_spec = PolicySpecWithProportion(class_path=policy.reference, data_path=None)

    play_episode(
        console=console,
        env_cfg=env_config,
        policy_specs=[policy_spec],
        game_name="diagnostic_chest_navigation1",
        seed=42,
        render_mode="none",
    )


@pytest.mark.skipif(
    not _nim_bindings_available(),
    reason=("Nim bindings missing. Run `nim c nim_agents.nim` in src/agent_policies/policies/scripted/cogsguard/nim_agents."),
)
@pytest.mark.skip(reason="Flaky on CI: nlanky Machina smoke test is nondeterministic.")
def test_nlanky_aligns_junctions_in_machina() -> None:
    _, env_cfg, _ = get_mission("machina_1", variants_arg=None, cogs=None)
    env_cfg.game.max_steps = 200
    results, _ = run_episode_local(
        policy_specs=[PolicySpec(class_path="nlanky", data_path=None)],
        assignments=[0] * env_cfg.game.num_agents,
        env=env_cfg,
        seed=42,
        device="cpu",
        render_mode="none",
    )
    agent_stats = results.stats.get("agent", [])
    aligned_total = sum(float(stats.get("junction.aligned_by_agent", 0.0)) for stats in agent_stats)
    assert aligned_total > 0.0, f"Expected nlanky to align at least one junction, got stats={agent_stats}"
