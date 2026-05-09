"""Role evaluators for Eurydice strategic mode selection."""

from __future__ import annotations

from collections.abc import Callable

from orpheus.action_memory import ActionMemory
from orpheus.belief_state import BeliefState
from orpheus.logging import LogLevel
from orpheus.mode import ModeDirective, ModeParams

from .log import logger
from .strategic_state import StrategicState
from .types import PlayerID, Role, Team, Urgency

Evaluator = Callable[[StrategicState, BeliefState, ActionMemory], ModeDirective]

_KEY_ROLES = {
    Role.HADES,
    Role.CERBERUS,
    Role.PERSEPHONE,
    Role.DEMETER,
}


def evaluate_hades(
    state: StrategicState,
    belief_state: BeliefState,
    action_memory: ActionMemory,
) -> ModeDirective:
    if _final_partner_unreachable(state):
        return _branch("hades", "final_partner_unreachable->time_waste", "time_waste")
    if not state.key_exchange_done:
        if _partner_in_room(state):
            return _branch("hades", "partner_in_room->probe_target", "probe_target")
        if _partner_in_other_room(state):
            return _branch("hades", "partner_in_other_room->seek_leadership", "seek_leadership")
        if not state.key_partner_found:
            return _branch("hades", "partner_unknown->probe_systematic", "probe_systematic")
    else:
        if _enemy_key_unknown(state):
            return _branch("hades", "exchange_done+enemy_unknown->probe_systematic", "probe_systematic")
        if _enemy_key_in_room(state):
            return _branch("hades", "exchange_done+enemy_in_room->hold_position", "hold_position")
        if _enemy_key_in_other_room(state):
            return _branch("hades", "exchange_done+enemy_in_other_room->coordinate_cross_room", "coordinate_cross_room")
    return _branch("hades", "fallback->scout", "scout")


def evaluate_cerberus(
    state: StrategicState,
    belief_state: BeliefState,
    action_memory: ActionMemory,
) -> ModeDirective:
    if _final_partner_unreachable(state):
        return _branch("cerberus", "final_partner_unreachable->time_waste", "time_waste")
    if not state.key_exchange_done:
        if _partner_in_room(state):
            return _branch("cerberus", "partner_in_room->probe_target", "probe_target")
        if _partner_in_other_room(state):
            return _branch("cerberus", "partner_in_other_room->coordinate_cross_room", "coordinate_cross_room")
        if not state.key_partner_found:
            return _branch("cerberus", "partner_unknown->probe_systematic", "probe_systematic")
    else:
        if _enemy_key_unknown(state):
            return _branch("cerberus", "exchange_done+enemy_unknown->probe_systematic", "probe_systematic")
        return _branch("cerberus", "exchange_done->hold_position", "hold_position")
    return _branch("cerberus", "fallback->scout", "scout")


def evaluate_persephone(
    state: StrategicState,
    belief_state: BeliefState,
    action_memory: ActionMemory,
) -> ModeDirective:
    if _final_partner_unreachable(state):
        return _branch("persephone", "final_partner_unreachable->time_waste", "time_waste")
    if not state.key_exchange_done:
        if _partner_in_room(state):
            return _branch("persephone", "partner_in_room->probe_target", "probe_target")
        if _partner_in_other_room(state):
            return _branch("persephone", "partner_in_other_room->hold_position", "hold_position")
        if not state.key_partner_found:
            return _branch("persephone", "partner_unknown->probe_systematic", "probe_systematic")
    else:
        if _enemy_key_in_room(state) and state.enemy_key_exchange_likely:
            return _branch("persephone", "exchange_done+enemy_in_room+enemy_exchange_likely->coordinate_cross_room", "coordinate_cross_room")
        if _enemy_key_in_room(state):
            return _branch("persephone", "exchange_done+enemy_in_room->hold_position", "hold_position")
        if _enemy_key_unknown(state):
            return _branch("persephone", "exchange_done+enemy_unknown->hold_position", "hold_position")
        if _enemy_key_in_other_room(state):
            return _branch("persephone", "exchange_done+enemy_in_other_room->hold_position", "hold_position")
    return _branch("persephone", "fallback->scout", "scout")


def evaluate_demeter(
    state: StrategicState,
    belief_state: BeliefState,
    action_memory: ActionMemory,
) -> ModeDirective:
    if _final_partner_unreachable(state):
        return _branch("demeter", "final_partner_unreachable->time_waste", "time_waste")
    if not state.key_exchange_done:
        if _partner_in_room(state):
            return _branch("demeter", "partner_in_room->probe_target", "probe_target")
        if _partner_in_other_room(state):
            return _branch("demeter", "partner_in_other_room->coordinate_cross_room", "coordinate_cross_room")
        if not state.key_partner_found:
            return _branch("demeter", "partner_unknown->probe_systematic", "probe_systematic")
    else:
        if _enemy_key_unknown(state):
            return _branch("demeter", "exchange_done+enemy_unknown->probe_systematic", "probe_systematic")
        return _branch("demeter", "exchange_done->hold_position", "hold_position")
    return _branch("demeter", "fallback->scout", "scout")


