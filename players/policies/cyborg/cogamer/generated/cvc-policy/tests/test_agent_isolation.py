"""Verify that CvCPolicy agents have no shared mutable state.

Each agent must own its own mutable objects (junctions, claims, world model, etc.).
Sharing mutable state between agents is a bug — this test catches it via id() checks.
"""

from __future__ import annotations

from cvc_policy.cogamer_policy import CvCPolicy
from mettagrid.policy.policy_env_interface import PolicyEnvInterface


def _make_policy_env_info() -> PolicyEnvInterface:
    return PolicyEnvInterface(
        action_names=["noop", "move_north", "move_south", "move_east", "move_west"],
        vibe_action_names=["change_vibe_default"],
        num_agents=2,
        observation_shape=(10, 3),
        egocentric_shape=(5, 5),
    )


def test_agents_share_no_mutable_state():
    """Two agents created by CvCPolicy must not share any mutable objects."""
    env_info = _make_policy_env_info()
    policy = CvCPolicy(env_info, device="cpu")

    wrapper_0 = policy.agent_policy(0)
    wrapper_1 = policy.agent_policy(1)

    # Force state initialization
    state_0 = wrapper_0._base_policy.initial_agent_state()
    state_1 = wrapper_1._base_policy.initial_agent_state()

    gs_0 = state_0.game_state
    gs_1 = state_1.game_state
    assert gs_0 is not None and gs_1 is not None

    engine_0 = gs_0.engine
    engine_1 = gs_1.engine

    # Core mutable dicts must be distinct objects
    assert id(engine_0._junctions) != id(engine_1._junctions), "agents share _junctions dict"
    assert id(engine_0._temp_blocks) != id(engine_1._temp_blocks), "agents share _temp_blocks dict"

    # World models must be distinct
    assert id(engine_0._world_model) != id(engine_1._world_model), "agents share _world_model"

    # Mutable collections on CvCAgentState must be distinct
    assert id(state_0.llm_latencies) != id(state_1.llm_latencies), "agents share llm_latencies"
    assert id(state_0.llm_log) != id(state_1.llm_log), "agents share llm_log"
