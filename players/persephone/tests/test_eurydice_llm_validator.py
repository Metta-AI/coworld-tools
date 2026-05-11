"""Tests for deterministic validation of future LLM decisions."""

from __future__ import annotations

import json

from orpheus.belief_state import BeliefState, PlayerInfo
from orpheus.logging import Logger
from orpheus.perception.types import HostageGrid, PlayerShape, Room, View

from agents.eurydice.ext_keys import PLAYER_KNOWLEDGE
from agents.eurydice.knowledge import PlayerKnowledge
from agents.eurydice.llm_context import DECISION_SCHEMA_VERSION, LLMDecision, build_llm_context
from agents.eurydice.llm_validator import (
    validate_and_trace_llm_decision,
    validate_llm_decision,
)
from agents.eurydice.log import set_logger
from agents.eurydice.pipeline import initialize_eurydice_state, player_index_to_id
from agents.eurydice.types import Role, RoleSource, Team, TeamSource


def _state(**overrides) -> BeliefState:
    values = {
        "tick": 100,
        "view": View.PLAYING,
        "round": 1,
        "timer_secs": 12,
        "my_index": 0,
        "my_color": 3,
        "my_role": "hades",
        "my_team": "shades",
        "my_room": Room.UNDERWORLD,
        "room": Room.UNDERWORLD,
        "position": (50, 50),
        "player_count": 10,
        "round_schedule": [(15, 1), (15, 1), (15, 1)],
    }
    values.update(overrides)
    belief_state = BeliefState(**values)
    initialize_eurydice_state(belief_state)
    return belief_state


def _decision(**overrides) -> dict:
    values = {
        "schema_version": DECISION_SCHEMA_VERSION,
        "action": "hold",
        "surface": None,
        "target": None,
        "destination": None,
        "hostage_targets": None,
        "message": None,
        "reveal_color": False,
        "reveal_role": False,
        "confidence": 0.7,
        "rationale": "safe default",
    }
    values.update(overrides)
    return values


def _add_player(
    belief_state: BeliefState,
    index: int,
    *,
    role: Role | None = None,
    role_source: RoleSource = RoleSource.ROLE_EXCHANGE,
    team: Team | None = None,
    in_whisper: bool = False,
) -> list[int]:
    belief_state.players[index] = PlayerInfo(
        position=(70, 50, belief_state.tick),
        room=Room.UNDERWORLD,
        last_seen_in_whisper=belief_state.tick if in_whisper else None,
    )
    player_id = player_index_to_id(index, belief_state)
    assert player_id is not None
    record = PlayerKnowledge.create(player_id)
    if role is not None:
        record.role = role
        record.role_source = role_source
    if team is not None:
        record.team = team
        record.team_source = TeamSource.COLOR_EXCHANGE
        record.team_confidence = 0.9
    belief_state.extra[PLAYER_KNOWLEDGE][player_id] = record
    return [int(player_id[0]), int(player_id[1])]


def test_validator_accepts_valid_probe_target_decision() -> None:
    belief_state = _state()
    target = _add_player(belief_state, 1)
    context = build_llm_context(belief_state)

    result = validate_llm_decision(
        _decision(action="probe_player", target=target, rationale="probe visible target"),
        context,
    )

    assert result.accepted is True
    assert result.decision["action"] == "probe_player"
    assert result.reasons == []


def test_validator_rejects_unknown_fields_and_bad_action() -> None:
    belief_state = _state()
    context = build_llm_context(belief_state)
    proposed = _decision(action="invent_mode", unsupported=True)

    result = validate_llm_decision(proposed, context)

    assert result.accepted is False
    assert "unknown_action" in result.reasons
    assert "unknown_fields:unsupported" in result.reasons
    assert result.fallback_decision["action"] == "hold"


def test_validator_rejects_boolean_numeric_fields() -> None:
    belief_state = _state()
    context = build_llm_context(belief_state)

    result = validate_llm_decision(
        _decision(action="probe_player", target=[True, False], confidence=True),
        context,
    )

    assert result.accepted is False
    assert "bad_target_shape" in result.reasons
    assert "bad_confidence" in result.reasons


