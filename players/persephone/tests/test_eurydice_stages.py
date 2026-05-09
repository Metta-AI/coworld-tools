"""Comprehensive pytest coverage for Eurydice stages 0-3."""
from __future__ import annotations

import json
import struct
from types import SimpleNamespace

import pytest

from agents.eurydice.accumulators import GlobalAccumulators, PlayerAccumulator
from agents.eurydice.deception import DeceptionState, is_cover_blown, record_lie
from agents.eurydice.ext_keys import *
from agents.eurydice.evaluators import evaluate_hades
from agents.eurydice.frame_recorder import FrameRecorder
from agents.eurydice.knowledge import PlayerKnowledge
from agents.eurydice.log import logger as eurydice_logger, set_logger
from agents.eurydice.meta_decide import build_strategic_state, compute_urgency, meta_decide
from agents.eurydice.modes import (
    ProbeSystematicMode,
    ProbeSystematicParams,
    ProbeTargetMode,
    ProbeTargetParams,
    ScoutMode,
)
from agents.eurydice.pipeline import (
    derive_behavioral_flags,
    eurydice_post_belief_update,
    initialize_eurydice_state,
    player_index_to_id,
    run_hard_inferences,
    run_soft_inferences,
    update_chat_tracker,
    update_exchange_tracker,
    update_minimap_tracker,
    update_position_tracker,
    update_whisper_tracker,
)
from agents.eurydice.strategic_state import StrategicState
from agents.eurydice.types import (
    INTERACTION_RANGE,
    Phase,
    PlayerID,
    Role,
    RoleSource,
    Team,
    TeamSource,
    TrustLevel,
    Urgency,
)
from agents.eurydice.whisper_mode import InWhisperMode
from orpheus.action_memory import ActionMemory
from orpheus.belief_state import (
    BeliefState,
    ChatMessageRecord,
    MinimapSighting,
    PlayerInfo,
)
from orpheus.idle import IdleTask
from orpheus.logging import Logger
from orpheus.mode import ModeDirective, ModeParams
from orpheus.perception._common import PLAYER_COLORS
from orpheus.perception.types import Room, View
from orpheus.tasks import CreateWhisperTask, MoveToTask, RequestEntryTask


def _belief_state(**overrides) -> BeliefState:
    values = {
        "tick": 1,
        "view": View.PLAYING,
        "position": (50, 50),
        "room": Room.UNDERWORLD,
        "room_size": (200, 200),
        "round": 1,
        "timer_secs": 300,
        "my_index": 0,
        "my_role": "hades",
        "my_team": "shades",
        "my_room": Room.UNDERWORLD,
        "player_count": 8,
    }
    values.update(overrides)
    return BeliefState(**values)


def _initialized_state(**overrides):
    belief_state = _belief_state(**overrides)
    initialize_eurydice_state(belief_state)
    return (
        belief_state,
        belief_state.extra[EURYDICE_ACCUMULATORS],
        belief_state.extra[PLAYER_KNOWLEDGE],
    )


def _pid(index: int, belief_state: BeliefState) -> PlayerID:
    player_id = player_index_to_id(index, belief_state)
    assert player_id == (PLAYER_COLORS[index % 8], index % 12)
    return player_id


def _knowledge_for(belief_state: BeliefState, index: int, **overrides) -> PlayerKnowledge:
    player_id = _pid(index, belief_state)
    record = PlayerKnowledge.create(player_id)
    for key, value in overrides.items():
        setattr(record, key, value)
    belief_state.extra.setdefault(PLAYER_KNOWLEDGE, {})[player_id] = record
    return record


def _system_message(text: str, tick: int = 1) -> ChatMessageRecord:
    return ChatMessageRecord(None, tick, "whisper", text)


def _player_message(
    sender_index: int,
    text: str,
    tick: int = 1,
    channel: str = "whisper",
) -> ChatMessageRecord:
    return ChatMessageRecord(sender_index, tick, channel, text)


def _capture_eurydice_logs(level: str = "verbose") -> list[str]:
    lines: list[str] = []
    set_logger(Logger(level=level, sink=lines.append, clock=lambda: 0.0))
    return lines


def _json_events(lines: list[str]) -> list[dict]:
    return [json.loads(line) for line in lines]


def test_frame_recorder_binary_layout(tmp_path) -> None:
    path = tmp_path / "eurydice.frames"
    recorder = FrameRecorder(path)
    recorder.record(17, b"abc")
    recorder.close()

    raw = path.read_bytes()
    tick, length = struct.unpack("<II", raw[:8])
    assert tick == 17
    assert length == 3
    assert raw[8:] == b"abc"


