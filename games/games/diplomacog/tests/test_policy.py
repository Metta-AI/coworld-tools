from mettagrid.policy.policy_env_interface import PolicyEnvInterface
from mettagrid.simulator.interface import AgentObservation

from diplomacog import make_diplomacog_env
from diplomacog.agent.diplomacy_agent.policy import (
    DiplomacyAgentState,
    DiplomacyBrain,
    DiplomacyObservation,
)


def test_diplomacog_env_defaults_to_colored_supply_centers() -> None:
    env = make_diplomacog_env(num_agents=6, max_steps=40, variants=["discussion_sessions"])

    assets = env.game.render.assets["supply_center"]
    assert [asset.asset for asset in assets] == [
        "diplomacy/stamp.country_a",
        "diplomacy/stamp.country_b",
        "diplomacy/stamp.country_c",
        "diplomacy/stamp.supply_center",
    ]
    assert env.game.render.object_status["supply_center"]["capture_window"].short_name == "FALL"
    assert env.game.talk.cooldown_steps == 1


def test_diplomacog_policy_marks_phase_transitions_with_overlay() -> None:
    env = make_diplomacog_env(num_agents=2, max_steps=40, variants=["discussion_sessions"])
    env_info = PolicyEnvInterface.from_mg_cfg(env)
    brain = DiplomacyBrain(env_info, agent_id=0)
    state = DiplomacyAgentState(agent_id=0, assigned_country="country_a", style="diplomat")
    state.last_phase_label = "Spring Discussion"
    state.last_center_snapshot = (1, 1, 1)
    obs = DiplomacyObservation(
        position=(100, 100),
        inventory={"country_a": 1},
        global_obs={
            "campaign_year": 1901,
            "season_fall": 1,
            "phase_orders": 1,
            "country_a.centers": 1,
            "country_b.centers": 1,
            "country_c.centers": 1,
        },
        visible_entities={},
    )
    brain._parse_observation = lambda _raw, _state: obs  # type: ignore[method-assign]

    brain.step_with_state(AgentObservation(agent_id=0, tokens=[]), state)

    assert brain._infos["tutorial_overlay"] == (
        "1901 Fall Orders\nOrders are live. Fall Orders is the only phase where supply centers can change hands."
    )


def test_diplomacog_policy_marks_supply_center_swings_with_overlay() -> None:
    env = make_diplomacog_env(num_agents=2, max_steps=40, variants=["discussion_sessions"])
    env_info = PolicyEnvInterface.from_mg_cfg(env)
    brain = DiplomacyBrain(env_info, agent_id=0)
    state = DiplomacyAgentState(agent_id=0, assigned_country="country_a", style="diplomat")
    state.last_phase_label = "Fall Orders"
    state.last_center_snapshot = (1, 1, 1)
    obs = DiplomacyObservation(
        position=(100, 100),
        inventory={"country_a": 1},
        global_obs={
            "campaign_year": 1901,
            "season_fall": 1,
            "phase_orders": 1,
            "country_a.centers": 2,
            "country_b.centers": 1,
            "country_c.centers": 0,
        },
        visible_entities={},
    )
    brain._parse_observation = lambda _raw, _state: obs  # type: ignore[method-assign]

    brain.step_with_state(AgentObservation(agent_id=0, tokens=[]), state)

    assert brain._infos["tutorial_overlay"] == "Supply Center Captured\nA +1  C -1"


def test_diplomacog_policy_keeps_agents_at_summit_during_opening_discussion_beats() -> None:
    env = make_diplomacog_env(num_agents=2, max_steps=40, variants=["discussion_sessions"])
    env_info = PolicyEnvInterface.from_mg_cfg(env)
    brain = DiplomacyBrain(env_info, agent_id=0)
    state = DiplomacyAgentState(agent_id=0, assigned_country="country_a", style="diplomat")
    state.post_discussion_target = "country_b_hub"
    state.discussion_steps_in_window = 2

    target = brain._choose_target_type(
        DiplomacyObservation(
            position=(100, 100),
            inventory={"country_a": 1},
            global_obs={"season_spring": 1, "phase_orders": 1, "phase_discussion": 1},
            visible_entities={},
        ),
        state,
    )

    assert target == "diplomacy_station"
