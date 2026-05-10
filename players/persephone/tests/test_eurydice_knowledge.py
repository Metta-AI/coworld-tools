"""Phase 2 knowledge-pipeline contracts for Eurydice."""

from __future__ import annotations

from agents.eurydice.ext_keys import (
    EURYDICE_ACCUMULATORS,
    INFO_SCREEN_RECONCILE_PENDING,
    PLAYER_KNOWLEDGE,
)
from agents.eurydice.knowledge import PlayerKnowledge
from agents.eurydice.pipeline import (
    initialize_eurydice_state,
    player_index_to_id,
    run_hard_inferences,
    update_chat_tracker,
    update_exchange_tracker,
    update_info_screen_reconciliation,
    update_leadership_tracker,
)
from agents.eurydice.types import Role, RoleSource, Team, TeamSource, TrustLevel
from orpheus.belief_state import BeliefState, ChatMessageRecord, PlayerInfo
from orpheus.perception._common import PLAYER_COLORS
from orpheus.perception.types import Room, View


def _belief_state(**overrides) -> BeliefState:
    values = {
        "tick": 10,
        "view": View.WHISPER,
        "in_whisper": True,
        "whisper_occupants": [0, 1],
        "my_index": 0,
        "my_color": PLAYER_COLORS[0],
        "my_shape": 0,
        "my_team": "shades",
        "my_role": "hades",
        "my_room": Room.UNDERWORLD,
        "room": Room.UNDERWORLD,
        "round": 1,
        "player_count": 8,
    }
    values.update(overrides)
    belief_state = BeliefState(**values)
    initialize_eurydice_state(belief_state)
    return belief_state


def _pid(index: int, belief_state: BeliefState):
    player_id = player_index_to_id(index, belief_state)
    assert player_id is not None
    return player_id


def test_exchange_tracker_consumes_structured_color_event() -> None:
    belief_state = _belief_state()
    belief_state.last_exchange_event = {
        "type": "swapped_colors",
        "tick": 10,
        "participants": [0, 1],
    }

    update_exchange_tracker(
        belief_state.extra[EURYDICE_ACCUMULATORS],
        belief_state.extra[PLAYER_KNOWLEDGE],
        belief_state,
    )

    player_id = _pid(1, belief_state)
    record = belief_state.extra[PLAYER_KNOWLEDGE][player_id]
    acc = belief_state.extra[EURYDICE_ACCUMULATORS].player_accumulators[player_id]
    assert record.has_exchanged_colors_with_us is True
    assert record.times_interacted == 1
    assert record.last_interaction_round == 1
    assert acc.color_offers_received_and_accepted == 1


def test_exchange_tracker_consumes_structured_role_event_once() -> None:
    belief_state = _belief_state()
    belief_state.last_exchange_event = {
        "type": "shared_roles",
        "tick": 10,
        "participants": [0, 1],
    }

    accumulators = belief_state.extra[EURYDICE_ACCUMULATORS]
    knowledge = belief_state.extra[PLAYER_KNOWLEDGE]
    update_exchange_tracker(accumulators, knowledge, belief_state)
    update_exchange_tracker(accumulators, knowledge, belief_state)

    player_id = _pid(1, belief_state)
    record = knowledge[player_id]
    acc = accumulators.player_accumulators[player_id]
    assert record.has_exchanged_roles_with_us is True
    assert record.times_interacted == 1
    assert acc.role_offers_received_and_accepted == 1


def test_exchange_tracker_schedules_info_screen_reconciliation() -> None:
    belief_state = _belief_state()
    belief_state.last_exchange_event = {
        "type": "shared_roles",
        "tick": 10,
        "participants": [0, 1],
    }

    update_exchange_tracker(
        belief_state.extra[EURYDICE_ACCUMULATORS],
        belief_state.extra[PLAYER_KNOWLEDGE],
        belief_state,
    )

    assert belief_state.extra[INFO_SCREEN_RECONCILE_PENDING] is True


