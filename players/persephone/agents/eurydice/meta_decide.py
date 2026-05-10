"""Eurydice Stage 2 outer-loop mode selection."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import asdict, is_dataclass
from typing import Any

from orpheus.action_memory import ActionMemory
from orpheus.belief_state import BeliefState
from orpheus.logging import LogLevel
from orpheus.mode import ModeDirective, ModeParams
from orpheus.perception.types import View

from .ext_keys import (
    EURYDICE_ACCUMULATORS,
    INFO_SCREEN_RECONCILE_PENDING,
    LAST_DIRECTIVE,
    LAST_NON_WHISPER_DIRECTIVE,
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
from .log import logger
from .pipeline import _parse_role_string, _parse_team_string, player_index_to_id
from .strategic_state import StrategicState
from .types import Phase, PlayerID, Role, Team, Urgency

TICKS_PER_SECOND = 24
MIN_MODE_DURATION_TICKS = 48
DEFAULT_ROUND_TICKS = 15 * TICKS_PER_SECOND
DEFAULT_ROUND_COUNT = 3
_PREV_STRATEGIC_KEY = "_eurydice_prev_strategic"

def meta_decide(
    belief_state: BeliefState,
    action_memory: ActionMemory,
) -> tuple[ModeDirective, dict | None]:
    """Select the next mode directive from the current belief snapshot."""
    state = build_strategic_state(belief_state)
    mode_complete = bool(belief_state.extra.pop(MODE_COMPLETE, False))
    current_mode = _last_mode(belief_state)
    ticks_in_mode = belief_state.tick - _last_tick(belief_state)

    override = _phase_override(belief_state)
    if override is not None:
        return _finish(
            override,
            state,
            belief_state,
            reason="phase_override",
            evaluator=None,
            mode_complete=mode_complete,
            ticks_in_mode=ticks_in_mode,
        )

    if belief_state.view is View.WHISPER:
        return _finish(
            _directive("in_whisper"),
            state,
            belief_state,
            reason="whisper_override",
            evaluator=None,
            mode_complete=mode_complete,
            ticks_in_mode=ticks_in_mode,
        )

    reconcile_override = _info_screen_reconcile_override(belief_state)
    if reconcile_override is not None:
        return _finish(
            reconcile_override,
            state,
            belief_state,
            reason="info_screen_reconcile_pending",
            evaluator=None,
            mode_complete=mode_complete,
            ticks_in_mode=ticks_in_mode,
        )

    if (
        not mode_complete
        and current_mode is not None
        and ticks_in_mode < MIN_MODE_DURATION_TICKS
        and not _critical_override(state, belief_state.inferences)
    ):
        return _finish(
            _last_directive(belief_state) or _directive(current_mode),
            state,
            belief_state,
            reason="min_duration_hold",
            evaluator=None,
            mode_complete=mode_complete,
            ticks_in_mode=ticks_in_mode,
        )

    if state.my_role is None:
        return _finish(
            _directive("probe_systematic"),
            state,
            belief_state,
            reason="no_role_fallback",
            evaluator=None,
            mode_complete=mode_complete,
            ticks_in_mode=ticks_in_mode,
        )

    evaluator = ROLE_EVALUATORS.get(state.my_role.name.lower())
    directive = (
        evaluator(state, belief_state, action_memory)
        if evaluator
        else _directive("idle")
    )
    return _finish(
        directive,
        state,
        belief_state,
        reason="evaluator",
        evaluator=state.my_role.name.lower() if evaluator else None,
        mode_complete=mode_complete,
        ticks_in_mode=ticks_in_mode,
    )


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
    state.match_roles = list(belief_state.match_roles)
    state.missing_roles = list(belief_state.missing_roles)
    state.echo_substitutions = list(belief_state.echo_substitutions)
    state.spy_in_game_config = belief_state.spy_in_game_config
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
    if belief_state.view is View.INFO_SCREEN:
        return _directive("check_info_screen")
    return None


def _info_screen_reconcile_override(
    belief_state: BeliefState,
) -> ModeDirective | None:
    if not belief_state.extra.get(INFO_SCREEN_RECONCILE_PENDING):
        return None
    if belief_state.view not in {View.PLAYING, View.GLOBAL_CHAT, View.INFO_SCREEN}:
        return None
    return _directive("check_info_screen")


def _finish(
    directive: ModeDirective,
    state: StrategicState,
    belief_state: BeliefState,
    *,
    reason: str,
    evaluator: str | None,
    mode_complete: bool,
    ticks_in_mode: int,
) -> tuple[ModeDirective, dict | None]:
    _log_strategic_state(belief_state, state)
    _log_meta_decide_reason(
        directive,
        reason=reason,
        evaluator=evaluator,
        mode_complete=mode_complete,
        ticks_in_mode=ticks_in_mode,
    )
    inferences = dict(belief_state.inferences)
    inferences.update(
        {
            STRATEGIC_STATE: state,
            LAST_PHASE: state.current_phase,
            LAST_EXCHANGE_STATUS: state.key_exchange_done,
            LAST_PARTNER_FOUND: state.key_partner_found,
        }
    )
    if _PREV_STRATEGIC_KEY in belief_state.extra:
        inferences[_PREV_STRATEGIC_KEY] = belief_state.extra[_PREV_STRATEGIC_KEY]

    last_mode, last_tick = _last_mode(belief_state), _last_tick(belief_state)
    if last_mode != directive.mode:
        last_tick = belief_state.tick
    inferences.update(
        {
            LAST_DIRECTIVE_MODE: directive.mode,
            LAST_DIRECTIVE_TICK: last_tick,
            LAST_DIRECTIVE: directive,
        }
    )
    if directive.mode != "in_whisper":
        inferences[LAST_NON_WHISPER_DIRECTIVE] = directive

    belief_state.extra.update(
        {
            STRATEGIC_STATE: state,
            LAST_DIRECTIVE_MODE: directive.mode,
            LAST_DIRECTIVE_TICK: last_tick,
            LAST_DIRECTIVE: directive,
        }
    )
    if directive.mode != "in_whisper":
        belief_state.extra[LAST_NON_WHISPER_DIRECTIVE] = directive

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


def _log_meta_decide_reason(
    directive: ModeDirective,
    *,
    reason: str,
    evaluator: str | None,
    mode_complete: bool,
    ticks_in_mode: int,
) -> None:
    if logger:
        logger.event(
            "meta_decide_reason",
            {
                "reason": reason,
                "mode": directive.mode,
                "evaluator": evaluator,
                "mode_complete": bool(mode_complete),
                "ticks_in_mode": int(ticks_in_mode),
                "params": _params_event_value(directive.params),
            },
            LogLevel.VERBOSE if reason == "min_duration_hold" else LogLevel.DECISIONS,
        )


def _log_strategic_state(
    belief_state: BeliefState,
    state: StrategicState,
) -> None:
    snapshot = _strategic_log_snapshot(belief_state, state)
    tick = getattr(belief_state, "tick", 0)

    if logger and isinstance(tick, int) and tick % TICKS_PER_SECOND == 0:
        logger.event(
            "strategic_state_snapshot",
            snapshot,
            LogLevel.VERBOSE,
        )

    previous = belief_state.extra.get(
        _PREV_STRATEGIC_KEY,
        belief_state.inferences.get(_PREV_STRATEGIC_KEY),
    )
    if isinstance(previous, dict):
        changed = {
            key: value
            for key, value in snapshot.items()
            if key != "game_elapsed_ticks" and previous.get(key) != value
        }
        if changed and logger:
            logger.event(
                "strategic_state_change",
                changed,
                LogLevel.EVENTS,
            )

    belief_state.extra[_PREV_STRATEGIC_KEY] = snapshot


def _strategic_log_snapshot(
    belief_state: BeliefState,
    state: StrategicState,
) -> dict[str, object]:
    return {
        "my_role": _name(state.my_role),
        "my_team": _name(state.my_team),
        "my_room": _name(state.my_room),
        "key_partner_found": state.key_partner_found,
        "key_exchange_done": state.key_exchange_done,
        "partner_location": _name(state.key_partner_room),
        "enemy_key_location": _name(state.enemy_key_role_room),
        "urgency": _name(state.urgency),
        "current_objective": _name(state.current_objective),
        "spy_in_game_config": state.spy_in_game_config,
        "game_elapsed_ticks": _game_elapsed_ticks(belief_state, state),
        "round_number": state.current_round,
        "current_phase": _name(state.current_phase),
        "ticks_remaining_in_phase": state.ticks_remaining_in_phase,
        "round_schedule": [
            list(item) if isinstance(item, tuple) else item
            for item in state.round_schedule
        ],
    }


def _game_elapsed_ticks(
    belief_state: BeliefState,
    state: StrategicState,
) -> int:
    durations = _round_durations(state.round_schedule)
    tick = getattr(belief_state, "tick", 0)
    if state.current_round <= 0 or not durations:
        return tick if isinstance(tick, int) else 0

    round_index = min(max(state.current_round - 1, 0), len(durations) - 1)
    round_duration = max(durations[round_index], 1)
    remaining = max(0, min(state.ticks_remaining_in_phase, round_duration))
    return sum(durations[:round_index]) + round_duration - remaining


def _name(value: object) -> str | None:
    if value is None:
        return None
    name = getattr(value, "name", None)
    if isinstance(name, str):
        return name.lower()
    raw = getattr(value, "value", None)
    if isinstance(raw, str):
        return raw
    return str(value)


def _knowledge(belief_state: BeliefState) -> dict[PlayerID, PlayerKnowledge]:
    raw = belief_state.extra.get(PLAYER_KNOWLEDGE, {})
    if isinstance(raw, dict):
        return raw
    return {}


def _last_mode(belief_state: BeliefState) -> str | None:
    return belief_state.extra.get(
        LAST_DIRECTIVE_MODE, belief_state.inferences.get(LAST_DIRECTIVE_MODE)
    )


def _last_directive(belief_state: BeliefState) -> ModeDirective | None:
    raw = belief_state.extra.get(
        LAST_DIRECTIVE,
        belief_state.inferences.get(LAST_DIRECTIVE),
    )
    return raw if isinstance(raw, ModeDirective) else None


def _last_tick(belief_state: BeliefState) -> int:
    raw = belief_state.extra.get(
        LAST_DIRECTIVE_TICK, belief_state.inferences.get(LAST_DIRECTIVE_TICK, 0)
    )
    if isinstance(raw, int):
        return raw
    return 0


def _params_event_value(params: ModeParams) -> dict[str, object] | str:
    if type(params) is ModeParams:
        return {}
    if is_dataclass(params):
        return {key: _jsonish_value(value) for key, value in asdict(params).items()}
    return repr(params)


def _jsonish_value(value: object) -> object:
    if isinstance(value, dict):
        return {str(key): _jsonish_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonish_value(item) for item in value]
    name = getattr(value, "name", None)
    if isinstance(name, str):
        return name.lower()
    raw = getattr(value, "value", None)
    if isinstance(raw, (str, int, float, bool)):
        return raw
    return value


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