def test_eurydice_logger_proxy_forwards_after_set() -> None:
    lines = _capture_eurydice_logs("decisions")
    try:
        assert eurydice_logger
        eurydice_logger.event("proxy_test", {"value": 3}, "decisions")
    finally:
        set_logger(None)

    assert not eurydice_logger
    events = _json_events(lines)
    assert events[0]["type"] == "proxy_test"
    assert events[0]["value"] == 3


def test_meta_decide_logs_reason_and_strategic_change() -> None:
    belief_state = _belief_state(tick=24, my_role=None, my_team=None)
    lines = _capture_eurydice_logs("verbose")
    try:
        directive, _ = meta_decide(belief_state, ActionMemory())
        assert directive.mode == "idle"

        belief_state.tick = 100
        belief_state.my_role = "hades"
        belief_state.my_team = "shades"
        directive, _ = meta_decide(belief_state, ActionMemory())
        assert directive.mode in {"probe_systematic", "scout"}
    finally:
        set_logger(None)

    events = _json_events(lines)
    reason_events = [event for event in events if event["type"] == "meta_decide_reason"]
    assert reason_events[0]["reason"] == "no_role"
    assert reason_events[-1]["reason"] == "evaluator"

    changes = [event for event in events if event["type"] == "strategic_state_change"]
    assert changes
    assert changes[-1]["my_role"] == "hades"


def test_strategic_change_ignores_game_elapsed_only() -> None:
    belief_state = _belief_state(
        tick=24,
        view=View.LOBBY,
        round=0,
        my_role=None,
        my_team=None,
    )
    lines = _capture_eurydice_logs("decisions")
    try:
        meta_decide(belief_state, ActionMemory())
        belief_state.tick = 25
        meta_decide(belief_state, ActionMemory())
    finally:
        set_logger(None)

    changes = [
        event
        for event in _json_events(lines)
        if event["type"] == "strategic_state_change"
    ]
    assert changes == []


def test_inference_logging_only_when_value_changes() -> None:
    belief_state, _accumulators, knowledge = _initialized_state()
    belief_state.players[1] = PlayerInfo(team="shades", role="hades")

    lines = _capture_eurydice_logs("decisions")
    try:
        run_hard_inferences(knowledge, belief_state)
        first_count = sum(
            1 for event in _json_events(lines) if event["type"] == "inference_fired"
        )
        run_hard_inferences(knowledge, belief_state)
        second_count = sum(
            1 for event in _json_events(lines) if event["type"] == "inference_fired"
        )
    finally:
        set_logger(None)

    assert first_count >= 2
    assert second_count == first_count


def test_deception_logs_lies_and_cover_blown_once() -> None:
    state = DeceptionState()
    lines = _capture_eurydice_logs("decisions")
    try:
        record_lie(state, (1, 2), "I AM HADES", "whisper", 1)
        record_lie(state, (1, 2), "I AM NYMPH", "whisper", 2)
        assert is_cover_blown(state, None)
        assert is_cover_blown(state, None)
    finally:
        set_logger(None)

    events = _json_events(lines)
    assert sum(1 for event in events if event["type"] == "lie_recorded") == 2
    assert sum(1 for event in events if event["type"] == "cover_blown") == 1
    assert events[-1]["reason"] == "inconsistent_lie_record"


def test_evaluator_branch_logged_at_verbose_level() -> None:
    state = StrategicState(
        my_role=Role.HADES,
        my_team=Team.SHADES,
        my_room=Room.UNDERWORLD,
        key_partner_found=True,
        key_partner_room=Room.UNDERWORLD,
        round_schedule=[(15, 1), (15, 1), (15, 1)],
    )
    lines = _capture_eurydice_logs("verbose")
    try:
        directive = evaluate_hades(state, BeliefState(), ActionMemory())
    finally:
        set_logger(None)

    assert directive.mode == "probe_target"
    events = _json_events(lines)
    branch = next(event for event in events if event["type"] == "evaluator_branch")
    assert branch["role"] == "hades"
    assert branch["branch"] == "partner_in_room->probe_target"


def test_whisper_fsm_and_protocol_logging() -> None:
    belief_state, _accumulators, _knowledge = _initialized_state(
        view=View.WHISPER,
        in_whisper=True,
        whisper_occupants=[0, 1],
    )
    mode = InWhisperMode()
    mode.mode_enter(belief_state, ActionMemory())

    lines = _capture_eurydice_logs("decisions")
    try:
        mode.select_task(belief_state, ActionMemory())
        mode.select_task(belief_state, ActionMemory())
    finally:
        set_logger(None)

    events = _json_events(lines)
    assert any(event["type"] == "whisper_fsm_transition" for event in events)
    protocol = next(
        event for event in events if event["type"] == "whisper_protocol_selected"
    )
    assert protocol["protocol"] == "standard"
    assert protocol["reason"] == "unknown_target_color_exchange"