def test_info_screen_reconciles_full_role_exchange() -> None:
    belief_state = _belief_state(
        view=View.INFO_SCREEN,
        in_whisper=False,
        whisper_occupants=[],
    )
    belief_state.extra[INFO_SCREEN_RECONCILE_PENDING] = True
    belief_state.players[1] = PlayerInfo(role="cerberus", team="shades")

    update_info_screen_reconciliation(
        belief_state.extra[EURYDICE_ACCUMULATORS],
        belief_state.extra[PLAYER_KNOWLEDGE],
        belief_state,
    )

    player_id = _pid(1, belief_state)
    record = belief_state.extra[PLAYER_KNOWLEDGE][player_id]
    acc = belief_state.extra[EURYDICE_ACCUMULATORS].player_accumulators[player_id]
    assert belief_state.extra[INFO_SCREEN_RECONCILE_PENDING] is False
    assert belief_state.my_exchange_partner == 1
    assert record.role is Role.CERBERUS
    assert record.role_source is RoleSource.ROLE_EXCHANGE
    assert record.team is Team.SHADES
    assert record.team_source is TeamSource.ROLE_EXCHANGE
    assert record.team_confidence == 1.0
    assert record.trust_level is TrustLevel.VERIFIED
    assert record.has_exchanged_roles_with_us is True
    assert record.has_exchanged_colors_with_us is True
    assert record.times_interacted == 1
    assert acc.role_offers_received_and_accepted == 1


def test_info_screen_reconciles_color_only_without_role() -> None:
    belief_state = _belief_state(
        view=View.INFO_SCREEN,
        in_whisper=False,
        whisper_occupants=[],
    )
    belief_state.players[2] = PlayerInfo(team="nymphs")

    update_info_screen_reconciliation(
        belief_state.extra[EURYDICE_ACCUMULATORS],
        belief_state.extra[PLAYER_KNOWLEDGE],
        belief_state,
    )

    player_id = _pid(2, belief_state)
    record = belief_state.extra[PLAYER_KNOWLEDGE][player_id]
    acc = belief_state.extra[EURYDICE_ACCUMULATORS].player_accumulators[player_id]
    assert record.role is None
    assert record.role_source is RoleSource.NONE
    assert record.team is Team.NYMPHS
    assert record.team_source is TeamSource.COLOR_EXCHANGE
    assert record.team_confidence == 1.0
    assert record.trust_level is TrustLevel.HOSTILE
    assert record.has_exchanged_colors_with_us is True
    assert record.has_exchanged_roles_with_us is False
    assert acc.color_offers_received_and_accepted == 1


def test_color_exchange_confidence_lower_when_spy_possible() -> None:
    belief_state = _belief_state(
        view=View.PLAYING,
        in_whisper=False,
        spy_in_game_config=True,
    )
    belief_state.players[1] = PlayerInfo(team="shades")
    knowledge = belief_state.extra[PLAYER_KNOWLEDGE]

    run_hard_inferences(knowledge, belief_state)

    record = knowledge[_pid(1, belief_state)]
    assert record.team is Team.SHADES
    assert record.team_source is TeamSource.COLOR_EXCHANGE
    assert record.team_confidence == 0.9


def test_color_exchange_confidence_full_when_spy_absent() -> None:
    belief_state = _belief_state(
        view=View.PLAYING,
        in_whisper=False,
        spy_in_game_config=False,
    )
    belief_state.players[1] = PlayerInfo(team="shades")
    knowledge = belief_state.extra[PLAYER_KNOWLEDGE]

    run_hard_inferences(knowledge, belief_state)

    record = knowledge[_pid(1, belief_state)]
    assert record.team_confidence == 1.0


