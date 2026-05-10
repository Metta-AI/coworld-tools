"""Role evaluator contracts for Eurydice phase 6 behavior."""

from __future__ import annotations

from agents.eurydice.advanced_modes import (
    CoordinateCrossRoomParams,
    HostageSelectParams,
    HoldPositionParams,
    SeekLeadershipParams,
    TimeWasteParams,
)
from agents.eurydice.evaluators import (
    evaluate_cerberus,
    evaluate_hades,
    evaluate_persephone,
    evaluate_shade,
    evaluate_spy,
)
from agents.eurydice.modes import ProbeSystematicParams
from agents.eurydice.strategic_state import StrategicState
from agents.eurydice.types import Objective, PlayerID, ProbeIntent, Role, Team, Urgency
from orpheus.action_memory import ActionMemory
from orpheus.belief_state import BeliefState
from orpheus.perception._common import PLAYER_COLORS
from orpheus.perception.types import Room


def _pid(index: int) -> PlayerID:
    return (PLAYER_COLORS[index % 8], index % 12)


def test_hades_partner_other_room_seeks_leadership() -> None:
    partner = _pid(1)
    state = StrategicState(
        my_role=Role.HADES,
        my_team=Team.SHADES,
        my_room=Room.UNDERWORLD,
        current_round=1,
        key_partner_found=True,
        key_partner_id=partner,
        key_partner_room=Room.MORTAL_REALM,
        round_schedule=[(15, 1), (15, 1), (15, 1)],
    )

    directive = evaluate_hades(state, BeliefState(), ActionMemory())

    assert directive.mode == "seek_leadership"
    assert isinstance(directive.params, SeekLeadershipParams)
    assert directive.params.reason == "reach_key_partner"
    assert state.current_objective is Objective.COMPLETE_KEY_EXCHANGE


def test_cerberus_partner_other_room_coordinates_cross_room() -> None:
    partner = _pid(1)
    state = StrategicState(
        my_role=Role.CERBERUS,
        my_team=Team.SHADES,
        my_room=Room.UNDERWORLD,
        current_round=1,
        key_partner_found=True,
        key_partner_id=partner,
        key_partner_room=Room.MORTAL_REALM,
        round_schedule=[(15, 1), (15, 1), (15, 1)],
    )

    directive = evaluate_cerberus(state, BeliefState(), ActionMemory())

    assert directive.mode == "coordinate_cross_room"
    assert directive.params == CoordinateCrossRoomParams(target=partner)
    assert state.current_objective is Objective.COMPLETE_KEY_EXCHANGE


def test_persephone_enemy_local_and_exchange_likely_coordinates_escape() -> None:
    enemy = _pid(2)
    state = StrategicState(
        my_role=Role.PERSEPHONE,
        my_team=Team.NYMPHS,
        my_room=Room.UNDERWORLD,
        key_exchange_done=True,
        enemy_key_role_id=enemy,
        enemy_key_role_room=Room.UNDERWORLD,
        enemy_key_exchange_likely=True,
    )

    directive = evaluate_persephone(state, BeliefState(), ActionMemory())

    assert directive.mode == "coordinate_cross_room"
    assert directive.params == CoordinateCrossRoomParams(target=enemy)
    assert state.current_objective is Objective.POSITION_FOR_WIN


def test_persephone_partner_other_room_holds_defensively() -> None:
    partner = _pid(3)
    state = StrategicState(
        my_role=Role.PERSEPHONE,
        my_team=Team.NYMPHS,
        my_room=Room.UNDERWORLD,
        key_partner_found=True,
        key_partner_id=partner,
        key_partner_room=Room.MORTAL_REALM,
    )

    directive = evaluate_persephone(state, BeliefState(), ActionMemory())

    assert directive.mode == "hold_position"
    assert directive.params == HoldPositionParams(
        seek_leadership=True,
        defensive=True,
        reason="partner_other_room",
    )
    assert state.current_objective is Objective.COMPLETE_KEY_EXCHANGE


def test_shade_leader_with_key_roles_need_help_selects_hostage_strategy() -> None:
    ally = _pid(1)
    enemy = _pid(2)
    state = StrategicState(
        my_role=Role.SHADE,
        my_team=Team.SHADES,
        my_room=Room.UNDERWORLD,
        am_leader=True,
        key_exchange_done=False,
        urgency=Urgency.PANIC,
        allies_in_my_room=[ally],
        enemies_in_my_room=[enemy],
    )

    directive = evaluate_shade(state, BeliefState(), ActionMemory())

    assert directive.mode == "hostage_select"
    assert directive.params == HostageSelectParams(
        objective=Objective.PROTECT_KEY_ROLE,
        protect=(ally,),
        move=(enemy,),
    )
    assert state.current_objective is Objective.PROTECT_KEY_ROLE


def test_spy_no_verified_ally_verifies_with_real_team_candidate() -> None:
    state = StrategicState(
        my_role=Role.SPY,
        my_team=Team.SHADES,
        my_room=Room.UNDERWORLD,
        verified_ally=None,
    )

    directive = evaluate_spy(state, BeliefState(), ActionMemory())

    assert directive.mode == "probe_systematic"
    assert directive.params == ProbeSystematicParams(
        target_team=Team.SHADES,
        intent=ProbeIntent.VERIFY_SELF_AS_SPY,
        cautious=True,
    )
    assert state.current_objective is Objective.MAINTAIN_COVER


def test_final_partner_unreachable_fires_only_final_round() -> None:
    partner = _pid(4)
    early = StrategicState(
        my_role=Role.HADES,
        my_team=Team.SHADES,
        my_room=Room.UNDERWORLD,
        current_round=2,
        round_schedule=[(15, 1), (15, 1), (15, 1)],
        key_partner_found=True,
        key_partner_id=partner,
        key_partner_room=Room.MORTAL_REALM,
    )
    final = StrategicState(
        my_role=Role.HADES,
        my_team=Team.SHADES,
        my_room=Room.UNDERWORLD,
        current_round=3,
        round_schedule=[(15, 1), (15, 1), (15, 1)],
        key_partner_found=True,
        key_partner_id=partner,
        key_partner_room=Room.MORTAL_REALM,
    )

    early_directive = evaluate_hades(early, BeliefState(), ActionMemory())
    final_directive = evaluate_hades(final, BeliefState(), ActionMemory())

    assert early_directive.mode == "seek_leadership"
    assert final_directive.mode == "time_waste"
    assert isinstance(final_directive.params, TimeWasteParams)
    assert final_directive.params.reason == "final_partner_unreachable"
    assert final.current_objective is Objective.DISRUPT_ENEMY