def test_stale_position_sets_not_visible_since() -> None:
    belief_state, accumulators, knowledge = _initialized_state(tick=10)
    belief_state.players[1] = PlayerInfo(position=(12, 18, 9))

    update_position_tracker(accumulators, knowledge, belief_state)

    acc = accumulators.player_accumulators[_pid(1, belief_state)]
    assert acc.not_visible_since == 10
    assert acc.visible_ticks_this_round == 0
    assert len(acc.position_history) == 0


def test_stationary_detection_increments() -> None:
    belief_state, accumulators, knowledge = _initialized_state()

    for tick in range(1, 5):
        belief_state.tick = tick
        belief_state.players[1] = PlayerInfo(position=(20, 30, tick))
        update_position_tracker(accumulators, knowledge, belief_state)

    acc = accumulators.player_accumulators[_pid(1, belief_state)]
    assert acc.visible_ticks_this_round == 4
    assert acc.stationary_ticks == 3
    assert list(acc.position_history) == [(1, 20, 30), (2, 20, 30), (3, 20, 30), (4, 20, 30)]


def test_stationary_resets_on_movement() -> None:
    belief_state, accumulators, knowledge = _initialized_state()

    for tick, position in [(1, (20, 20)), (2, (20, 20)), (3, (25, 20))]:
        belief_state.tick = tick
        belief_state.players[1] = PlayerInfo(position=(*position, tick))
        update_position_tracker(accumulators, knowledge, belief_state)

    acc = accumulators.player_accumulators[_pid(1, belief_state)]
    assert acc.stationary_ticks == 0
    assert acc.total_distance_this_round == pytest.approx(5.0)


def test_approach_detection() -> None:
    belief_state, accumulators, knowledge = _initialized_state()
    positions_by_tick = {
        1: {1: (0, 100), 2: (100, 100)},
        2: {1: (80, 100), 2: (100, 100)},
    }

    for tick, positions in positions_by_tick.items():
        belief_state.tick = tick
        belief_state.players = {
            index: PlayerInfo(position=(*position, tick))
            for index, position in positions.items()
        }
        update_position_tracker(accumulators, knowledge, belief_state)

    acc = accumulators.player_accumulators[_pid(1, belief_state)]
    assert _pid(2, belief_state) in acc.distinct_players_approached


def test_total_distance_accumulates() -> None:
    belief_state, accumulators, knowledge = _initialized_state()

    for tick, position in [(1, (0, 0)), (2, (3, 4)), (3, (6, 8))]:
        belief_state.tick = tick
        belief_state.players[1] = PlayerInfo(position=(*position, tick))
        update_position_tracker(accumulators, knowledge, belief_state)

    acc = accumulators.player_accumulators[_pid(1, belief_state)]
    assert acc.total_distance_this_round == pytest.approx(10.0)


def test_minimap_tracker_updates_knowledge_and_accumulator() -> None:
    belief_state, accumulators, knowledge = _initialized_state(tick=42)
    belief_state.minimap_sightings = [
        MinimapSighting(
            color=PLAYER_COLORS[1],
            position=(120, 80),
            tick=42,
        )
    ]

    update_minimap_tracker(accumulators, knowledge, belief_state)

    player_id = _pid(1, belief_state)
    assert knowledge[player_id].last_seen_position == (120, 80)
    acc = accumulators.player_accumulators[player_id]
    assert acc.visible_ticks_this_round == 1
    assert list(acc.position_history) == [(42, 120, 80)]


def test_minimap_tracker_skips_self_index_for_repeated_color() -> None:
    belief_state, accumulators, knowledge = _initialized_state(
        tick=12,
        player_count=10,
        my_index=0,
        my_color=PLAYER_COLORS[0],
    )
    belief_state.minimap_sightings = [
        MinimapSighting(
            color=PLAYER_COLORS[0],
            position=(140, 70),
            tick=12,
        )
    ]

    update_minimap_tracker(accumulators, knowledge, belief_state)

    repeated_color_player = _pid(8, belief_state)
    assert repeated_color_player in knowledge
    assert knowledge[repeated_color_player].last_seen_position == (140, 70)
    assert _pid(0, belief_state) not in knowledge


def test_whisper_entry_not_counted_when_not_in_whisper() -> None:
    belief_state, accumulators, _knowledge = _initialized_state(
        in_whisper=False,
        whisper_occupants=[1, 2],
    )

    update_whisper_tracker(accumulators, belief_state)

    assert accumulators.player_accumulators == {}
    assert belief_state.extra["_eurydice_prev_whisper_occupants"] == [1, 2]


