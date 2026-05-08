"""Eurydice Stage 2 outer-loop mode selection."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from orpheus.action_memory import ActionMemory
from orpheus.belief_state import BeliefState
from orpheus.mode import ModeDirective, ModeParams
from orpheus.perception.types import View

from .ext_keys import (
    EURYDICE_ACCUMULATORS,
    LAST_DIRECTIVE_MODE,
    LAST_DIRECTIVE_TICK,
    LAST_EXCHANGE_STATUS,
    LAST_PARTNER_FOUND,
    LAST_PHASE,
    MODE_COMPLETE,
    PLAYER_KNOWLEDGE,
    STRATEGIC_STATE,
)
from .evaluators import ROLE_EVALUATORS
from .knowledge import PlayerKnowledge
from .pipeline import _parse_role_string, _parse_team_string, player_index_to_id
from .strategic_state import StrategicState
from .types import Phase, PlayerID, Role, Team, Urgency

TICKS_PER_SECOND = 24
MIN_MODE_DURATION_TICKS = 48
DEFAULT_ROUND_TICKS = 15 * TICKS_PER_SECOND
DEFAULT_ROUND_COUNT = 3

def meta_decide(
    belief_state: BeliefState,
    action_memory: ActionMemory,
) -> tuple[ModeDirective, dict | None]:
    """Select the next mode directive from the current belief snapshot."""
    state = build_strategic_state(belief_state)
    mode_complete = bool(belief_state.extra.pop(MODE_COMPLETE, False))

    override = _phase_override(belief_state)
    if override is not None:
        return _finish(override, state, belief_state)

    current_mode = _last_mode(belief_state)

    if (
        not mode_complete
        and current_mode == "in_whisper"
        and belief_state.view is View.WHISPER
    ):
        return _finish(_directive(current_mode), state, belief_state)

    ticks_in_mode = belief_state.tick - _last_tick(belief_state)

    if (
        not mode_complete
        and current_mode is not None
        and ticks_in_mode < MIN_MODE_DURATION_TICKS
        and not _critical_override(state, belief_state.inferences)
    ):
        return _finish(_directive(current_mode), state, belief_state)

    if state.my_role is None:
        return _finish(_directive("idle"), state, belief_state)

    evaluator = ROLE_EVALUATORS.get(state.my_role.name.lower())
    directive = (
        evaluator(state, belief_state, action_memory)
        if evaluator
        else _directive("idle")
    )
    return _finish(directive, state, belief_state)


def build_strategic_state(belief_state: BeliefState) -> StrategicState:
    """Rebuild Eurydice's strategic summary from belief_state.extra."""
    state = StrategicState()
    state.my_role = _parse_role_string(belief_state.my_role)
    state.my_team = _parse_team_string(belief_state.my_team) or _team_for_role(
        state.my_role
    )

    state.my_room = belief_state.my_room or belief_state.room
    state.my_player_id = _my_player_id(belief_state)
    state.current_round = belief_state.round or 0
    state.current_phase = _phase_from_view(belief_state.view)
    state.round_schedule = list(belief_state.round_schedule)
    state.round_start_tick = _round_start_tick(belief_state, state)
    state.ticks_remaining_in_phase = _ticks_remaining(belief_state, state)
    state.mode_entered_tick = _last_tick(belief_state)

    knowledge = _knowledge(belief_state)
    _populate_rooms(state, belief_state, knowledge)
    _populate_keys(state, belief_state, knowledge)
    _populate_leadership(state, belief_state, knowledge)
    _populate_probe_budget(state, belief_state, knowledge)
    state.urgency = compute_urgency(state)

    state.enemy_key_exchange_likely = (
        state.enemy_key_exchange_done is True
        or _enemy_exchange_likely_from_flags(state, knowledge)
    )

    return state


