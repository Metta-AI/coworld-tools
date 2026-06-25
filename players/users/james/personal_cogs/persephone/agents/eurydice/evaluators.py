"""Role evaluators for Eurydice strategic mode selection."""

from __future__ import annotations

from collections.abc import Callable

from orpheus.action_memory import ActionMemory
from orpheus.belief_state import BeliefState
from orpheus.logging import LogLevel
from orpheus.mode import ModeDirective, ModeParams

from .advanced_modes import (
    CoordinateCrossRoomParams,
    HoldPositionParams,
    HostageSelectParams,
    SeekLeadershipParams,
    TimeWasteParams,
)
from .log import logger
from .modes import (
    KEY_OPENER_ROLES,
    KEY_REQUESTER_ROLES,
    ProbeSystematicParams,
    ProbeTargetParams,
)
from .strategic_state import StrategicState
from .types import Objective, PlayerID, ProbeIntent, Role, Team, Urgency

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
        return _branch(
            state,
            "hades",
            "final_partner_unreachable->time_waste",
            "time_waste",
            TimeWasteParams(reason="final_partner_unreachable"),
            Objective.DISRUPT_ENEMY,
        )
    if not state.key_exchange_done:
        if _partner_in_room(state):
            return _branch(
                state,
                "hades",
                "partner_in_room->probe_target",
                "probe_target",
                _partner_probe_params(state),
                Objective.COMPLETE_KEY_EXCHANGE,
            )
        if _partner_in_other_room(state):
            return _branch(
                state,
                "hades",
                "partner_in_other_room->seek_leadership",
                "seek_leadership",
                SeekLeadershipParams(reason="reach_key_partner"),
                Objective.COMPLETE_KEY_EXCHANGE,
            )
        if _partner_room_unknown(state):
            return _branch(
                state,
                "hades",
                "partner_room_unknown->probe_target",
                "probe_target",
                _partner_probe_params(state),
                Objective.COMPLETE_KEY_EXCHANGE,
            )
        if not state.key_partner_found:
            return _branch(
                state,
                "hades",
                "partner_unknown->probe_systematic",
                "probe_systematic",
                _partner_search_params(state),
                Objective.FIND_KEY_PARTNER,
            )
    else:
        if _enemy_key_unknown(state):
            return _branch(
                state,
                "hades",
                "exchange_done+enemy_unknown->probe_systematic",
                "probe_systematic",
                _enemy_key_search_params(state),
                Objective.LOCATE_ENEMY_KEY,
            )
        if _enemy_key_in_room(state):
            return _branch(
                state,
                "hades",
                "exchange_done+enemy_in_room->hold_position",
                "hold_position",
                HoldPositionParams(reason="enemy_key_local"),
                Objective.POSITION_FOR_WIN,
            )
        if _enemy_key_in_other_room(state):
            return _branch(
                state,
                "hades",
                "exchange_done+enemy_in_other_room->coordinate_cross_room",
                "coordinate_cross_room",
                CoordinateCrossRoomParams(target=state.enemy_key_role_id),
                Objective.POSITION_FOR_WIN,
            )
    return _branch(state, "hades", "fallback->scout", "scout")