def test_whisper_partners_tracked_bidirectionally() -> None:
    belief_state, accumulators, _knowledge = _initialized_state(in_whisper=True, whisper_occupants=[0, 1, 2])

    update_whisper_tracker(accumulators, belief_state)

    pid0 = _pid(0, belief_state)
    pid1 = _pid(1, belief_state)
    pid2 = _pid(2, belief_state)
    assert accumulators.player_accumulators[pid0].whisper_partners_this_round == {pid1, pid2}
    assert accumulators.player_accumulators[pid1].whisper_partners_this_round == {pid0, pid2}
    assert accumulators.player_accumulators[pid2].whisper_partners_this_round == {pid0, pid1}


def test_whisper_time_increments_per_tick() -> None:
    belief_state, accumulators, _knowledge = _initialized_state(in_whisper=True, whisper_occupants=[1])

    for tick in range(1, 4):
        belief_state.tick = tick
        update_whisper_tracker(accumulators, belief_state)

    acc = accumulators.player_accumulators[_pid(1, belief_state)]
    assert acc.whisper_entries_this_round == 1
    assert acc.total_time_in_whispers_ticks == 3



def test_multi_occupant_whisper_drops_attribution() -> None:
    belief_state, accumulators, knowledge = _initialized_state(
        in_whisper=True, whisper_occupants=[0, 1, 2], chat_history=[_system_message("OFFERED ROLE")]
    )

    update_exchange_tracker(accumulators, knowledge, belief_state)

    # Current gap: system messages in 3+ occupant whispers cannot be attributed
    # because _whisper_other_occupant intentionally returns None.
    assert accumulators.player_accumulators == {}
    assert knowledge == {}


def test_offer_role_creates_role_offers_made() -> None:
    belief_state, accumulators, knowledge = _initialized_state(
        in_whisper=True, whisper_occupants=[0, 1], chat_history=[_system_message("OFFERED ROLE")]
    )

    update_exchange_tracker(accumulators, knowledge, belief_state)

    acc = accumulators.player_accumulators[_pid(1, belief_state)]
    assert acc.role_offers_made == 1
    assert acc.color_offers_made == 0


def test_ticks_before_first_offer_calculated() -> None:
    belief_state, accumulators, knowledge = _initialized_state(tick=100, in_whisper=True, whisper_occupants=[0, 1])
    update_whisper_tracker(accumulators, belief_state)

    belief_state.tick = 115
    belief_state.chat_history = [_system_message("OFFERED ROLE", tick=115)]
    update_exchange_tracker(accumulators, knowledge, belief_state)

    acc = accumulators.player_accumulators[_pid(1, belief_state)]
    assert acc.whisper_entry_ticks == [100]
    assert acc.ticks_before_first_offer == 15


def test_exchange_tracker_and_chat_tracker_no_double_count() -> None:
    belief_state, accumulators, knowledge = _initialized_state(
        in_whisper=True,
        whisper_occupants=[0, 1],
        chat_history=[
            _system_message("OFFERED ROLE"),
            _player_message(1, "I am Cerberus"),
        ],
    )

    update_exchange_tracker(accumulators, knowledge, belief_state)
    update_chat_tracker(accumulators, knowledge, belief_state)

    acc = accumulators.player_accumulators[_pid(1, belief_state)]
    pk = knowledge[_pid(1, belief_state)]
    assert acc.role_offers_made == 1
    assert acc.whisper_messages_sent == 1
    assert acc.global_messages_sent_this_round == 0
    assert acc.message_content_log == [(1, "I am Cerberus")]
    assert pk.claims_made == ["I am Cerberus"]



def test_aggressive_probing_fires_at_threshold() -> None:
    belief_state = _belief_state(tick=299)
    accumulators = GlobalAccumulators(round_start_tick=0)
    acc = PlayerAccumulator(player_id=_pid(1, belief_state), whisper_entries_this_round=3)

    flags = derive_behavioral_flags(acc, {}, accumulators, belief_state)

    assert "aggressive_probing" in flags


def test_aggressive_probing_does_not_fire_below_threshold() -> None:
    belief_state = _belief_state(tick=120)
    accumulators = GlobalAccumulators(round_start_tick=0)
    acc = PlayerAccumulator(player_id=_pid(1, belief_state), whisper_entries_this_round=1)

    flags = derive_behavioral_flags(acc, {}, accumulators, belief_state)

    assert "aggressive_probing" not in flags


