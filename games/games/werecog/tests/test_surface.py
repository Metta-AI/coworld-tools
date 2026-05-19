from __future__ import annotations

import pytest

pytest.importorskip("mettagrid_sdk")

from mettagrid_sdk.runtime.observation import ObservationEnvelope
from werecog import make_game
from werecog.sdk import (
    WerewolfHelperCatalog,
    WerewolfMafiaPromptAdapter,
    WerewolfMafiaSemanticSurface,
    WerewolfMafiaStateAdapter,
)

from mettagrid.policy.policy_env_interface import PolicyEnvInterface
from mettagrid.simulator.interface import AgentObservation, Location, VisibleTalk
from mettagrid.simulator.simulator import Simulation


def test_werewolf_mafia_state_adapter_handles_live_observation() -> None:
    env = make_game("werewolf_mafia", num_agents=8, max_steps=120)
    policy_env_info = PolicyEnvInterface.from_mg_cfg(env)
    sim = Simulation(env)
    adapter = WerewolfMafiaStateAdapter()

    state = adapter.build_state(
        ObservationEnvelope(
            raw_observation=sim.agent(0).observation,
            policy_env_info=policy_env_info,
            step=1,
        )
    )

    assert state.game == "werecog"
    assert state.self_state.role in {"werewolf", "villager"}
    assert {"day", "night"} & set(state.self_state.status)
    assert state.team_summary is not None
    assert state.team_summary.team_id in {"werewolves", "village"}
    assert any(entity.entity_type in {"agent", "meeting_bell"} for entity in state.visible_entities)


def test_werewolf_mafia_surface_turns_visible_talk_into_events() -> None:
    env = make_game("werewolf_mafia", num_agents=8, max_steps=120)
    policy_env_info = PolicyEnvInterface.from_mg_cfg(env)
    sim = Simulation(env)
    surface = WerewolfMafiaSemanticSurface()
    observation = sim.agent(0).observation

    state = surface.build_state_with_events(
        AgentObservation(
            agent_id=observation.agent_id,
            tokens=observation.tokens,
            talk=[
                VisibleTalk(
                    agent_id=3,
                    text="vote agent 2",
                    location=Location(0, 0),
                    remaining_steps=6,
                )
            ],
        ),
        policy_env_info=policy_env_info,
        step=7,
    )

    assert any(event.event_type == "heard_speech" for event in state.recent_events)
    assert any("vote agent 2" in event.summary for event in state.recent_events)


def test_werewolf_helper_catalog_reads_phase_calls_and_packmates() -> None:
    env = make_game("werewolf_mafia", num_agents=8, max_steps=120)
    policy_env_info = PolicyEnvInterface.from_mg_cfg(env)
    sim = Simulation(env)
    surface = WerewolfMafiaSemanticSurface()
    observation = sim.agent(0).observation
    state = surface.build_state_with_events(
        AgentObservation(
            agent_id=observation.agent_id,
            tokens=observation.tokens,
            talk=[
                VisibleTalk(
                    agent_id=3,
                    text="agent 2 feels off, vote agent 2",
                    location=Location(0, 0),
                    remaining_steps=6,
                ),
                VisibleTalk(
                    agent_id=4,
                    text="pack should focus agent 1, hunt agent 1",
                    location=Location(0, 0),
                    remaining_steps=6,
                ),
            ],
        ),
        policy_env_info=policy_env_info,
        step=7,
    )

    helpers = WerewolfHelperCatalog(state)
    speech_events = helpers.heard_speech_events()

    assert helpers.phase() in {"day", "night"}
    assert helpers.called_player_ids("vote") == ["agent-2"]
    assert helpers.called_player_ids("hunt") == ["agent-1"]
    assert helpers.called_player_ids() == ["agent-2", "agent-1"]
    assert helpers.heard_speech() == [
        "agent 2 feels off, vote agent 2",
        "pack should focus agent 1, hunt agent 1",
    ]
    assert speech_events[0].speaker_entity_id == "agent-3"
    assert speech_events[0].verb == "vote"
    assert speech_events[0].target_entity_id == "agent-2"
    assert speech_events[1].speaker_entity_id == "agent-4"
    assert speech_events[1].verb == "hunt"
    assert speech_events[1].target_entity_id == "agent-1"
    assert isinstance(helpers.packmate_ids(), list)


def test_werewolf_prompt_adapter_exposes_discussion_skills() -> None:
    adapter = WerewolfMafiaPromptAdapter()

    library = adapter.render_skill_library()

    assert "public_discussion" in library
    assert "night_hunt" in library
    assert "target_entity_id" in library


def test_werewolf_mafia_surface_deduplicates_persistent_talk() -> None:
    env = make_game("werewolf_mafia", num_agents=8, max_steps=120)
    policy_env_info = PolicyEnvInterface.from_mg_cfg(env)
    sim = Simulation(env)
    surface = WerewolfMafiaSemanticSurface()
    observation = sim.agent(0).observation

    first_state = surface.build_state_with_events(
        AgentObservation(
            agent_id=observation.agent_id,
            tokens=observation.tokens,
            talk=[
                VisibleTalk(
                    agent_id=3,
                    text="vote agent 2",
                    location=Location(0, 0),
                    remaining_steps=6,
                )
            ],
        ),
        policy_env_info=policy_env_info,
        step=7,
    )
    second_state = surface.build_state_with_events(
        AgentObservation(
            agent_id=observation.agent_id,
            tokens=observation.tokens,
            talk=[
                VisibleTalk(
                    agent_id=3,
                    text="vote agent 2",
                    location=Location(0, 0),
                    remaining_steps=5,
                )
            ],
        ),
        policy_env_info=policy_env_info,
        step=8,
        previous_state=first_state,
    )
    third_state = surface.build_state_with_events(
        AgentObservation(
            agent_id=observation.agent_id,
            tokens=observation.tokens,
            talk=[
                VisibleTalk(
                    agent_id=3,
                    text="vote agent 2",
                    location=Location(0, 0),
                    remaining_steps=4,
                )
            ],
        ),
        policy_env_info=policy_env_info,
        step=9,
        previous_state=second_state,
    )

    assert [event.event_type for event in first_state.recent_events] == ["heard_speech"]
    assert second_state.recent_events == []
    assert third_state.recent_events == []
