from __future__ import annotations

import pytest
from policies.scripted.cogsguard.scripted_agent.cogsguard.miner import MinerAgentPolicyImpl
from policies.scripted.cogsguard.scripted_agent.cogsguard.types import CogsguardAgentState, Role, StructureInfo, StructureType
from policies.scripted.cogsguard.scripted_agent.types import CellType

from mettagrid.policy.policy_env_interface import PolicyEnvInterface


@pytest.fixture
def policy_env_info() -> PolicyEnvInterface:
    return PolicyEnvInterface(
        obs_features=[],
        tags=[],
        action_names=["noop", "move_north", "move_south", "move_east", "move_west"],
        vibe_action_names=[],
        num_agents=1,
        observation_shape=(1, 1),
        egocentric_shape=(3, 3),
    )


def _make_state(*, map_size: int = 30, row: int = 0, col: int = 0) -> CogsguardAgentState:
    occupancy = [[CellType.FREE.value] * map_size for _ in range(map_size)]
    explored = [[False] * map_size for _ in range(map_size)]
    return CogsguardAgentState(
        agent_id=0,
        role=Role.MINER,
        map_height=map_size,
        map_width=map_size,
        occupancy=occupancy,
        explored=explored,
        row=row,
        col=col,
    )


def test_miner_prefers_extractor_outside_danger_radius(policy_env_info: PolicyEnvInterface) -> None:
    policy = MinerAgentPolicyImpl(policy_env_info, agent_id=0, role=Role.MINER)
    state = _make_state()
    state.hp = 100

    state.structures[(0, 0)] = StructureInfo(
        position=(0, 0),
        structure_type=StructureType.CHARGER,
        name="junction",
        alignment="clips",
    )
    state.structures[(0, 5)] = StructureInfo(
        position=(0, 5),
        structure_type=StructureType.EXTRACTOR,
        name="carbon_extractor",
        resource_type="carbon",
        inventory_amount=10,
    )
    state.structures[(0, 10)] = StructureInfo(
        position=(0, 10),
        structure_type=StructureType.EXTRACTOR,
        name="carbon_extractor",
        resource_type="carbon",
        inventory_amount=10,
    )

    extractor = policy._get_safe_extractor(state)

    assert extractor is not None
    assert extractor.position == (0, 10)