def test_avoids_interaction_requires_all_conditions() -> None:
    belief_state = _belief_state(tick=250)
    accumulators = GlobalAccumulators(round_start_tick=0)
    player_id = _pid(1, belief_state)

    incomplete_cases = [
        PlayerAccumulator(player_id=player_id, visible_ticks_this_round=200, whisper_entries_this_round=0, stationary_ticks=101),
        PlayerAccumulator(player_id=player_id, visible_ticks_this_round=201, whisper_entries_this_round=1, stationary_ticks=101),
        PlayerAccumulator(player_id=player_id, visible_ticks_this_round=201, whisper_entries_this_round=0, stationary_ticks=100),
    ]
    for acc in incomplete_cases:
        flags = derive_behavioral_flags(acc, {}, accumulators, belief_state)
        assert "avoids_interaction" not in flags

    complete = PlayerAccumulator(player_id=player_id, visible_ticks_this_round=201, whisper_entries_this_round=0, stationary_ticks=101)
    flags = derive_behavioral_flags(complete, {}, accumulators, belief_state)
    assert "avoids_interaction" in flags


def test_chatty_global_threshold() -> None:
    belief_state = _belief_state(tick=50)
    accumulators = GlobalAccumulators(round_start_tick=0)
    player_id = _pid(1, belief_state)

    quiet = PlayerAccumulator(player_id=player_id, global_messages_sent_this_round=1)
    chatty = PlayerAccumulator(player_id=player_id, global_messages_sent_this_round=2)

    assert "chatty_global" not in derive_behavioral_flags(quiet, {}, accumulators, belief_state)
    assert "chatty_global" in derive_behavioral_flags(chatty, {}, accumulators, belief_state)


def test_relaxed_after_urgency_requires_cross_round() -> None:
    belief_state = _belief_state(tick=121)
    accumulators = GlobalAccumulators(round_start_tick=0)
    player_id = _pid(1, belief_state)
    acc = PlayerAccumulator(player_id=player_id, max_whisper_entries_any_round=3, whisper_entries_this_round=0)

    flags = derive_behavioral_flags(acc, {}, accumulators, belief_state)

    assert "relaxed_after_urgency" in flags

    belief_state.tick = 120
    assert "relaxed_after_urgency" not in derive_behavioral_flags(acc, {}, accumulators, belief_state)


def test_whispers_with_both_teams() -> None:
    belief_state = _belief_state(tick=50)
    accumulators = GlobalAccumulators(round_start_tick=0)
    player_id = _pid(3, belief_state)
    shades_partner = _pid(1, belief_state)
    nymphs_partner = _pid(2, belief_state)
    knowledge = {
        shades_partner: PlayerKnowledge.create(shades_partner),
        nymphs_partner: PlayerKnowledge.create(nymphs_partner),
    }
    knowledge[shades_partner].team = Team.SHADES
    knowledge[nymphs_partner].team = Team.NYMPHS
    acc = PlayerAccumulator(player_id=player_id, whisper_partners_this_round={shades_partner, nymphs_partner})

    flags = derive_behavioral_flags(acc, knowledge, accumulators, belief_state)

    assert "whispers_with_both_teams" in flags



def test_team_from_player_info_does_not_overwrite_role_exchange() -> None:
    belief_state, _accumulators, knowledge = _initialized_state(my_team="shades")
    belief_state.players[1] = PlayerInfo(team="nymphs")
    player_id = _pid(1, belief_state)
    pk = PlayerKnowledge.create(player_id)
    pk.team = Team.SHADES
    pk.team_source = TeamSource.ROLE_EXCHANGE
    pk.team_confidence = 1.0
    knowledge[player_id] = pk

    run_hard_inferences(knowledge, belief_state)

    assert pk.team is Team.SHADES
    assert pk.team_source is TeamSource.ROLE_EXCHANGE
    assert pk.team_confidence == 1.0


def test_trust_level_hostile_for_enemy() -> None:
    belief_state, _accumulators, knowledge = _initialized_state(my_team="shades")
    player_id = _pid(1, belief_state)
    pk = PlayerKnowledge.create(player_id)
    pk.team = Team.NYMPHS
    pk.team_source = TeamSource.COLOR_EXCHANGE
    knowledge[player_id] = pk

    run_hard_inferences(knowledge, belief_state)

    assert pk.trust_level is TrustLevel.HOSTILE


def test_trust_level_verified_for_role_exchanged() -> None:
    belief_state, _accumulators, knowledge = _initialized_state(my_team="shades")
    player_id = _pid(1, belief_state)
    pk = PlayerKnowledge.create(player_id)
    pk.role = Role.CERBERUS
    pk.role_source = RoleSource.ROLE_EXCHANGE
    pk.team = Team.SHADES
    pk.team_source = TeamSource.ROLE_EXCHANGE
    knowledge[player_id] = pk

    run_hard_inferences(knowledge, belief_state)

    assert pk.trust_level is TrustLevel.VERIFIED