def test_validator_rejects_action_illegal_for_current_view() -> None:
    belief_state = _state(view=View.PLAYING)
    context = build_llm_context(belief_state)

    result = validate_llm_decision(
        _decision(action="send_whisper", message="HELLO", rationale="wrong view"),
        context,
    )

    assert result.accepted is False
    assert "illegal_action_for_view" in result.reasons


def test_validator_rejects_missing_or_unknown_probe_target() -> None:
    belief_state = _state()
    context = build_llm_context(belief_state)

    missing = validate_llm_decision(
        _decision(action="probe_player", target=None),
        context,
    )
    unknown = validate_llm_decision(
        _decision(action="probe_player", target=[99, 99]),
        context,
    )

    assert "target_required" in missing.reasons
    assert "unknown_target" in unknown.reasons


def test_validator_requires_exchange_targets_unless_single_occupant() -> None:
    belief_state = _state(
        view=View.WHISPER,
        in_whisper=True,
        whisper_occupants=[0, 1, 2],
    )
    _add_player(belief_state, 1, team=Team.SHADES, in_whisper=True)
    _add_player(belief_state, 2, team=Team.SHADES, in_whisper=True)
    context = build_llm_context(belief_state)

    result = validate_llm_decision(_decision(action="offer_role"), context)

    assert result.accepted is False
    assert "target_required" in result.reasons


def test_validator_allows_offer_target_omission_for_single_occupant() -> None:
    belief_state = _state(
        view=View.WHISPER,
        in_whisper=True,
        whisper_occupants=[0, 1],
    )
    _add_player(belief_state, 1, team=Team.SHADES, in_whisper=True)
    context = build_llm_context(belief_state)

    result = validate_llm_decision(_decision(action="offer_role"), context)

    assert result.accepted is True


def test_validator_rejects_accept_without_active_offer_from_target() -> None:
    belief_state = _state(
        view=View.WHISPER,
        in_whisper=True,
        whisper_occupants=[0, 1],
    )
    target = _add_player(belief_state, 1, team=Team.SHADES, in_whisper=True)
    context = build_llm_context(belief_state)

    result = validate_llm_decision(_decision(action="accept_role", target=target), context)

    assert result.accepted is False
    assert "no_active_role_offer_from_target" in result.reasons


def test_validator_accepts_active_offer_from_target() -> None:
    belief_state = _state(
        view=View.WHISPER,
        in_whisper=True,
        whisper_occupants=[0, 1],
        active_role_offers=[1],
    )
    target = _add_player(belief_state, 1, team=Team.SHADES, in_whisper=True)
    context = build_llm_context(belief_state)

    result = validate_llm_decision(_decision(action="accept_role", target=target), context)

    assert result.accepted is True


def test_validator_requires_grant_target_to_match_pending_entry() -> None:
    belief_state = _state(
        view=View.WHISPER,
        in_whisper=True,
        whisper_occupants=[0],
        pending_entry=2,
    )
    wrong = _add_player(belief_state, 1)
    pending = _add_player(belief_state, 2)
    context = build_llm_context(belief_state)

    wrong_result = validate_llm_decision(_decision(action="grant_entry", target=wrong), context)
    pending_result = validate_llm_decision(_decision(action="grant_entry", target=pending), context)

    assert wrong_result.accepted is False
    assert "target_not_pending_entry" in wrong_result.reasons
    assert pending_result.accepted is True


def test_validator_requires_destination_for_move_to() -> None:
    belief_state = _state(room_size=(100, 100))
    context = build_llm_context(belief_state)

    missing = validate_llm_decision(_decision(action="move_to"), context)
    valid = validate_llm_decision(
        _decision(action="move_to", destination=[80, 70]),
        context,
    )
    out_of_bounds = validate_llm_decision(
        _decision(action="move_to", destination=[180, 70]),
        context,
    )

    assert "destination_required" in missing.reasons
    assert valid.accepted is True
    assert "destination_out_of_bounds" in out_of_bounds.reasons


def test_validator_requires_hostage_targets_for_hostage_selection() -> None:
    belief_state = _state(view=View.HOSTAGE_SELECT)
    target = _add_player(belief_state, 1)
    context = build_llm_context(belief_state)

    missing = validate_llm_decision(_decision(action="select_hostage"), context)
    valid = validate_llm_decision(
        _decision(action="select_hostage", hostage_targets=[target]),
        context,
    )

    assert "hostage_targets_required" in missing.reasons
    assert valid.accepted is True