def test_ambiguous_multi_occupant_exchange_does_not_misattribute() -> None:
    belief_state = _belief_state(whisper_occupants=[0, 1, 2])
    belief_state.last_exchange_event = {
        "type": "shared_roles",
        "tick": 10,
        "participants": [],
    }

    update_exchange_tracker(
        belief_state.extra[EURYDICE_ACCUMULATORS],
        belief_state.extra[PLAYER_KNOWLEDGE],
        belief_state,
    )

    assert belief_state.extra[PLAYER_KNOWLEDGE] == {}
    assert belief_state.extra[EURYDICE_ACCUMULATORS].player_accumulators == {}


def test_active_offer_tracking_is_deduplicated() -> None:
    belief_state = _belief_state(active_role_offers=[1])
    accumulators = belief_state.extra[EURYDICE_ACCUMULATORS]
    knowledge = belief_state.extra[PLAYER_KNOWLEDGE]

    update_exchange_tracker(accumulators, knowledge, belief_state)
    update_exchange_tracker(accumulators, knowledge, belief_state)

    acc = accumulators.player_accumulators[_pid(1, belief_state)]
    assert acc.role_offers_made == 1


def test_chat_parser_updates_low_priority_identity_claim() -> None:
    belief_state = _belief_state(view=View.PLAYING, in_whisper=False)
    player_id = _pid(1, belief_state)
    record = PlayerKnowledge.create(player_id)
    record.team = Team.SHADES
    record.team_source = TeamSource.COLOR_EXCHANGE
    record.team_confidence = 1.0
    belief_state.extra[PLAYER_KNOWLEDGE][player_id] = record
    belief_state.chat_history = [
        ChatMessageRecord(1, 11, "global", "I am Cerberus"),
    ]

    update_chat_tracker(
        belief_state.extra[EURYDICE_ACCUMULATORS],
        belief_state.extra[PLAYER_KNOWLEDGE],
        belief_state,
    )

    assert record.claims_about_identity == "I am Cerberus"
    assert record.role is Role.CERBERUS
    assert record.role_source is RoleSource.CHAT_CLAIM
    assert record.team is Team.SHADES
    assert record.team_source is TeamSource.COLOR_EXCHANGE


def test_enemy_chat_claim_cannot_overwrite_mechanical_exchange() -> None:
    belief_state = _belief_state(view=View.PLAYING, in_whisper=False)
    player_id = _pid(1, belief_state)
    record = PlayerKnowledge.create(player_id)
    record.role = Role.HADES
    record.role_source = RoleSource.ROLE_EXCHANGE
    record.team = Team.SHADES
    record.team_source = TeamSource.ROLE_EXCHANGE
    record.team_confidence = 1.0
    belief_state.extra[PLAYER_KNOWLEDGE][player_id] = record
    belief_state.chat_history = [
        ChatMessageRecord(1, 11, "global", "I am Persephone"),
    ]

    update_chat_tracker(
        belief_state.extra[EURYDICE_ACCUMULATORS],
        belief_state.extra[PLAYER_KNOWLEDGE],
        belief_state,
    )

    assert record.claims_about_identity == "I am Persephone"
    assert record.role is Role.HADES
    assert record.role_source is RoleSource.ROLE_EXCHANGE
    assert record.team is Team.SHADES
    assert record.team_source is TeamSource.ROLE_EXCHANGE


def test_leadership_tracker_records_confirmed_leader_color() -> None:
    belief_state = _belief_state(
        view=View.PLAYING,
        in_whisper=False,
        leader_colors={Room.UNDERWORLD: PLAYER_COLORS[3]},
    )

    update_leadership_tracker(
        belief_state.extra[EURYDICE_ACCUMULATORS],
        belief_state,
    )

    player_id = _pid(3, belief_state)
    record = belief_state.extra[PLAYER_KNOWLEDGE][player_id]
    acc = belief_state.extra[EURYDICE_ACCUMULATORS].player_accumulators[player_id]
    assert record.is_leader is True
    assert record.room is Room.UNDERWORLD
    assert record.was_leader_round == [1]
    assert acc.leadership_rounds == [1]