def test_already_probed_player_not_re_tracked_as_unprobed() -> None:
    belief_state, _accumulators, _knowledge = _initialized_state()
    belief_state.players[1] = PlayerInfo(room=Room.UNDERWORLD, team="shades")
    probed = _knowledge_for(
        belief_state,
        1,
        room=Room.UNDERWORLD,
        team=Team.SHADES,
        last_interaction_round=1,
        times_interacted=1,
    )

    state = build_strategic_state(belief_state)

    assert probed.player_id in state.players_probed_this_round
    assert probed.player_id not in state.players_unprobed_in_room


def test_empty_players_dict_no_crash() -> None:
    belief_state = _belief_state(players={})

    eurydice_post_belief_update(belief_state)

    assert belief_state.extra[EURYDICE_ACCUMULATORS].player_accumulators == {}
    assert belief_state.extra[PLAYER_KNOWLEDGE] == {}


def test_chat_claim_does_not_overwrite_mechanical() -> None:
    belief_state, _accumulators, knowledge = _initialized_state(my_team="shades")
    player_id = _pid(1, belief_state)
    pk = PlayerKnowledge.create(player_id)
    pk.role = Role.HADES
    pk.role_source = RoleSource.ROLE_EXCHANGE
    pk.team = Team.SHADES
    pk.team_source = TeamSource.ROLE_EXCHANGE
    pk.claims_about_identity = "I am Persephone"
    knowledge[player_id] = pk

    run_soft_inferences(knowledge, belief_state)

    assert pk.role is Role.HADES
    assert pk.role_source is RoleSource.ROLE_EXCHANGE
    assert pk.team is Team.SHADES
    assert pk.team_source is TeamSource.ROLE_EXCHANGE



def test_critical_override_phase_change_bypasses_hysteresis() -> None:
    belief_state, _accumulators, _knowledge = _initialized_state(tick=20)
    belief_state.extra[LAST_DIRECTIVE_MODE] = "idle"
    belief_state.extra[LAST_DIRECTIVE_TICK] = 0
    belief_state.inferences[LAST_PHASE] = Phase.LOBBY

    directive, inferences = meta_decide(belief_state, ActionMemory())

    assert directive.mode == "probe_systematic"
    assert inferences is not None
    assert inferences[LAST_DIRECTIVE_MODE] == "probe_systematic"
    assert inferences[LAST_DIRECTIVE_TICK] == 20


def test_critical_override_exchange_done_bypasses_hysteresis() -> None:
    belief_state, _accumulators, knowledge = _initialized_state(tick=20)
    belief_state.extra[LAST_DIRECTIVE_MODE] = "idle"
    belief_state.extra[LAST_DIRECTIVE_TICK] = 0
    belief_state.inferences[LAST_EXCHANGE_STATUS] = False
    partner_id = _pid(1, belief_state)
    partner = PlayerKnowledge.create(partner_id)
    partner.role = Role.CERBERUS
    partner.role_source = RoleSource.ROLE_EXCHANGE
    partner.team = Team.SHADES
    partner.team_source = TeamSource.ROLE_EXCHANGE
    partner.has_exchanged_roles_with_us = True
    knowledge[partner_id] = partner

    directive, inferences = meta_decide(belief_state, ActionMemory())

    assert directive.mode == "probe_systematic"
    assert inferences is not None
    assert inferences[LAST_EXCHANGE_STATUS] is True


def test_in_whisper_mode_not_interrupted() -> None:
    belief_state, _accumulators, _knowledge = _initialized_state(
        tick=20,
        view=View.WHISPER,
        in_whisper=True,
    )
    belief_state.extra[LAST_DIRECTIVE_MODE] = "in_whisper"
    belief_state.extra[LAST_DIRECTIVE_TICK] = 0
    belief_state.extra[MODE_COMPLETE] = False

    directive, inferences = meta_decide(belief_state, ActionMemory())

    assert directive == ModeDirective("in_whisper", ModeParams())
    assert inferences is not None
    assert inferences[LAST_DIRECTIVE_MODE] == "in_whisper"