def test_validator_rejects_hostage_targets_not_matching_grid() -> None:
    belief_state = _state(view=View.HOSTAGE_SELECT)
    target = _add_player(belief_state, 1)
    other = _add_player(belief_state, 2)
    belief_state.hostage_selections = HostageGrid(
        eligible_colors=[target[0]],
        eligible_shapes=[PlayerShape(target[1])],
        selected_positions=[],
        count_label="0/1 HOSTAGES",
    )
    context = build_llm_context(belief_state)

    result = validate_llm_decision(
        _decision(action="select_hostage", hostage_targets=[other]),
        context,
    )

    assert result.accepted is False
    assert "hostage_target_not_eligible" in result.reasons


def test_validator_accepts_hostage_option_even_when_player_not_visible() -> None:
    belief_state = _state(view=View.HOSTAGE_SELECT)
    belief_state.hostage_selections = HostageGrid(
        eligible_colors=[12],
        eligible_shapes=[PlayerShape.SQUARE],
        selected_positions=[],
        count_label="0/1 HOSTAGES",
    )
    context = build_llm_context(belief_state)

    result = validate_llm_decision(
        _decision(
            action="select_hostage",
            hostage_targets=[[12, PlayerShape.SQUARE.value]],
        ),
        context,
    )

    assert result.accepted is True


def test_validator_rejects_wrong_hostage_target_count() -> None:
    belief_state = _state(view=View.HOSTAGE_SELECT)
    first = _add_player(belief_state, 1)
    second = _add_player(belief_state, 2)
    belief_state.hostage_selections = HostageGrid(
        eligible_colors=[first[0], second[0]],
        eligible_shapes=[PlayerShape(first[1]), PlayerShape(second[1])],
        selected_positions=[],
        count_label="0/2 HOSTAGES",
    )
    context = build_llm_context(belief_state)

    result = validate_llm_decision(
        _decision(action="select_hostage", hostage_targets=[first]),
        context,
    )

    assert result.accepted is False
    assert "hostage_target_count_mismatch" in result.reasons


def test_validator_rejects_role_reveal_to_known_enemy() -> None:
    belief_state = _state(
        view=View.WHISPER,
        in_whisper=True,
        whisper_occupants=[0, 1],
    )
    target = _add_player(belief_state, 1, team=Team.NYMPHS, in_whisper=True)
    context = build_llm_context(belief_state)

    result = validate_llm_decision(
        _decision(
            action="offer_role",
            target=target,
            reveal_role=True,
            rationale="enemy should not see true role",
        ),
        context,
    )

    assert result.accepted is False
    assert "role_reveal_to_known_enemy" in result.reasons


def test_validator_allows_role_reveal_to_enemy_for_disruption_objective() -> None:
    belief_state = _state(
        view=View.WHISPER,
        in_whisper=True,
        whisper_occupants=[0, 1],
    )
    target = _add_player(belief_state, 1, team=Team.NYMPHS, in_whisper=True)
    context = build_llm_context(belief_state)
    context["strategy"]["objective"] = "disrupt_enemy"

    result = validate_llm_decision(
        _decision(action="offer_role", target=target, reveal_role=True),
        context,
    )

    assert result.accepted is True


def test_validator_rejects_color_reveal_when_spy_risk_active() -> None:
    belief_state = _state(
        view=View.WHISPER,
        in_whisper=True,
        whisper_occupants=[0, 1],
        spy_in_game_config=True,
    )
    target = _add_player(belief_state, 1, team=Team.SHADES, in_whisper=True)
    context = build_llm_context(belief_state)

    result = validate_llm_decision(
        _decision(action="offer_color", target=target, reveal_color=True),
        context,
    )

    assert result.accepted is False
    assert "color_reveal_with_spy_risk" in result.reasons


def test_validator_rejects_unsafe_message_and_unsupported_mechanical_claim() -> None:
    belief_state = _state(view=View.GLOBAL_CHAT)
    context = build_llm_context(belief_state)

    result = validate_llm_decision(
        _decision(
            action="send_global",
            message="ROLE EXCHANGED \u2603",
            rationale="bad claim",
        ),
        context,
    )

    assert result.accepted is False
    assert "message_not_safe_ascii" in result.reasons
    assert "unsupported_mechanical_claim" in result.reasons


