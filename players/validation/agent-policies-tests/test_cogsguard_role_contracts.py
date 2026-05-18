from __future__ import annotations

import pytest
from policies.scripted.cogsguard.scripted_agent.cogsguard.policy import CogsguardPolicy

from mettagrid.policy.policy_env_interface import PolicyEnvInterface


def _policy_env_info(*, num_agents: int) -> PolicyEnvInterface:
    action_names = [
        "noop",
        "move_north",
        "move_south",
        "move_east",
        "move_west",
    ]
    vibe_action_names = [
        "change_vibe_default",
        "change_vibe_gear",
        "change_vibe_miner",
        "change_vibe_scout",
        "change_vibe_aligner",
        "change_vibe_scrambler",
    ]
    return PolicyEnvInterface(
        obs_features=[],
        tags=["agent", "hub", "junction"],
        action_names=action_names,
        vibe_action_names=vibe_action_names,
        num_agents=num_agents,
        observation_shape=(1, 1),
        egocentric_shape=(5, 5),
    )


@pytest.mark.parametrize(
    ("num_agents", "policy_kwargs", "expected_vibes", "smart_role_enabled"),
    [
        pytest.param(
            4,
            {"role_order": "miner,scout,aligner,scrambler"},
            ["miner", "scout", "aligner", "scrambler"],
            False,
            id="static-role-order",
        ),
        pytest.param(
            3,
            {"role_order": "scout,aligner,scrambler"},
            ["scout", "aligner", "scrambler"],
            False,
            id="truncated-static-role-order",
        ),
        pytest.param(
            4,
            {"gear": 4},
            ["gear", "gear", "gear", "gear"],
            True,
            id="gear-mode",
        ),
    ],
)
def test_policy_contracts_reflect_initial_vibes(
    num_agents: int,
    policy_kwargs: dict[str, str | int],
    expected_vibes: list[str],
    smart_role_enabled: bool,
) -> None:
    env = _policy_env_info(num_agents=num_agents)
    policy = CogsguardPolicy(env, **policy_kwargs)

    assert policy._initial_vibes == expected_vibes
    for agent_id, expected_vibe in enumerate(expected_vibes):
        agent = policy.agent_policy(agent_id)
        impl = agent._base_policy
        assert impl._initial_target_vibe == expected_vibe
        assert impl._smart_role_enabled is smart_role_enabled