def test_urgency_with_custom_round_schedule() -> None:
    early_state = SimpleNamespace(
        current_round=1,
        round_schedule=[(0, 240), (240, 720), (720, 1680)],
        ticks_remaining_in_phase=120,
        key_exchange_done=False,
    )
    middle_state = SimpleNamespace(
        current_round=2,
        round_schedule=[(0, 240), (240, 720), (720, 1680)],
        ticks_remaining_in_phase=480,
        key_exchange_done=False,
    )
    late_state = SimpleNamespace(
        current_round=3,
        round_schedule=[(0, 240), (240, 720), (720, 1680)],
        ticks_remaining_in_phase=900,
        key_exchange_done=False,
    )

    assert compute_urgency(early_state) is Urgency.CALM
    assert compute_urgency(middle_state) is Urgency.PRESSING
    assert compute_urgency(late_state) is Urgency.PANIC



def test_scout_ignores_already_probed_player() -> None:
    belief_state, _accumulators, _knowledge = _initialized_state(
        position=(50, 50),
        room_size=(100, 100),
    )
    belief_state.players[1] = PlayerInfo(position=(55, 50, belief_state.tick))
    _knowledge_for(belief_state, 1, times_interacted=1)
    mode = ScoutMode()
    mode.mode_enter(belief_state, ActionMemory())

    task = mode.select_task(belief_state, ActionMemory())

    assert task is not None
    assert MODE_COMPLETE not in belief_state.extra
    assert FOUND_TARGET not in belief_state.extra


def test_probe_target_in_range_whisper_creates_whisper() -> None:
    belief_state, _accumulators, _knowledge = _initialized_state(
        position=(50, 50),
        tick=12,
    )
    belief_state.players[1] = PlayerInfo(position=(50 + INTERACTION_RANGE - 1, 50, 12))
    mode = ProbeTargetMode()
    mode.params = ProbeTargetParams(target=_pid(1, belief_state))

    task = mode.select_task(belief_state, ActionMemory())

    assert isinstance(task, CreateWhisperTask)
    assert belief_state.extra[MODE_COMPLETE] is True
    assert belief_state.extra[FOUND_TARGET] == _pid(1, belief_state)


def test_probe_target_in_range_whisper_requests_entry() -> None:
    belief_state, _accumulators, _knowledge = _initialized_state(
        position=(50, 50),
        tick=12,
    )
    belief_state.players[1] = PlayerInfo(
        position=(50 + INTERACTION_RANGE - 1, 50, 12),
        last_seen_in_whisper=12,
    )
    mode = ProbeTargetMode()
    mode.params = ProbeTargetParams(target=_pid(1, belief_state))

    task = mode.select_task(belief_state, ActionMemory())

    assert isinstance(task, RequestEntryTask)
    assert task.player_index == 1
    assert belief_state.extra[MODE_COMPLETE] is True


def test_probe_target_moves_to_last_known_position_without_visible_player() -> None:
    belief_state, _accumulators, _knowledge = _initialized_state(
        position=(50, 50),
        tick=12,
        players={},
    )
    target = _pid(1, belief_state)
    belief_state.extra[PLAYER_KNOWLEDGE][target] = PlayerKnowledge.create(target)
    belief_state.extra[PLAYER_KNOWLEDGE][target].last_seen_position = (90, 50)
    mode = ProbeTargetMode()
    mode.params = ProbeTargetParams(target=target)

    task = mode.select_task(belief_state, ActionMemory())

    assert isinstance(task, MoveToTask)
    assert (task.x, task.y) == (90, 50)
    assert MODE_COMPLETE not in belief_state.extra


def test_probe_target_creates_whisper_at_last_known_position() -> None:
    belief_state, _accumulators, _knowledge = _initialized_state(
        position=(50, 50),
        tick=12,
        players={},
    )
    target = _pid(1, belief_state)
    belief_state.extra[PLAYER_KNOWLEDGE][target] = PlayerKnowledge.create(target)
    belief_state.extra[PLAYER_KNOWLEDGE][target].last_seen_position = (
        50 + INTERACTION_RANGE - 1,
        50,
    )
    mode = ProbeTargetMode()
    mode.params = ProbeTargetParams(target=target)

    task = mode.select_task(belief_state, ActionMemory())

    assert isinstance(task, CreateWhisperTask)
    assert belief_state.extra[MODE_COMPLETE] is True
    assert belief_state.extra[FOUND_TARGET] == target


def test_probe_systematic_score_filters_wrong_team() -> None:
    belief_state, _accumulators, _knowledge = _initialized_state(position=(50, 50))
    player_id = _pid(1, belief_state)
    _knowledge_for(belief_state, 1, team=Team.NYMPHS)
    mode = ProbeSystematicMode()
    mode.params = ProbeSystematicParams(target_team=Team.SHADES)

    score = mode.score_target(
        belief_state,
        player_id,
        target_position=(50, 50),
        self_position=(50, 50),
    )

    assert score < 0