def evaluate_cerberus(
    state: StrategicState,
    belief_state: BeliefState,
    action_memory: ActionMemory,
) -> ModeDirective:
    if _final_partner_unreachable(state):
        return _branch(
            state,
            "cerberus",
            "final_partner_unreachable->time_waste",
            "time_waste",
            TimeWasteParams(reason="final_partner_unreachable"),
            Objective.DISRUPT_ENEMY,
        )
    if not state.key_exchange_done:
        if _partner_in_room(state):
            return _branch(
                state,
                "cerberus",
                "partner_in_room->probe_target",
                "probe_target",
                _partner_probe_params(state),
                Objective.COMPLETE_KEY_EXCHANGE,
            )
        if _partner_in_other_room(state):
            return _branch(
                state,
                "cerberus",
                "partner_in_other_room->coordinate_cross_room",
                "coordinate_cross_room",
                CoordinateCrossRoomParams(target=state.key_partner_id),
                Objective.COMPLETE_KEY_EXCHANGE,
            )
        if _partner_room_unknown(state):
            return _branch(
                state,
                "cerberus",
                "partner_room_unknown->probe_target",
                "probe_target",
                _partner_probe_params(state),
                Objective.COMPLETE_KEY_EXCHANGE,
            )
        if not state.key_partner_found:
            return _branch(
                state,
                "cerberus",
                "partner_unknown->probe_systematic",
                "probe_systematic",
                _partner_search_params(state),
                Objective.FIND_KEY_PARTNER,
            )
    else:
        if _enemy_key_unknown(state):
            return _branch(
                state,
                "cerberus",
                "exchange_done+enemy_unknown->probe_systematic",
                "probe_systematic",
                _enemy_key_search_params(state),
                Objective.LOCATE_ENEMY_KEY,
            )
        return _branch(
            state,
            "cerberus",
            "exchange_done->hold_position",
            "hold_position",
            HoldPositionParams(reason="exchange_done"),
            Objective.POSITION_FOR_WIN,
        )
    return _branch(state, "cerberus", "fallback->scout", "scout")


def evaluate_persephone(
    state: StrategicState,
    belief_state: BeliefState,
    action_memory: ActionMemory,
) -> ModeDirective:
    if _final_partner_unreachable(state):
        return _branch(
            state,
            "persephone",
            "final_partner_unreachable->time_waste",
            "time_waste",
            TimeWasteParams(reason="final_partner_unreachable"),
            Objective.DISRUPT_ENEMY,
        )
    if not state.key_exchange_done:
        if _partner_in_room(state):
            return _branch(
                state,
                "persephone",
                "partner_in_room->probe_target",
                "probe_target",
                _partner_probe_params(state),
                Objective.COMPLETE_KEY_EXCHANGE,
            )
        if _partner_in_other_room(state):
            return _branch(
                state,
                "persephone",
                "partner_in_other_room->hold_position",
                "hold_position",
                HoldPositionParams(seek_leadership=True, defensive=True, reason="partner_other_room"),
                Objective.COMPLETE_KEY_EXCHANGE,
            )
        if _partner_room_unknown(state):
            return _branch(
                state,
                "persephone",
                "partner_room_unknown->probe_target",
                "probe_target",
                _partner_probe_params(state),
                Objective.COMPLETE_KEY_EXCHANGE,
            )
        if not state.key_partner_found:
            return _branch(
                state,
                "persephone",
                "partner_unknown->probe_systematic",
                "probe_systematic",
                _partner_search_params(state, cautious=True),
                Objective.FIND_KEY_PARTNER,
            )
    else:
        if _enemy_key_in_room(state) and state.enemy_key_exchange_likely:
            return _branch(
                state,
                "persephone",
                "exchange_done+enemy_in_room+enemy_exchange_likely->coordinate_cross_room",
                "coordinate_cross_room",
                CoordinateCrossRoomParams(target=state.enemy_key_role_id),
                Objective.POSITION_FOR_WIN,
            )
        if _enemy_key_in_room(state):
            return _branch(
                state,
                "persephone",
                "exchange_done+enemy_in_room->hold_position",
                "hold_position",
                HoldPositionParams(seek_leadership=True, defensive=True, reason="enemy_key_local"),
                Objective.POSITION_FOR_WIN,
            )
        if _enemy_key_unknown(state):
            return _branch(
                state,
                "persephone",
                "exchange_done+enemy_unknown->hold_position",
                "hold_position",
                HoldPositionParams(seek_leadership=True, defensive=True, reason="enemy_key_unknown"),
                Objective.POSITION_FOR_WIN,
            )
        if _enemy_key_in_other_room(state):
            return _branch(
                state,
                "persephone",
                "exchange_done+enemy_in_other_room->hold_position",
                "hold_position",
                HoldPositionParams(seek_leadership=True, defensive=True, reason="safe_from_enemy_key"),
                Objective.POSITION_FOR_WIN,
            )
    return _branch(state, "persephone", "fallback->scout", "scout")


