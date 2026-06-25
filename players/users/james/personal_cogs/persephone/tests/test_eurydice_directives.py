"""Phase 3 directive-parameter contracts for Eurydice."""

from __future__ import annotations

from agents.eurydice.evaluators import (
    evaluate_cerberus,
    evaluate_demeter,
    evaluate_hades,
    evaluate_persephone,
)
from agents.eurydice.ext_keys import (
    EURYDICE_ACCUMULATORS,
    LAST_DIRECTIVE,
    LAST_DIRECTIVE_MODE,
    LAST_DIRECTIVE_TICK,
    PLAYER_KNOWLEDGE,
    STRATEGIC_STATE,
)
from agents.eurydice.knowledge import PlayerKnowledge
from agents.eurydice.meta_decide import meta_decide
from agents.eurydice.modes import ProbeSystematicParams, ProbeTargetParams
from agents.eurydice.pipeline import initialize_eurydice_state, player_index_to_id
from agents.eurydice.policy import build_registry
from agents.eurydice.strategic_state import StrategicState
from agents.eurydice.types import Objective, ProbeIntent, Role, RoleSource, Team, TeamSource
from orpheus.action_memory import ActionMemory
from orpheus.belief_state import BeliefState, PlayerInfo
from orpheus.mode import ModeDirective
from orpheus.perception._common import PLAYER_COLORS
from orpheus.perception.types import Room, View


def _belief_state(**overrides) -> BeliefState:
    values = {
        "tick": 24,
        "view": View.PLAYING,
        "position": (50, 50),
        "room": Room.UNDERWORLD,
        "my_index": 0,
        "my_color": PLAYER_COLORS[0],
        "my_shape": 0,
        "my_role": "hades",
        "my_team": "shades",
        "my_room": Room.UNDERWORLD,
        "round": 1,
        "timer_secs": 180,
        "player_count": 8,
        "round_schedule": [(180, 1), (120, 1), (60, 1)],
    }
    values.update(overrides)
    belief_state = BeliefState(**values)
    initialize_eurydice_state(belief_state)
    return belief_state


def _pid(index: int, belief_state: BeliefState):
    player_id = player_index_to_id(index, belief_state)
    assert player_id is not None
    return player_id


def test_hades_partner_local_requests_entry_for_key_exchange() -> None:
    partner_id = (PLAYER_COLORS[1], 1)
    state = StrategicState(
        my_role=Role.HADES,
        my_team=Team.SHADES,
        my_room=Room.UNDERWORLD,
        key_partner_found=True,
        key_partner_id=partner_id,
        key_partner_room=Room.UNDERWORLD,
    )

    directive = evaluate_hades(state, BeliefState(), ActionMemory())

    assert directive.mode == "probe_target"
    assert directive.params == ProbeTargetParams(
        target=partner_id,
        intent=ProbeIntent.FIND_KEY_PARTNER,
        skip_color_exchange=True,
        max_approach_ticks=240,
        request_only=True,
        open_in_place=False,
    )
    assert state.current_objective is Objective.COMPLETE_KEY_EXCHANGE


def test_cerberus_partner_local_opens_whisper_for_key_exchange() -> None:
    partner_id = (PLAYER_COLORS[3], 3)
    state = StrategicState(
        my_role=Role.CERBERUS,
        my_team=Team.SHADES,
        my_room=Room.UNDERWORLD,
        key_partner_found=True,
        key_partner_id=partner_id,
        key_partner_room=Room.UNDERWORLD,
    )

    directive = evaluate_cerberus(state, BeliefState(), ActionMemory())

    assert directive.mode == "probe_target"
    assert directive.params == ProbeTargetParams(
        target=partner_id,
        intent=ProbeIntent.FIND_KEY_PARTNER,
        skip_color_exchange=True,
        max_approach_ticks=240,
        request_only=False,
        open_in_place=True,
    )
    assert state.current_objective is Objective.COMPLETE_KEY_EXCHANGE


def test_persephone_partner_unknown_uses_cautious_same_team_probe() -> None:
    state = StrategicState(
        my_role=Role.PERSEPHONE,
        my_team=Team.NYMPHS,
        my_room=Room.UNDERWORLD,
    )

    directive = evaluate_persephone(state, BeliefState(), ActionMemory())

    assert directive.mode == "probe_systematic"
    assert directive.params == ProbeSystematicParams(
        target_team=Team.NYMPHS,
        intent=ProbeIntent.FIND_KEY_PARTNER,
        cautious=True,
        aggressive=False,
    )
    assert state.current_objective is Objective.FIND_KEY_PARTNER


def test_demeter_partner_unknown_uses_aggressive_same_team_probe() -> None:
    state = StrategicState(
        my_role=Role.DEMETER,
        my_team=Team.NYMPHS,
        my_room=Room.UNDERWORLD,
    )

    directive = evaluate_demeter(state, BeliefState(), ActionMemory())

    assert directive.mode == "probe_systematic"
    assert directive.params == ProbeSystematicParams(
        target_team=Team.NYMPHS,
        intent=ProbeIntent.FIND_KEY_PARTNER,
        cautious=False,
        aggressive=True,
    )


def test_hysteresis_preserves_directive_params() -> None:
    belief_state = _belief_state(tick=25)
    held = ModeDirective(
        "probe_systematic",
        ProbeSystematicParams(
            target_team=Team.SHADES,
            intent=ProbeIntent.LOCATE_ENEMY_KEY,
            aggressive=True,
        ),
    )
    belief_state.extra[LAST_DIRECTIVE] = held
    belief_state.extra[LAST_DIRECTIVE_MODE] = held.mode
    belief_state.extra[LAST_DIRECTIVE_TICK] = 0

    directive, inferences = meta_decide(belief_state, ActionMemory())

    assert directive == held
    assert inferences is not None
    assert inferences[LAST_DIRECTIVE] == held


def test_meta_decide_stores_current_objective_for_whisper_protocol() -> None:
    belief_state = _belief_state()
    partner_id = _pid(1, belief_state)
    partner = PlayerKnowledge.create(partner_id)
    partner.role = Role.CERBERUS
    partner.role_source = RoleSource.ROLE_EXCHANGE
    partner.team = Team.SHADES
    partner.team_source = TeamSource.ROLE_EXCHANGE
    partner.room = Room.UNDERWORLD
    belief_state.extra[PLAYER_KNOWLEDGE][partner_id] = partner
    belief_state.players[1] = PlayerInfo(
        role="cerberus",
        team="shades",
        room=Room.UNDERWORLD,
        position=(55, 50, belief_state.tick),
    )

    directive, _ = meta_decide(belief_state, ActionMemory())

    state = belief_state.extra[STRATEGIC_STATE]
    assert directive.mode == "probe_target"
    assert isinstance(directive.params, ProbeTargetParams)
    assert state.current_objective is Objective.COMPLETE_KEY_EXCHANGE


def test_mode_registry_accepts_evaluator_directive_param_types() -> None:
    registry = build_registry()
    state = StrategicState(
        my_role=Role.HADES,
        my_team=Team.SHADES,
        my_room=Room.UNDERWORLD,
        key_partner_found=True,
        key_partner_id=(PLAYER_COLORS[1], 1),
        key_partner_room=Room.UNDERWORLD,
    )

    directive = evaluate_hades(state, BeliefState(), ActionMemory())

    mode_cls = registry.get(directive.mode)
    assert mode_cls is not None
    assert isinstance(directive.params, mode_cls.params_type)