def test_validator_rejects_false_first_person_key_role_claim() -> None:
    belief_state = _state(view=View.GLOBAL_CHAT, my_role="nymph", my_team="nymphs")
    context = build_llm_context(belief_state)

    result = validate_llm_decision(
        _decision(
            action="send_global",
            message="I AM PERSEPHONE",
            rationale="false key role claim",
        ),
        context,
    )

    assert result.accepted is False
    assert "false_self_role_claim" in result.reasons


def test_validator_allows_true_first_person_role_claim() -> None:
    belief_state = _state(view=View.GLOBAL_CHAT, my_role="demeter", my_team="nymphs")
    context = build_llm_context(belief_state)

    result = validate_llm_decision(
        _decision(
            action="send_global",
            message="I AM DEMETER",
            rationale="true role claim",
        ),
        context,
    )

    assert result.accepted is True


def test_validator_rejects_false_implied_here_role_claim() -> None:
    belief_state = _state(view=View.GLOBAL_CHAT, my_role="persephone", my_team="nymphs")
    context = build_llm_context(belief_state)

    result = validate_llm_decision(
        _decision(
            action="send_global",
            message="DEMETER HERE. NEED YOU.",
            rationale="false implied role claim",
        ),
        context,
    )

    assert result.accepted is False
    assert "false_self_role_claim" in result.reasons


def test_validator_allows_question_about_role_here() -> None:
    belief_state = _state(view=View.GLOBAL_CHAT, my_role="shade", my_team="shades")
    context = build_llm_context(belief_state)

    result = validate_llm_decision(
        _decision(
            action="send_global",
            message="HADES HERE? ROLE SWAP?",
            rationale="question not a self claim",
        ),
        context,
    )

    assert result.accepted is True


def test_validator_rejects_unsupported_role_possession_claim() -> None:
    belief_state = _state(view=View.LEADER_SUMMIT, my_role="shade", my_team="shades")
    context = build_llm_context(belief_state)

    result = validate_llm_decision(
        _decision(
            action="send_whisper",
            message="I HAVE CERBERUS",
            rationale="unsupported possession claim",
        ),
        context,
    )

    assert result.accepted is False
    assert "unsupported_role_possession_claim" in result.reasons


def test_validator_allows_role_possession_with_mechanical_evidence() -> None:
    belief_state = _state(view=View.LEADER_SUMMIT)
    _add_player(belief_state, 1, role=Role.CERBERUS)
    context = build_llm_context(belief_state)

    result = validate_llm_decision(
        _decision(
            action="send_whisper",
            message="I HAVE CERBERUS",
            rationale="mechanically known role",
        ),
        context,
    )

    assert result.accepted is True


def test_validator_accepts_llm_decision_dataclass() -> None:
    belief_state = _state()
    context = build_llm_context(belief_state)

    result = validate_llm_decision(LLMDecision(action="hold", confidence=0.5), context)

    assert result.accepted is True


def test_validate_and_trace_emits_shadow_events() -> None:
    lines: list[str] = []
    set_logger(Logger(level="decisions", sink=lines.append, clock=lambda: 0.0))
    try:
        belief_state = _state()
        result = validate_and_trace_llm_decision(
            belief_state,
            _decision(action="send_whisper", message="HELLO"),
        )
    finally:
        set_logger(None)

    assert result.accepted is False
    event_types = [json.loads(line)["type"] for line in lines]
    assert event_types == [
        "llm_context",
        "llm_decision",
        "llm_decision_rejected",
    ]
    rejected = json.loads(lines[-1])
    assert rejected["context_hash"] == result.context_hash
    assert "illegal_action_for_view" in rejected["reasons"]


def test_validate_and_trace_emits_accepted_shadow_event() -> None:
    lines: list[str] = []
    set_logger(Logger(level="decisions", sink=lines.append, clock=lambda: 0.0))
    try:
        belief_state = _state()
        result = validate_and_trace_llm_decision(
            belief_state,
            _decision(action="hold"),
        )
    finally:
        set_logger(None)

    assert result.accepted is True
    event_types = [json.loads(line)["type"] for line in lines]
    assert event_types == [
        "llm_context",
        "llm_decision",
        "llm_decision_accepted",
    ]
