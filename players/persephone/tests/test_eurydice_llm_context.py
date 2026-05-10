"""Tests for Eurydice's LLM-control context contract."""

from __future__ import annotations

import json

from orpheus.belief_state import BeliefState, ChatMessageRecord, PlayerInfo
from orpheus.perception.types import Room, View

from agents.eurydice.ext_keys import PLAYER_KNOWLEDGE
from agents.eurydice.knowledge import PlayerKnowledge
from agents.eurydice.llm_context import (
    DECISION_SCHEMA_VERSION,
    SCHEMA_VERSION,
    build_llm_context,
    llm_decision_schema,
)
from agents.eurydice.pipeline import initialize_eurydice_state, player_index_to_id
from agents.eurydice.types import Role, RoleSource, Team, TeamSource


def _state(**overrides) -> BeliefState:
    values = {
        "tick": 120,
        "view": View.PLAYING,
        "round": 1,
        "timer_secs": 12,
        "my_index": 0,
        "my_color": 3,
        "my_role": "hades",
        "my_team": "shades",
        "my_room": Room.UNDERWORLD,
        "room": Room.UNDERWORLD,
        "position": (50, 60),
        "player_count": 10,
        "round_schedule": [(15, 1), (15, 1), (15, 1)],
    }
    values.update(overrides)
    belief_state = BeliefState(**values)
    initialize_eurydice_state(belief_state)
    return belief_state


def test_llm_context_is_json_serializable_and_namespaced() -> None:
    belief_state = _state()
    target = player_index_to_id(1, belief_state)
    assert target is not None
    belief_state.players[1] = PlayerInfo(
        position=(70, 60, 120),
        room=Room.UNDERWORLD,
        last_seen_in_whisper=118,
    )
    record = PlayerKnowledge.create(target)
    record.team = Team.NYMPHS
    record.team_source = TeamSource.COLOR_EXCHANGE
    record.team_confidence = 0.9
    record.role = Role.NYMPH
    record.role_source = RoleSource.CHAT_CLAIM
    record.times_interacted = 1
    record.behavioral_flags.add("exchange_eager")
    belief_state.extra[PLAYER_KNOWLEDGE][target] = record
    belief_state.chat_history.append(
        ChatMessageRecord(1, 119, "whisper", "I AM NYMPH", occupants=[0, 1])
    )

    context = build_llm_context(belief_state)

    assert context["schema_version"] == SCHEMA_VERSION
    assert context["self"]["role"] == "hades"
    assert context["strategy"]["objective"] in {"find_key_partner", "idle"}
    assert context["match"]["round_schedule"] == [[15, 1], [15, 1], [15, 1]]
    assert context["players"][0]["player_id"] == [3, 0]
    assert any(player["team"] == "nymphs" for player in context["players"])
    assert context["recent_messages"][-1]["text"] == "I AM NYMPH"
    assert "probe_player" in context["legal_actions"]
    json.dumps(context)


def test_llm_context_whisper_actions_include_exchange_controls() -> None:
    belief_state = _state(
        view=View.WHISPER,
        in_whisper=True,
        whisper_occupants=[0, 1],
        pending_offers={"role": True, "color": True},
    )

    context = build_llm_context(belief_state)

    assert set(context["legal_actions"]) >= {
        "send_whisper",
        "accept_color",
        "accept_role",
        "offer_color",
        "offer_role",
        "exit_whisper",
    }
    assert any("role exchange" in item.lower() for item in context["hard_constraints"])


def test_llm_decision_schema_is_closed_and_action_bounded() -> None:
    schema = llm_decision_schema()

    assert schema["schema_version"] == DECISION_SCHEMA_VERSION
    assert schema["additionalProperties"] is False
    assert "probe_player" in schema["properties"]["action"]["enum"]
    assert schema["properties"]["message"]["maxLength"] == 48