def compute_urgency(state: StrategicState) -> Urgency:
    """Compute urgency from relative round position and elapsed time."""
    durations = _round_durations(state.round_schedule)
    if state.current_round <= 0 or not durations:
        return Urgency.CALM

    total_rounds = len(durations)
    round_index = min(max(state.current_round - 1, 0), total_rounds - 1)
    rounds_remaining = total_rounds - state.current_round
    round_duration = max(durations[round_index], 1)
    remaining = max(0, min(state.ticks_remaining_in_phase, round_duration))
    round_elapsed = (round_duration - remaining) / round_duration
    game_elapsed = (
        sum(durations[:round_index]) + round_duration - remaining
    ) / max(sum(durations), 1)

    if rounds_remaining == 0 and not state.key_exchange_done:
        return Urgency.PANIC
    if rounds_remaining == 0 and round_elapsed > 0.8:
        return Urgency.PANIC
    if rounds_remaining == 1 and not state.key_exchange_done:
        return Urgency.PRESSING
    if rounds_remaining == 0:
        return Urgency.PRESSING
    if game_elapsed > 0.5 and not state.key_exchange_done:
        return Urgency.PRESSING
    return Urgency.CALM


def _phase_override(belief_state: BeliefState) -> ModeDirective | None:
    if belief_state.view in {
        View.LOBBY,
        View.ROSTER_REVEAL,
        View.ROLE_REVEAL,
        View.HOSTAGE_EXCHANGE,
        View.REVEAL,
        View.GAME_OVER,
    }:
        return _directive("idle")
    if belief_state.view is View.HOSTAGE_SELECT:
        return _directive("hostage_select" if belief_state.is_leader else "hold_position")
    if belief_state.view is View.LEADER_SUMMIT and belief_state.is_leader:
        return _directive("summit_interact")
    return None


def _finish(
    directive: ModeDirective,
    state: StrategicState,
    belief_state: BeliefState,
) -> tuple[ModeDirective, dict | None]:
    inferences = dict(belief_state.inferences)
    inferences.update(
        {
            STRATEGIC_STATE: state,
            LAST_PHASE: state.current_phase,
            LAST_EXCHANGE_STATUS: state.key_exchange_done,
            LAST_PARTNER_FOUND: state.key_partner_found,
        }
    )

    last_mode, last_tick = _last_mode(belief_state), _last_tick(belief_state)
    if last_mode != directive.mode:
        last_tick = belief_state.tick
    inferences.update(
        {
            LAST_DIRECTIVE_MODE: directive.mode,
            LAST_DIRECTIVE_TICK: last_tick,
        }
    )

    belief_state.extra.update(
        {
            STRATEGIC_STATE: state,
            LAST_DIRECTIVE_MODE: directive.mode,
            LAST_DIRECTIVE_TICK: last_tick,
        }
    )

    return directive, inferences


def _critical_override(state: StrategicState, inferences: dict) -> bool:
    last_phase = inferences.get(LAST_PHASE)
    if last_phase is not None and not _same_phase(last_phase, state.current_phase):
        return True
    last_exchange = inferences.get(LAST_EXCHANGE_STATUS)
    if last_exchange is not None and bool(last_exchange) != state.key_exchange_done:
        return True
    last_partner = inferences.get(LAST_PARTNER_FOUND)
    return (
        last_partner is not None
        and bool(last_partner) != state.key_partner_found
    )