def evaluate_shade(
    state: StrategicState,
    belief_state: BeliefState,
    action_memory: ActionMemory,
) -> ModeDirective:
    if _room_composition_unknown(state):
        return _branch("shade", "room_composition_unknown->probe_systematic", "probe_systematic")
    if state.am_leader and _key_roles_need_help(state):
        return _branch("shade", "leader+key_roles_need_help->hold_position", "hold_position")
    if _hostile_leader(state):
        return _branch("shade", "hostile_leader->seek_leadership", "seek_leadership")
    return _branch("shade", "default_support_probe->probe_systematic", "probe_systematic")


def evaluate_nymph(
    state: StrategicState,
    belief_state: BeliefState,
    action_memory: ActionMemory,
) -> ModeDirective:
    if _room_composition_unknown(state):
        return _branch("nymph", "room_composition_unknown->probe_systematic", "probe_systematic")
    if _hostile_leader_threatens_persephone(state):
        return _branch("nymph", "hostile_leader_threatens_persephone->seek_leadership", "seek_leadership")
    return _branch("nymph", "default_support_probe->probe_systematic", "probe_systematic")


def evaluate_spy(
    state: StrategicState,
    belief_state: BeliefState,
    action_memory: ActionMemory,
) -> ModeDirective:
    if state.verified_ally is None:
        return _branch("spy", "no_verified_ally->probe_systematic", "probe_systematic")
    if state.cover_intact:
        return _branch("spy", "cover_intact->probe_systematic", "probe_systematic")
    if state.my_team is Team.SHADES:
        directive = evaluate_shade(state, belief_state, action_memory)
        _log_branch("spy", "cover_blown+shades_delegate", directive.mode)
        return directive
    if state.my_team is Team.NYMPHS:
        directive = evaluate_nymph(state, belief_state, action_memory)
        _log_branch("spy", "cover_blown+nymphs_delegate", directive.mode)
        return directive
    return _branch("spy", "unknown_team->scout", "scout")


def _directive(mode: str) -> ModeDirective:
    return ModeDirective(mode, ModeParams())


def _branch(role: str, branch: str, mode: str) -> ModeDirective:
    _log_branch(role, branch, mode)
    return _directive(mode)


def _log_branch(role: str, branch: str, mode: str) -> None:
    if logger:
        logger.event(
            "evaluator_branch",
            {"role": role, "branch": branch, "mode": mode},
            LogLevel.VERBOSE,
        )


def _partner_unreachable(state: StrategicState) -> bool:
    return (
        state.current_round == len(state.round_schedule)
        and _partner_in_other_room(state)
    )


def _room_composition_unknown(state: StrategicState) -> bool:
    return not state.allies_in_my_room and not state.enemies_in_my_room


def _final_partner_unreachable(state: StrategicState) -> bool:
    return (
        state.my_role in _KEY_ROLES
        and not state.key_exchange_done
        and _partner_unreachable(state)
    )


def _partner_in_room(state: StrategicState) -> bool:
    return (
        state.key_partner_found
        and state.key_partner_room is not None
        and state.my_room is not None
        and state.key_partner_room == state.my_room
    )


def _partner_in_other_room(state: StrategicState) -> bool:
    return (
        state.key_partner_found
        and state.key_partner_room is not None
        and state.my_room is not None
        and state.key_partner_room != state.my_room
    )


def _enemy_key_unknown(state: StrategicState) -> bool:
    return state.enemy_key_role_id is None or state.enemy_key_role_room is None


def _enemy_key_in_room(state: StrategicState) -> bool:
    return (
        state.enemy_key_role_room is not None
        and state.my_room is not None
        and state.enemy_key_role_room == state.my_room
    )


def _enemy_key_in_other_room(state: StrategicState) -> bool:
    return (
        state.enemy_key_role_room is not None
        and state.my_room is not None
        and state.enemy_key_role_room != state.my_room
    )


def _key_roles_need_help(state: StrategicState) -> bool:
    return (
        not state.key_exchange_done
        and (
            state.urgency in {Urgency.PRESSING, Urgency.PANIC}
            or state.enemy_key_exchange_likely
        )
    )


def _hostile_leader(state: StrategicState) -> bool:
    return (
        not state.am_leader
        and state.my_team is not None
        and state.room_leader_team is not None
        and state.room_leader_team != state.my_team
    )


def _hostile_leader_threatens_persephone(state: StrategicState) -> bool:
    return _hostile_leader(state)


ROLE_EVALUATORS: dict[str, Evaluator] = {
    "hades": evaluate_hades,
    "cerberus": evaluate_cerberus,
    "shade": evaluate_shade,
    "persephone": evaluate_persephone,
    "demeter": evaluate_demeter,
    "nymph": evaluate_nymph,
    "spy": evaluate_spy,
}


__all__ = [
    "Evaluator",
    "ROLE_EVALUATORS",
    "evaluate_hades",
    "evaluate_cerberus",
    "evaluate_shade",
    "evaluate_persephone",
    "evaluate_demeter",
    "evaluate_nymph",
    "evaluate_spy",
]
