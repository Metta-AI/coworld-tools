"""Role evaluators for Eurydice strategic mode selection."""

from __future__ import annotations

from collections.abc import Callable

from orpheus.action_memory import ActionMemory
from orpheus.belief_state import BeliefState
from orpheus.mode import ModeDirective, ModeParams

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
        return _directive("time_waste")
    if not state.key_exchange_done:
        if _partner_in_room(state):
            return _directive("probe_target")
        if _partner_in_other_room(state):
            return _directive("seek_leadership")
        if not state.key_partner_found:
            return _directive("probe_systematic")
    else:
        if _enemy_key_unknown(state):
            return _directive("probe_systematic")
        if _enemy_key_in_room(state):
            return _directive("hold_position")
        if _enemy_key_in_other_room(state):
            return _directive("coordinate_cross_room")
    return _directive("scout")


def evaluate_cerberus(
    state: StrategicState,
    belief_state: BeliefState,
    action_memory: ActionMemory,
) -> ModeDirective:
    if _final_partner_unreachable(state):
        return _directive("time_waste")
    if not state.key_exchange_done:
        if _partner_in_room(state):
            return _directive("probe_target")
        if _partner_in_other_room(state):
            return _directive("coordinate_cross_room")
        if not state.key_partner_found:
            return _directive("probe_systematic")
    else:
        if _enemy_key_unknown(state):
            return _directive("probe_systematic")
        return _directive("hold_position")
    return _directive("scout")


def evaluate_persephone(
    state: StrategicState,
    belief_state: BeliefState,
    action_memory: ActionMemory,
) -> ModeDirective:
    if _final_partner_unreachable(state):
        return _directive("time_waste")
    if not state.key_exchange_done:
        if _partner_in_room(state):
            return _directive("probe_target")
        if _partner_in_other_room(state):
            return _directive("hold_position")
        if not state.key_partner_found:
            return _directive("probe_systematic")
    else:
        if _enemy_key_in_room(state) and state.enemy_key_exchange_likely:
            return _directive("coordinate_cross_room")
        if _enemy_key_in_room(state):
            return _directive("hold_position")
        if _enemy_key_unknown(state):
            return _directive("hold_position")
        if _enemy_key_in_other_room(state):
            return _directive("hold_position")
    return _directive("scout")


def evaluate_demeter(
    state: StrategicState,
    belief_state: BeliefState,
    action_memory: ActionMemory,
) -> ModeDirective:
    if _final_partner_unreachable(state):
        return _directive("time_waste")
    if not state.key_exchange_done:
        if _partner_in_room(state):
            return _directive("probe_target")
        if _partner_in_other_room(state):
            return _directive("coordinate_cross_room")
        if not state.key_partner_found:
            return _directive("probe_systematic")
    else:
        if _enemy_key_unknown(state):
            return _directive("probe_systematic")
        return _directive("hold_position")
    return _directive("scout")


def evaluate_shade(
    state: StrategicState,
    belief_state: BeliefState,
    action_memory: ActionMemory,
) -> ModeDirective:
    if _room_composition_unknown(state):
        return _directive("probe_systematic")
    if state.am_leader and _key_roles_need_help(state):
        return _directive("hold_position")
    if _hostile_leader(state):
        return _directive("seek_leadership")
    return _directive("probe_systematic")


def evaluate_nymph(
    state: StrategicState,
    belief_state: BeliefState,
    action_memory: ActionMemory,
) -> ModeDirective:
    if _room_composition_unknown(state):
        return _directive("probe_systematic")
    if _hostile_leader_threatens_persephone(state):
        return _directive("seek_leadership")
    return _directive("probe_systematic")


def evaluate_spy(
    state: StrategicState,
    belief_state: BeliefState,
    action_memory: ActionMemory,
) -> ModeDirective:
    if state.verified_ally is None:
        return _directive("probe_systematic")
    if state.cover_intact:
        return _directive("probe_systematic")
    if state.my_team is Team.SHADES:
        return evaluate_shade(state, belief_state, action_memory)
    if state.my_team is Team.NYMPHS:
        return evaluate_nymph(state, belief_state, action_memory)
    return _directive("scout")


def _directive(mode: str) -> ModeDirective:
    return ModeDirective(mode, ModeParams())


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