def _populate_rooms(
    state: StrategicState,
    belief_state: BeliefState,
    knowledge: dict[PlayerID, PlayerKnowledge],
) -> None:
    room_team = {
        player_id: (record.room, record.team)
        for player_id, record in knowledge.items()
    }

    for index, info in belief_state.players.items():
        player_id = player_index_to_id(index, belief_state)
        if player_id is None:
            continue
        room_team.setdefault(player_id, (info.room, _parse_team_string(info.team)))
    if state.my_player_id is not None and state.my_room is not None:
        room_team.setdefault(state.my_player_id, (state.my_room, state.my_team))

    for player_id, (room, team) in room_team.items():
        if room is None:
            state.players_room_unknown.append(player_id)
            continue
        if room == state.my_room:
            state.players_in_my_room.append(player_id)
            if player_id == state.my_player_id:
                continue
            if team is None:
                continue
            target = (
                state.allies_in_my_room
                if team == state.my_team
                else state.enemies_in_my_room
            )
            target.append(player_id)
            continue

        state.players_in_other_room.append(player_id)

    state.total_player_count = belief_state.player_count or max(
        len(room_team), len(belief_state.players)
    )

    estimate = (
        max(1, state.total_player_count // 2)
        if state.total_player_count
        else 0
    )
    state.room_player_count = max(len(state.players_in_my_room), estimate)
    state.usurp_votes_needed = (
        state.room_player_count // 2 + 1
        if state.room_player_count
        else 0
    )


def _populate_keys(
    state: StrategicState,
    belief_state: BeliefState,
    knowledge: dict[PlayerID, PlayerKnowledge],
) -> None:
    partner = _partner_role(state.my_role)
    enemy_primary, enemy_partner = _enemy_key_roles(state.my_team)
    for player_id, record in knowledge.items():
        if partner is not None and record.role is partner:
            state.key_partner_found = True
            state.key_partner_id = player_id
            state.key_partner_room = record.room
            state.key_exchange_done = (
                state.key_exchange_done or record.has_exchanged_roles_with_us
            )
        if enemy_primary is None:
            continue
        if record.role is not enemy_primary:
            continue
        state.enemy_key_role_id = player_id
        state.enemy_key_role_room = record.room

    if belief_state.my_exchange_partner is not None and partner is not None:
        player_id = player_index_to_id(belief_state.my_exchange_partner, belief_state)
        record = knowledge.get(player_id) if player_id is not None else None
        if record is not None and record.role is partner:
            state.key_exchange_done = state.key_partner_found = True
            state.key_partner_id, state.key_partner_room = player_id, record.room

    roles = {record.role for record in knowledge.values()}
    if enemy_primary in roles and enemy_partner in roles:
        state.enemy_key_exchange_done = None


def _populate_leadership(
    state: StrategicState,
    belief_state: BeliefState,
    knowledge: dict[PlayerID, PlayerKnowledge],
) -> None:
    state.am_leader = belief_state.is_leader
    if state.am_leader:
        state.room_leader_id = state.my_player_id
        state.room_leader_team = state.my_team
        return
    for player_id, record in knowledge.items():
        if not record.is_leader:
            continue
        if record.room != state.my_room:
            continue
        state.room_leader_id = player_id
        state.room_leader_team = record.team
        return
    leader_color = belief_state.leader_colors.get(state.my_room)
    if leader_color is None:
        return
    for player_id, record in knowledge.items():
        if player_id[0] != leader_color:
            continue
        state.room_leader_id = player_id
        state.room_leader_team = record.team
        return
    if (
        state.my_player_id is not None
        and state.my_player_id[0] == leader_color
    ):
        state.room_leader_id = state.my_player_id
        state.room_leader_team = state.my_team


def _populate_probe_budget(
    state: StrategicState,
    belief_state: BeliefState,
    knowledge: dict[PlayerID, PlayerKnowledge],
) -> None:
    state.players_probed_this_round = [
        player_id
        for player_id, record in knowledge.items()
        if record.last_interaction_round == state.current_round
        and record.times_interacted > 0
    ]

    probed = set(state.players_probed_this_round)
    state.players_unprobed_in_room = [
        player_id
        for player_id in state.players_in_my_room
        if player_id != state.my_player_id
        and player_id not in probed
    ]

    room_count = max(state.room_player_count, 1)
    cycle_ticks = max(MIN_MODE_DURATION_TICKS, _current_duration(state) // room_count)
    remaining = max(0, state.ticks_remaining_in_phase // cycle_ticks)
    acc = belief_state.extra.get(EURYDICE_ACCUMULATORS)
    state.probe_cycles_remaining = max(
        0,
        remaining - max(getattr(acc, "our_probe_cycles_this_round", 0), 0),
    )
    state.probe_coverage_fraction = state.probe_cycles_remaining / room_count


def _round_start_tick(belief_state: BeliefState, state: StrategicState) -> int:
    acc = belief_state.extra.get(EURYDICE_ACCUMULATORS)
    if getattr(acc, "round_start_tick", 0):
        return acc.round_start_tick
    if belief_state.timer_secs is None:
        return 0
    return belief_state.tick - max(
        0,
        _current_duration(state) - belief_state.timer_secs * TICKS_PER_SECOND,
    )


def _ticks_remaining(belief_state: BeliefState, state: StrategicState) -> int:
    if belief_state.timer_secs is not None:
        return max(0, belief_state.timer_secs * TICKS_PER_SECOND)
    if state.round_start_tick:
        return max(
            0,
            _current_duration(state) - (belief_state.tick - state.round_start_tick),
        )
    return _current_duration(state)


def _round_durations(schedule: Sequence[Any]) -> list[int]:
    if not schedule:
        return [DEFAULT_ROUND_TICKS] * DEFAULT_ROUND_COUNT
    durations = []
    for entry in schedule:
        if isinstance(entry, (tuple, list)) and len(entry) >= 2:
            first, second = int(entry[0]), int(entry[1])
            duration = (
                second - first
                if second > first and second - first >= MIN_MODE_DURATION_TICKS
                else _to_ticks(first)
            )
        else:
            duration = _to_ticks(int(entry))
        durations.append(max(1, duration))
    return durations


def _current_duration(state: StrategicState) -> int:
    durations = _round_durations(state.round_schedule)
    index = min(max(state.current_round - 1, 0), len(durations) - 1)
    return durations[index]


def _to_ticks(value: int) -> int:
    if value <= 300:
        return value * TICKS_PER_SECOND
    return value


def _directive(mode: str) -> ModeDirective:
    return ModeDirective(mode, ModeParams())


def _knowledge(belief_state: BeliefState) -> dict[PlayerID, PlayerKnowledge]:
    raw = belief_state.extra.get(PLAYER_KNOWLEDGE, {})
    if isinstance(raw, dict):
        return raw
    return {}


def _last_mode(belief_state: BeliefState) -> str | None:
    return belief_state.extra.get(
        LAST_DIRECTIVE_MODE, belief_state.inferences.get(LAST_DIRECTIVE_MODE)
    )


def _last_tick(belief_state: BeliefState) -> int:
    raw = belief_state.extra.get(
        LAST_DIRECTIVE_TICK, belief_state.inferences.get(LAST_DIRECTIVE_TICK, 0)
    )
    if isinstance(raw, int):
        return raw
    return 0


def _my_player_id(belief_state: BeliefState) -> PlayerID | None:
    if belief_state.my_index is not None:
        return player_index_to_id(belief_state.my_index, belief_state)
    if belief_state.my_color is None or belief_state.my_shape is None:
        return None
    return (
        belief_state.my_color,
        int(getattr(belief_state.my_shape, "value", belief_state.my_shape)),
    )


def _phase_from_view(view: View) -> Phase:
    return {
        View.LOBBY: Phase.LOBBY,
        View.ROSTER_REVEAL: Phase.ROSTER_REVEAL,
        View.ROLE_REVEAL: Phase.ROLE_REVEAL,
        View.PLAYING: Phase.PLAYING,
        View.HOSTAGE_SELECT: Phase.HOSTAGE_SELECT,
        View.LEADER_SUMMIT: Phase.LEADER_SUMMIT,
        View.HOSTAGE_EXCHANGE: Phase.HOSTAGE_EXCHANGE,
        View.REVEAL: Phase.REVEAL,
        View.GAME_OVER: Phase.GAME_OVER,
    }.get(view, Phase.PLAYING)


def _team_for_role(role: Role | None) -> Team | None:
    if role in (Role.HADES, Role.CERBERUS, Role.SHADE):
        return Team.SHADES
    if role in (Role.PERSEPHONE, Role.DEMETER, Role.NYMPH):
        return Team.NYMPHS
    return None


def _partner_role(role: Role | None) -> Role | None:
    return {
        Role.HADES: Role.CERBERUS,
        Role.CERBERUS: Role.HADES,
        Role.PERSEPHONE: Role.DEMETER,
        Role.DEMETER: Role.PERSEPHONE,
    }.get(role)


def _enemy_key_roles(team: Team | None) -> tuple[Role | None, Role | None]:
    if team is Team.SHADES:
        return Role.PERSEPHONE, Role.DEMETER
    if team is Team.NYMPHS:
        return Role.HADES, Role.CERBERUS
    return None, None


def _enemy_exchange_likely_from_flags(
    state: StrategicState,
    knowledge: dict[PlayerID, PlayerKnowledge],
) -> bool:
    roles = set(_enemy_key_roles(state.my_team))
    flags = {"relaxed_after_urgency", "co_seeking_positioning"}
    return any(
        r.role in roles and bool(r.behavioral_flags & flags)
        for r in knowledge.values()
    )


def _same_phase(value: object, phase: Phase) -> bool:
    if isinstance(value, Phase):
        return value is phase
    return isinstance(value, str) and (
        value == phase.name or value.lower() == phase.name.lower()
    )