def evaluate_demeter(
    state: StrategicState,
    belief_state: BeliefState,
    action_memory: ActionMemory,
) -> ModeDirective:
    if _final_partner_unreachable(state):
        return _branch(
            state,
            "demeter",
            "final_partner_unreachable->time_waste",
            "time_waste",
            TimeWasteParams(reason="final_partner_unreachable"),
            Objective.DISRUPT_ENEMY,
        )
    if not state.key_exchange_done:
        if _partner_in_room(state):
            return _branch(
                state,
                "demeter",
                "partner_in_room->probe_target",
                "probe_target",
                _partner_probe_params(state),
                Objective.COMPLETE_KEY_EXCHANGE,
            )
        if _partner_in_other_room(state):
            return _branch(
                state,
                "demeter",
                "partner_in_other_room->coordinate_cross_room",
                "coordinate_cross_room",
                CoordinateCrossRoomParams(target=state.key_partner_id),
                Objective.COMPLETE_KEY_EXCHANGE,
            )
        if _partner_room_unknown(state):
            return _branch(
                state,
                "demeter",
                "partner_room_unknown->probe_target",
                "probe_target",
                _partner_probe_params(state),
                Objective.COMPLETE_KEY_EXCHANGE,
            )
        if not state.key_partner_found:
            return _branch(
                state,
                "demeter",
                "partner_unknown->probe_systematic",
                "probe_systematic",
                _partner_search_params(state, aggressive=True),
                Objective.FIND_KEY_PARTNER,
            )
    else:
        if _enemy_key_unknown(state):
            return _branch(
                state,
                "demeter",
                "exchange_done+enemy_unknown->probe_systematic",
                "probe_systematic",
                _enemy_key_search_params(state),
                Objective.LOCATE_ENEMY_KEY,
            )
        return _branch(
            state,
            "demeter",
            "exchange_done->hold_position",
            "hold_position",
            HoldPositionParams(reason="exchange_done"),
            Objective.POSITION_FOR_WIN,
        )
    return _branch(state, "demeter", "fallback->scout", "scout")


def evaluate_shade(
    state: StrategicState,
    belief_state: BeliefState,
    action_memory: ActionMemory,
) -> ModeDirective:
    if _room_composition_unknown(state):
        return _branch(
            state,
            "shade",
            "room_composition_unknown->probe_systematic",
            "probe_systematic",
            ProbeSystematicParams(target_team=state.my_team, intent=ProbeIntent.MAP_ROOM),
            Objective.GATHER_INTEL,
        )
    if state.am_leader and _key_roles_need_help(state):
        return _branch(
            state,
            "shade",
            "leader+key_roles_need_help->hostage_select",
            "hostage_select",
            HostageSelectParams(
                objective=Objective.PROTECT_KEY_ROLE,
                protect=tuple(state.allies_in_my_room),
                move=tuple(state.enemies_in_my_room),
            ),
            Objective.PROTECT_KEY_ROLE,
        )
    if _hostile_leader(state):
        return _branch(
            state,
            "shade",
            "hostile_leader->seek_leadership",
            "seek_leadership",
            SeekLeadershipParams(reason="hostile_leader"),
            Objective.PROTECT_KEY_ROLE,
        )
    return _branch(
        state,
        "shade",
        "default_support_probe->probe_systematic",
        "probe_systematic",
        ProbeSystematicParams(target_team=state.my_team, intent=ProbeIntent.MAP_ROOM),
        Objective.GATHER_INTEL,
    )


def evaluate_nymph(
    state: StrategicState,
    belief_state: BeliefState,
    action_memory: ActionMemory,
) -> ModeDirective:
    if _room_composition_unknown(state):
        return _branch(
            state,
            "nymph",
            "room_composition_unknown->probe_systematic",
            "probe_systematic",
            ProbeSystematicParams(target_team=state.my_team, intent=ProbeIntent.MAP_ROOM),
            Objective.GATHER_INTEL,
        )
    if _hostile_leader_threatens_persephone(state):
        return _branch(
            state,
            "nymph",
            "hostile_leader_threatens_persephone->seek_leadership",
            "seek_leadership",
            SeekLeadershipParams(reason="hostile_leader_threatens_persephone"),
            Objective.PROTECT_KEY_ROLE,
        )
    return _branch(
        state,
        "nymph",
        "default_support_probe->probe_systematic",
        "probe_systematic",
        ProbeSystematicParams(target_team=state.my_team, intent=ProbeIntent.MAP_ROOM),
        Objective.GATHER_INTEL,
    )