def test_probe_systematic_score_prefers_unprobed() -> None:
    belief_state, _accumulators, _knowledge = _initialized_state(
        tick=100,
        position=(50, 50),
    )
    unprobed_id = _pid(1, belief_state)
    recently_interacted_id = _pid(2, belief_state)
    _knowledge_for(belief_state, 1, times_interacted=0)
    _knowledge_for(
        belief_state,
        2,
        times_interacted=1,
        last_interaction_tick=90,
    )
    mode = ProbeSystematicMode()

    unprobed_score = mode.score_target(
        belief_state,
        unprobed_id,
        target_position=(60, 50),
        self_position=(50, 50),
    )
    recently_interacted_score = mode.score_target(
        belief_state,
        recently_interacted_id,
        target_position=(60, 50),
        self_position=(50, 50),
    )

    assert unprobed_score > recently_interacted_score


def test_probe_systematic_no_targets_signals_complete() -> None:
    belief_state, _accumulators, _knowledge = _initialized_state(players={})
    mode = ProbeSystematicMode()

    task = mode.select_task(belief_state, ActionMemory())

    # With no targets visible, probe_systematic wanders instead of giving up
    assert isinstance(task, MoveToTask)
    assert MODE_COMPLETE not in belief_state.extra


def test_probe_systematic_targets_knowledge_last_seen_position() -> None:
    belief_state, _accumulators, _knowledge = _initialized_state(
        position=(50, 50),
        players={},
    )
    target = _pid(1, belief_state)
    belief_state.extra[PLAYER_KNOWLEDGE][target] = PlayerKnowledge.create(target)
    belief_state.extra[PLAYER_KNOWLEDGE][target].last_seen_position = (90, 50)
    mode = ProbeSystematicMode()

    task = mode.select_task(belief_state, ActionMemory())

    assert isinstance(task, MoveToTask)
    assert (task.x, task.y) == (90, 50)


def test_scout_finds_nearby_knowledge_player() -> None:
    belief_state, _accumulators, _knowledge = _initialized_state(
        position=(50, 50),
        players={},
    )
    target = _pid(1, belief_state)
    belief_state.extra[PLAYER_KNOWLEDGE][target] = PlayerKnowledge.create(target)
    belief_state.extra[PLAYER_KNOWLEDGE][target].last_seen_position = (
        50 + INTERACTION_RANGE - 1,
        50,
    )
    mode = ScoutMode()
    mode.mode_enter(belief_state, ActionMemory())

    task = mode.select_task(belief_state, ActionMemory())

    assert isinstance(task, IdleTask)
    assert belief_state.extra[MODE_COMPLETE] is True
    assert belief_state.extra[FOUND_TARGET] == target


def test_scout_non_overworld_view_returns_idle() -> None:
    belief_state, _accumulators, _knowledge = _initialized_state(
        view=View.WHISPER,
        in_whisper=True,
    )
    mode = ScoutMode()

    task = mode.select_task(belief_state, ActionMemory())

    assert isinstance(task, IdleTask)
    assert MODE_COMPLETE not in belief_state.extra



def test_pipeline_accumulation_over_10_ticks() -> None:
    belief_state = _belief_state()

    for tick in range(1, 11):
        belief_state.tick = tick
        belief_state.players[1] = PlayerInfo(position=(20, 30, tick))
        eurydice_post_belief_update(belief_state)

    accumulators = belief_state.extra[EURYDICE_ACCUMULATORS]
    acc = accumulators.player_accumulators[_pid(1, belief_state)]
    assert acc.visible_ticks_this_round == 10
    assert len(acc.position_history) == 10
    assert belief_state.extra[PLAYER_KNOWLEDGE][_pid(1, belief_state)].last_seen_position == (
        20,
        30,
    )


def test_full_pipeline_to_meta_decide_to_mode() -> None:
    belief_state = _belief_state(position=(50, 50))

    for tick in range(1, 6):
        belief_state.tick = tick
        belief_state.players[1] = PlayerInfo(
            position=(60, 50, tick),
            room=Room.UNDERWORLD,
            role="cerberus",
        )
        eurydice_post_belief_update(belief_state)

    directive, inferences = meta_decide(belief_state, ActionMemory())

    strategic_state = belief_state.extra[STRATEGIC_STATE]
    assert directive.mode == "probe_target"
    assert inferences is not None
    assert strategic_state.my_role is Role.HADES
    assert strategic_state.my_team is Team.SHADES
    assert strategic_state.current_round == 1
    assert _pid(1, belief_state) in strategic_state.players_in_my_room
    assert strategic_state.key_partner_found is True
