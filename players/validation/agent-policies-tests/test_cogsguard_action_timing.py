from __future__ import annotations

from types import SimpleNamespace

import pytest
from policies.scripted.cogsguard.scripted_agent.cogsguard.policy import CogsguardAgentPolicyImpl
from policies.scripted.cogsguard.scripted_agent.cogsguard.types import CogsguardAgentState, Role
from policies.scripted.cogsguard.scripted_agent.types import CellType

from mettagrid.policy.policy_env_interface import PolicyEnvInterface
from mettagrid.simulator import Action


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


def _make_state(
    *,
    map_size: int = 5,
    row: int = 2,
    col: int = 2,
) -> CogsguardAgentState:
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


@pytest.mark.parametrize(
    ("last_action_name", "last_action_executed", "expected_position"),
    [
        pytest.param("move_north", "move_south", (3, 2), id="uses-executed-action"),
        pytest.param("move_east", None, (2, 3), id="falls-back-to-intended-action"),
    ],
)
def test_update_agent_position(
    policy_env_info: PolicyEnvInterface,
    last_action_name: str,
    last_action_executed: str | None,
    expected_position: tuple[int, int],
) -> None:
    policy = CogsguardAgentPolicyImpl(policy_env_info, agent_id=0, role=Role.MINER)
    state = _make_state()

    state.last_action = Action(name=last_action_name)
    state.last_action_executed = last_action_executed

    policy._update_agent_position(state)

    assert (state.row, state.col) == expected_position


def test_read_inventory_parses_last_action_without_center_location(
    policy_env_info: PolicyEnvInterface,
) -> None:
    policy = CogsguardAgentPolicyImpl(policy_env_info, agent_id=0, role=Role.MINER)
    state = _make_state()

    def _token(name: str, value: int, *, location: tuple[int, int] | None, normalization: int = 1) -> object:
        return SimpleNamespace(
            location=location,
            value=value,
            feature=SimpleNamespace(name=name, normalization=normalization),
        )

    obs = SimpleNamespace(
        tokens=[
            _token("vibe", 0, location=(1, 1)),
            _token("last_action", 2, location=None),
            _token("inv:energy", 100, location=(1, 1)),
        ]
    )

    policy._read_inventory(state, obs)  # type: ignore[arg-type]

    assert state.last_action_executed == "move_south"
