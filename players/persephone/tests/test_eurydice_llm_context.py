"""Tests for Eurydice's LLM-control context contract."""

from __future__ import annotations

import json

from orpheus.belief_state import BeliefState, ChatMessageRecord, PlayerInfo
from orpheus.perception.types import HostageGrid, PlayerShape, Room, View

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


def test_llm_context_exposes_runtime_affordances_for_whisper_entry() -> None:
    belief_state = _state(
        view=View.WHISPER,
        in_whisper=True,
        whisper_occupants=[0, 1],
        pending_entry=2,
        active_role_offers=[1],
        cooldowns={"chat": 12},
    )
    _ = _add_player_for_context(belief_state, 1)
    entry_target = _add_player_for_context(belief_state, 2)

    context = build_llm_context(belief_state)

    assert "grant_entry" in context["legal_actions"]
    assert "deny_entry" in context["legal_actions"]
    assert "join_whisper" not in context["legal_actions"]
    assert context["runtime"]["pending_entry"]["player_id"] == entry_target
    assert context["runtime"]["active_role_offers"][0]["player_id"] == [14, 1]
    assert context["runtime"]["cooldowns"]["chat"] == 12
    assert context["action_affordances"]["grant_entry"]["pending_entry"]["player_id"] == entry_target
    assert context["action_affordances"]["accept_role"]["requires_active_offer"] is True


def test_llm_context_exposes_hostage_options() -> None:
    belief_state = _state(view=View.HOSTAGE_SELECT)
    target = _add_player_for_context(belief_state, 1)
    belief_state.hostage_selections = HostageGrid(
        eligible_colors=[target[0], 8],
        eligible_shapes=[PlayerShape(target[1]), PlayerShape.TRIANGLE],
        selected_positions=[],
        count_label="0/1 HOSTAGES",
    )

    context = build_llm_context(belief_state)

    assert context["legal_actions"] == ["hold", "select_hostage"]
    options = context["runtime"]["hostage_options"]
    assert options["remaining_count"] == 1
    assert options["options"][0]["player_id"] == target
    assert context["action_affordances"]["select_hostage"]["requires_hostage_targets"] is True


def test_llm_decision_schema_is_closed_and_action_bounded() -> None:
    schema = llm_decision_schema()

    assert schema["schema_version"] == DECISION_SCHEMA_VERSION
    assert schema["additionalProperties"] is False
    assert "probe_player" in schema["properties"]["action"]["enum"]
    assert "grant_entry" in schema["properties"]["action"]["enum"]
    assert "deny_entry" in schema["properties"]["action"]["enum"]
    assert schema["properties"]["destination"]["maxItems"] == 2
    assert "hostage_targets" in schema["properties"]
    assert schema["properties"]["message"]["maxLength"] == 48


def _add_player_for_context(belief_state: BeliefState, index: int) -> list[int]:
    belief_state.players[index] = PlayerInfo(
        position=(70 + index, 60, belief_state.tick),
        room=Room.UNDERWORLD,
        last_seen_in_whisper=belief_state.tick,
    )
    player_id = player_index_to_id(index, belief_state)
    assert player_id is not None
    belief_state.extra[PLAYER_KNOWLEDGE][player_id] = PlayerKnowledge.create(player_id)
    return [int(player_id[0]), int(player_id[1])]
