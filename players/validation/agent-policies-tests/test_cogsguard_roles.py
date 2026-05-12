from __future__ import annotations

import pytest
from agent_policies.policies.scripted.cogsguard.scripted_agent.cogsguard.aligner import AlignerAgentPolicyImpl
from agent_policies.policies.scripted.cogsguard.scripted_agent.cogsguard.miner import MinerAgentPolicyImpl
from agent_policies.policies.scripted.cogsguard.scripted_agent.cogsguard.policy import CogsguardAgentPolicyImpl
from agent_policies.policies.scripted.cogsguard.scripted_agent.cogsguard.scout import ScoutAgentPolicyImpl
from agent_policies.policies.scripted.cogsguard.scripted_agent.cogsguard.scrambler import ScramblerAgentPolicyImpl
from agent_policies.policies.scripted.cogsguard.scripted_agent.cogsguard.types import (
    CogsguardAgentState,
    Role,
    StructureInfo,
    StructureType,
)
from agent_policies.policies.scripted.cogsguard.scripted_agent.types import CellType

from mettagrid.policy.policy_env_interface import PolicyEnvInterface


@pytest.fixture
def policy_env_info() -> PolicyEnvInterface:
    return PolicyEnvInterface(
        obs_features=[],
        tags=["team:cogs", "team:clips", "hub", "junction"],
        action_names=["noop", "move_north", "move_south", "move_east", "move_west"],
        vibe_action_names=[],
        num_agents=1,
        observation_shape=(1, 1),
        egocentric_shape=(3, 3),
    )


def _make_state(
    role: Role,
    *,
    map_size: int = 5,
    row: int = 2,
    col: int = 2,
) -> CogsguardAgentState:
    occupancy = [[CellType.FREE.value] * map_size for _ in range(map_size)]
    explored = [[False] * map_size for _ in range(map_size)]
    return CogsguardAgentState(
        agent_id=1,
        role=role,
        map_height=map_size,
        map_width=map_size,
        occupancy=occupancy,
        explored=explored,
        row=row,
        col=col,
    )


def test_alignment_uses_team_tags(policy_env_info: PolicyEnvInterface) -> None:
    policy = CogsguardAgentPolicyImpl(policy_env_info, agent_id=0, role=Role.MINER)

    assert (
        policy._derive_alignment(
            "junction",
            StructureType.CHARGER,
            tags=["team:cogs"],
        )
        == "cogs"
    )
    assert (
        policy._derive_alignment(
            "junction",
            StructureType.CHARGER,
            tags=["team:clips"],
        )
        == "clips"
    )
    assert (
        policy._derive_alignment(
            "junction",
            StructureType.CHARGER,
            tags=[],
        )
        is None
    )


def test_aligner_does_not_require_influence_before_aligning(policy_env_info: PolicyEnvInterface) -> None:
    policy = AlignerAgentPolicyImpl(policy_env_info, agent_id=0, role=Role.ALIGNER)
    state = _make_state(Role.ALIGNER)

    state.aligner = 1
    state.heart = 1
    state.influence = 0
    state.structures[(state.row, state.col + 1)] = StructureInfo(
        position=(state.row, state.col + 1),
        structure_type=StructureType.HUB,
        name="hub",
        alignment="cogs",
    )
    state.structures[(state.row, state.col - 1)] = StructureInfo(
        position=(state.row, state.col - 1),
        structure_type=StructureType.CHARGER,
        name="junction",
        alignment=None,
    )

    action = policy.execute_role(state)

    assert action.name != "noop"


def test_scrambler_prioritizes_clips_junctions(policy_env_info: PolicyEnvInterface) -> None:
    policy = ScramblerAgentPolicyImpl(policy_env_info, agent_id=0, role=Role.SCRAMBLER)
    state = _make_state(Role.SCRAMBLER, map_size=10, row=0, col=0)

    state.structures[(1, 0)] = StructureInfo(
        position=(1, 0),
        structure_type=StructureType.CHARGER,
        name="junction",
        alignment=None,
    )
    state.structures[(4, 0)] = StructureInfo(
        position=(4, 0),
        structure_type=StructureType.CHARGER,
        name="junction",
        alignment="clips",
    )

    assert policy._find_best_target(state) == (4, 0)


def test_scout_moves_to_frontier(policy_env_info: PolicyEnvInterface) -> None:
    policy = ScoutAgentPolicyImpl(policy_env_info, agent_id=0, role=Role.SCOUT)
    state = _make_state(Role.SCOUT, map_size=3, row=1, col=1)

    state.explored[1][1] = True

    action = policy.execute_role(state)

    assert action.name == "move_north"


def test_miner_prefers_nearest_aligned_depot(policy_env_info: PolicyEnvInterface) -> None:
    policy = MinerAgentPolicyImpl(policy_env_info, agent_id=0, role=Role.MINER)
    state = _make_state(Role.MINER, map_size=10, row=0, col=0)

    state.structures[(0, 5)] = StructureInfo(
        position=(0, 5),
        structure_type=StructureType.HUB,
        name="hub",
        alignment="cogs",
    )
    state.structures[(0, 2)] = StructureInfo(
        position=(0, 2),
        structure_type=StructureType.CHARGER,
        name="junction",
        alignment="cogs",
    )

    assert policy._get_nearest_aligned_depot(state) == (0, 2)