def evaluate_spy(
    state: StrategicState,
    belief_state: BeliefState,
    action_memory: ActionMemory,
) -> ModeDirective:
    if state.verified_ally is None:
        return _branch(
            state,
            "spy",
            "no_verified_ally->probe_systematic",
            "probe_systematic",
            ProbeSystematicParams(
                target_team=state.my_team,
                intent=ProbeIntent.VERIFY_SELF_AS_SPY,
                cautious=True,
            ),
            Objective.MAINTAIN_COVER,
        )
    if state.cover_intact:
        return _branch(
            state,
            "spy",
            "cover_intact->probe_systematic",
            "probe_systematic",
            ProbeSystematicParams(intent=ProbeIntent.DISRUPT, cautious=True),
            Objective.MAINTAIN_COVER,
        )
    if state.my_team is Team.SHADES:
        directive = evaluate_shade(state, belief_state, action_memory)
        _log_branch("spy", "cover_blown+shades_delegate", directive.mode)
        return directive
    if state.my_team is Team.NYMPHS:
        directive = evaluate_nymph(state, belief_state, action_memory)
        _log_branch("spy", "cover_blown+nymphs_delegate", directive.mode)
        return directive
    return _branch(state, "spy", "unknown_team->scout", "scout")


def _directive(mode: str, params: ModeParams | None = None) -> ModeDirective:
    return ModeDirective(mode, params or ModeParams())


def _branch(
    state: StrategicState,
    role: str,
    branch: str,
    mode: str,
    params: ModeParams | None = None,
    objective: Objective | None = None,
) -> ModeDirective:
    if objective is not None:
        state.current_objective = objective
    _log_branch(role, branch, mode)
    return _directive(mode, params)


def _log_branch(role: str, branch: str, mode: str) -> None:
    if logger:
        logger.event(
            "evaluator_branch",
            {"role": role, "branch": branch, "mode": mode},
            LogLevel.VERBOSE,
        )


def _partner_unreachable(state: StrategicState) -> bool:
    return (
        bool(state.round_schedule)
        and state.current_round > 0
        and state.current_round == len(state.round_schedule)
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


def _partner_room_unknown(state: StrategicState) -> bool:
    return (
        state.key_partner_found
        and state.key_partner_id is not None
        and state.key_partner_room is None
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


def _partner_probe_params(state: StrategicState) -> ProbeTargetParams:
    return ProbeTargetParams(
        target=state.key_partner_id or (0, 0),
        intent=ProbeIntent.FIND_KEY_PARTNER,
        skip_color_exchange=True,
        max_approach_ticks=240,
        request_only=state.my_role in KEY_REQUESTER_ROLES,
        open_in_place=state.my_role in KEY_OPENER_ROLES,
    )


def _partner_search_params(
    state: StrategicState,
    *,
    cautious: bool = False,
    aggressive: bool = False,
) -> ProbeSystematicParams:
    return ProbeSystematicParams(
        target_team=state.my_team,
        intent=ProbeIntent.FIND_KEY_PARTNER,
        cautious=cautious,
        aggressive=aggressive,
    )


def _enemy_key_search_params(state: StrategicState) -> ProbeSystematicParams:
    return ProbeSystematicParams(
        target_team=_enemy_team(state.my_team),
        intent=ProbeIntent.LOCATE_ENEMY_KEY,
        cautious=state.urgency is Urgency.PANIC,
    )


def _enemy_team(team: Team | None) -> Team | None:
    if team is Team.SHADES:
        return Team.NYMPHS
    if team is Team.NYMPHS:
        return Team.SHADES
    return None


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
