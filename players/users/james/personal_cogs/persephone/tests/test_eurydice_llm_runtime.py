"""Tests for optional runtime LLM control in Eurydice meta_decide."""

from __future__ import annotations

from orpheus.action_memory import ActionMemory
from orpheus.belief_state import BeliefState, ChatMessageRecord, PlayerInfo
from orpheus.mode import ModeDirective, ModeParams
from orpheus.perception.types import HostageGrid, PlayerShape, Room, View

from agents.eurydice.advanced_modes import HostageSelectParams
from agents.eurydice.ext_keys import PLAYER_KNOWLEDGE
from agents.eurydice.knowledge import PlayerKnowledge
from agents.eurydice.llm_controller import maybe_override_directive
from agents.eurydice.llm_context import DECISION_SCHEMA_VERSION
from agents.eurydice.meta_decide import meta_decide
from agents.eurydice.modes import ProbeTargetParams
from agents.eurydice.pipeline import initialize_eurydice_state, player_index_to_id
from agents.eurydice.strategic_state import StrategicState
from agents.eurydice.types import Objective, Role, Team
from agents.eurydice.whisper_mode import InWhisperMode, InWhisperParams
from orpheus.tasks import (
    AcceptRoleExchangeTask,
    GrantEntryTask,
    OfferRoleExchangeTask,
)


def _state() -> BeliefState:
    belief_state = BeliefState(
        tick=100,
        view=View.PLAYING,
        round=1,
        timer_secs=12,
        my_index=0,
        my_color=3,
        my_role="hades",
        my_team="shades",
        my_room=Room.UNDERWORLD,
        room=Room.UNDERWORLD,
        position=(50, 50),
        player_count=4,
        round_schedule=[(15, 1), (15, 1), (15, 1)],
    )
    initialize_eurydice_state(belief_state)
    belief_state.extra["_identity_global_chat_review_done"] = belief_state.round
    belief_state.chat_history.append(
        ChatMessageRecord(0, 100, "global", "I AM HADES")
    )
    belief_state.players[1] = PlayerInfo(
        position=(70, 50, belief_state.tick),
        room=Room.UNDERWORLD,
    )
    return belief_state


def _mark_key_exchange_done(belief_state: BeliefState) -> None:
    partner = player_index_to_id(1, belief_state)
    assert partner is not None
    record = PlayerKnowledge.create(partner)
    record.role = Role.CERBERUS
    record.team = Team.SHADES
    record.has_exchanged_roles_with_us = True
    belief_state.extra[PLAYER_KNOWLEDGE][partner] = record
    belief_state.my_exchange_partner = 1


def test_meta_decide_targets_control_can_replace_systematic_probe() -> None:
    belief_state = _state()
    _mark_key_exchange_done(belief_state)
    target = player_index_to_id(1, belief_state)

    directive, _ = meta_decide(
        belief_state,
        ActionMemory(),
        llm_control="targets",
        llm_provider="heuristic",
    )

    assert directive.mode == "probe_target"
    assert isinstance(directive.params, ProbeTargetParams)
    assert directive.params.target == target


def test_meta_decide_shadow_control_keeps_deterministic_directive() -> None:
    directive, _ = meta_decide(
        _state(),
        ActionMemory(),
        llm_control="shadow",
        llm_provider="heuristic",
    )

    assert directive.mode == "probe_systematic"


def test_meta_decide_off_keeps_deterministic_directive() -> None:
    directive, _ = meta_decide(_state(), ActionMemory())

    assert directive.mode == "probe_systematic"


def test_meta_decide_all_control_can_select_global_action(monkeypatch) -> None:
    class Provider:
        name = "fake"

        def decide(self, context, prompt):
            del context, prompt
            return {
                "schema_version": DECISION_SCHEMA_VERSION,
                "action": "send_global",
                "surface": "global",
                "target": None,
                "destination": None,
                "hostage_targets": None,
                "message": "STATUS?",
                "reveal_color": False,
                "reveal_role": False,
                "confidence": 0.9,
                "rationale": "ask for status",
            }

    monkeypatch.setattr("agents.eurydice.llm_controller.make_provider", lambda name: Provider())
    belief_state = _state()
    belief_state.my_role = "shade"
    belief_state.chat_history[-1] = ChatMessageRecord(
        0,
        100,
        "global",
        "I AM SHADE",
    )
    belief_state.view = View.GLOBAL_CHAT

    directive, _ = meta_decide(
        belief_state,
        ActionMemory(),
        llm_control="all",
        llm_provider="fake",
    )

    assert directive.mode == "llm_action"
    assert getattr(directive.params, "action", None) == "send_global"
    assert getattr(directive.params, "message", None) == "STATUS?"


def test_meta_decide_preserves_key_partner_probe_params_when_llm_agrees(monkeypatch) -> None:
    belief_state = _state()
    belief_state.my_role = "cerberus"
    belief_state.chat_history.append(
        ChatMessageRecord(0, 100, "global", "I AM CERBERUS")
    )
    target = player_index_to_id(1, belief_state)
    assert target is not None
    record = PlayerKnowledge.create(target)
    record.role = Role.HADES
    record.room = Room.UNDERWORLD
    belief_state.extra[PLAYER_KNOWLEDGE][target] = record

    class Provider:
        name = "fake"

        def decide(self, context, prompt):
            del context, prompt
            return {
                "schema_version": DECISION_SCHEMA_VERSION,
                "action": "probe_player",
                "surface": "probe",
                "target": [target[0], target[1]],
                "destination": None,
                "hostage_targets": None,
                "message": None,
                "reveal_color": False,
                "reveal_role": False,
                "confidence": 0.9,
                "rationale": "probe key partner",
            }

    monkeypatch.setattr("agents.eurydice.llm_controller.make_provider", lambda name: Provider())

    directive, _ = meta_decide(
        belief_state,
        ActionMemory(),
        llm_control="all",
        llm_provider="fake",
    )

    assert directive.mode == "probe_target"
    assert isinstance(directive.params, ProbeTargetParams)
    assert directive.params.target == target
    assert directive.params.request_only is False
    assert directive.params.open_in_place is True
    assert directive.params.skip_color_exchange is True


def test_llm_key_partner_probe_from_systematic_keeps_key_exchange_params(monkeypatch) -> None:
    belief_state = _state()
    target = player_index_to_id(1, belief_state)
    assert target is not None
    state = StrategicState(
        my_role=Role.HADES,
        my_team=Team.SHADES,
        key_partner_id=target,
        current_objective=Objective.FIND_KEY_PARTNER,
    )

    class Provider:
        name = "fake"

        def decide(self, context, prompt):
            del context, prompt
            return {
                "schema_version": DECISION_SCHEMA_VERSION,
                "action": "probe_player",
                "surface": "probe",
                "target": [target[0], target[1]],
                "destination": None,
                "hostage_targets": None,
                "message": None,
                "reveal_color": False,
                "reveal_role": False,
                "confidence": 0.9,
                "rationale": "probe known key partner",
            }

    monkeypatch.setattr("agents.eurydice.llm_controller.make_provider", lambda name: Provider())

    directive = maybe_override_directive(
        belief_state,
        state,
        ModeDirective("probe_systematic", ModeParams()),
        control_mode="all",
        provider_name="fake",
    )

    assert directive.mode == "probe_target"
    assert isinstance(directive.params, ProbeTargetParams)
    assert directive.params.target == target
    assert directive.params.request_only is True
    assert directive.params.skip_color_exchange is True


def test_llm_find_key_partner_probe_without_known_partner_keeps_requester_params(
    monkeypatch,
) -> None:
    belief_state = _state()
    target = player_index_to_id(1, belief_state)
    assert target is not None
    state = StrategicState(
        my_role=Role.CERBERUS,
        my_team=Team.SHADES,
        key_partner_id=None,
        current_objective=Objective.FIND_KEY_PARTNER,
    )

    class Provider:
        name = "fake"

        def decide(self, context, prompt):
            del context, prompt
            return {
                "schema_version": DECISION_SCHEMA_VERSION,
                "action": "probe_player",
                "surface": "probe",
                "target": [target[0], target[1]],
                "destination": None,
                "hostage_targets": None,
                "message": None,
                "reveal_color": False,
                "reveal_role": False,
                "confidence": 0.9,
                "rationale": "probe a possible key partner",
            }

    monkeypatch.setattr("agents.eurydice.llm_controller.make_provider", lambda name: Provider())

    directive = maybe_override_directive(
        belief_state,
        state,
        ModeDirective("probe_systematic", ModeParams()),
        control_mode="all",
        provider_name="fake",
    )

    assert directive.mode == "probe_target"
    assert isinstance(directive.params, ProbeTargetParams)
    assert directive.params.target == target
    assert directive.params.open_in_place is True
    assert directive.params.skip_color_exchange is True
    assert directive.params.max_approach_ticks == 240


def test_llm_key_role_probe_uses_rendezvous_params_without_key_objective(
    monkeypatch,
) -> None:
    belief_state = _state()
    target = player_index_to_id(1, belief_state)
    assert target is not None
    state = StrategicState(
        my_role=Role.CERBERUS,
        my_team=Team.SHADES,
        current_objective=Objective.IDLE,
    )

    class Provider:
        name = "fake"

        def decide(self, context, prompt):
            del context, prompt
            return {
                "schema_version": DECISION_SCHEMA_VERSION,
                "action": "probe_player",
                "surface": "probe",
                "target": [target[0], target[1]],
                "destination": None,
                "hostage_targets": None,
                "message": None,
                "reveal_color": False,
                "reveal_role": False,
                "confidence": 0.9,
                "rationale": "probe Hades from chat context",
            }

    monkeypatch.setattr("agents.eurydice.llm_controller.make_provider", lambda name: Provider())

    directive = maybe_override_directive(
        belief_state,
        state,
        ModeDirective("probe_systematic", ModeParams()),
        control_mode="all",
        provider_name="fake",
    )

    assert directive.mode == "probe_target"
    assert isinstance(directive.params, ProbeTargetParams)
    assert directive.params.target == target
    assert directive.params.open_in_place is True
    assert directive.params.skip_color_exchange is True
    assert directive.params.intent.name == "FIND_KEY_PARTNER"


def test_llm_key_role_probe_pins_known_key_partner(monkeypatch) -> None:
    belief_state = _state()
    wrong_target = player_index_to_id(1, belief_state)
    belief_state.players[2] = PlayerInfo(
        position=(55, 50, belief_state.tick),
        room=Room.UNDERWORLD,
    )
    key_partner = player_index_to_id(2, belief_state)
    assert wrong_target is not None
    assert key_partner is not None
    state = StrategicState(
        my_role=Role.CERBERUS,
        my_team=Team.SHADES,
        key_partner_id=key_partner,
        current_objective=Objective.IDLE,
    )

    class Provider:
        name = "fake"

        def decide(self, context, prompt):
            del context, prompt
            return {
                "schema_version": DECISION_SCHEMA_VERSION,
                "action": "probe_player",
                "surface": "probe",
                "target": [wrong_target[0], wrong_target[1]],
                "destination": None,
                "hostage_targets": None,
                "message": None,
                "reveal_color": False,
                "reveal_role": False,
                "confidence": 0.9,
                "rationale": "model picked a non-partner",
            }

    monkeypatch.setattr("agents.eurydice.llm_controller.make_provider", lambda name: Provider())

    directive = maybe_override_directive(
        belief_state,
        state,
        ModeDirective("probe_systematic", ModeParams()),
        control_mode="all",
        provider_name="fake",
    )

    assert directive.mode == "probe_target"
    assert isinstance(directive.params, ProbeTargetParams)
    assert directive.params.target == key_partner
    assert directive.params.open_in_place is True
    assert directive.params.skip_color_exchange is True


def test_llm_key_probe_rejects_non_probe_override(monkeypatch) -> None:
    belief_state = _state()
    state = StrategicState(
        my_role=Role.HADES,
        my_team=Team.SHADES,
        current_objective=Objective.FIND_KEY_PARTNER,
    )
    fallback = ModeDirective("probe_systematic", ModeParams())

    class Provider:
        name = "fake"

        def decide(self, context, prompt):
            del context, prompt
            return {
                "schema_version": DECISION_SCHEMA_VERSION,
                "action": "send_whisper",
                "surface": "summit",
                "target": None,
                "destination": None,
                "hostage_targets": None,
                "message": "MEET CERBERUS",
                "reveal_color": False,
                "reveal_role": False,
                "confidence": 0.9,
                "rationale": "chat instead of rendezvous",
            }

    monkeypatch.setattr("agents.eurydice.llm_controller.make_provider", lambda name: Provider())

    directive = maybe_override_directive(
        belief_state,
        state,
        fallback,
        control_mode="all",
        provider_name="fake",
    )

    assert directive is fallback
    assert directive.mode == "probe_systematic"


def test_meta_decide_throttles_expensive_provider_between_calls(monkeypatch) -> None:
    belief_state = _state()
    _mark_key_exchange_done(belief_state)
    target = player_index_to_id(1, belief_state)
    assert target is not None
    calls = []

    class Provider:
        name = "fake-expensive"
        decision_cooldown_ticks = 100

        def decide(self, context, prompt):
            calls.append((context, prompt))
            return {
                "schema_version": DECISION_SCHEMA_VERSION,
                "action": "probe_player",
                "surface": "probe",
                "target": [target[0], target[1]],
                "destination": None,
                "hostage_targets": None,
                "message": None,
                "reveal_color": False,
                "reveal_role": False,
                "confidence": 0.9,
                "rationale": "probe reachable target",
            }

    provider = Provider()
    monkeypatch.setattr(
        "agents.eurydice.llm_controller.make_provider",
        lambda name: provider,
    )

    directive, inferences = meta_decide(
        belief_state,
        ActionMemory(),
        llm_control="all",
        llm_provider="fake",
    )
    assert directive.mode == "probe_target"
    assert len(calls) == 1

    belief_state.inferences = inferences or {}
    belief_state.tick += 60
    meta_decide(
        belief_state,
        ActionMemory(),
        llm_control="all",
        llm_provider="fake",
    )

    assert len(calls) == 1


def test_meta_decide_all_control_can_override_hostage_phase(monkeypatch) -> None:
    belief_state = _state()
    _mark_key_exchange_done(belief_state)
    target = player_index_to_id(1, belief_state)
    assert target is not None
    belief_state.view = View.HOSTAGE_SELECT
    belief_state.is_leader = True
    belief_state.hostage_selections = HostageGrid(
        eligible_colors=[target[0]],
        eligible_shapes=[PlayerShape(target[1])],
        selected_positions=[],
        count_label="0/1 HOSTAGES",
    )

    class Provider:
        name = "fake"

        def decide(self, context, prompt):
            del context, prompt
            return {
                "schema_version": DECISION_SCHEMA_VERSION,
                "action": "select_hostage",
                "surface": "hostage",
                "target": None,
                "destination": None,
                "hostage_targets": [[target[0], target[1]]],
                "message": None,
                "reveal_color": False,
                "reveal_role": False,
                "confidence": 0.9,
                "rationale": "select requested hostage",
            }

    monkeypatch.setattr("agents.eurydice.llm_controller.make_provider", lambda name: Provider())

    directive, _ = meta_decide(
        belief_state,
        ActionMemory(),
        llm_control="all",
        llm_provider="fake",
    )

    assert directive.mode == "hostage_select"
    assert directive.params == HostageSelectParams(move=(target,))


def test_meta_decide_all_control_can_override_leader_summit(monkeypatch) -> None:
    class Provider:
        name = "fake"

        def decide(self, context, prompt):
            del context, prompt
            return {
                "schema_version": DECISION_SCHEMA_VERSION,
                "action": "send_whisper",
                "surface": "summit",
                "target": None,
                "destination": None,
                "hostage_targets": None,
                "message": "SEND ME",
                "reveal_color": False,
                "reveal_role": False,
                "confidence": 0.9,
                "rationale": "request transfer",
            }

    monkeypatch.setattr("agents.eurydice.llm_controller.make_provider", lambda name: Provider())
    belief_state = _state()
    _mark_key_exchange_done(belief_state)
    belief_state.view = View.LEADER_SUMMIT
    belief_state.is_leader = True

    directive, _ = meta_decide(
        belief_state,
        ActionMemory(),
        llm_control="all",
        llm_provider="fake",
    )

    assert directive.mode == "llm_action"
    assert getattr(directive.params, "action", None) == "send_whisper"
    assert getattr(directive.params, "message", None) == "SEND ME"


def test_meta_decide_passes_llm_config_into_whisper_mode() -> None:
    belief_state = _state()
    _mark_key_exchange_done(belief_state)
    belief_state.view = View.WHISPER
    belief_state.in_whisper = True

    directive, _ = meta_decide(
        belief_state,
        ActionMemory(),
        llm_control="whispers",
        llm_provider="heuristic",
    )

    assert directive.mode == "in_whisper"
    assert directive.params == InWhisperParams(
        llm_control="whispers",
        llm_provider="heuristic",
    )


def test_in_whisper_llm_control_can_grant_pending_entry() -> None:
    belief_state = _state()
    belief_state.view = View.WHISPER
    belief_state.in_whisper = True
    belief_state.whisper_occupants = [0]
    belief_state.pending_entry = 1
    mode = InWhisperMode()
    mode.params = InWhisperParams(llm_control="whispers", llm_provider="heuristic")
    memory = ActionMemory()
    mode.mode_enter(belief_state, memory)

    task = mode.select_task(belief_state, memory)

    assert isinstance(task, GrantEntryTask)


def test_in_whisper_llm_control_can_accept_pending_role_offer(monkeypatch) -> None:
    """LLM-driven whisper hook should accept a pending role offer.

    Before this hook was wired into _role_exchange_task, the LLM only got
    consulted on the first message and entry-grant decisions; exchange
    decisions were fully deterministic. With the hook in place, a provider
    that returns ``accept_role`` now drives the actual accept menu sequence.
    """
    from agents.eurydice.llm_context import DECISION_SCHEMA_VERSION

    belief_state = _state()
    belief_state.view = View.WHISPER
    belief_state.in_whisper = True
    belief_state.whisper_occupants = [0, 1]
    belief_state.pending_entry = None
    belief_state.active_role_offers = {1: 0}  # player 1 offered role to us
    partner = player_index_to_id(1, belief_state)
    assert partner is not None

    class Provider:
        name = "fake"

        def decide(self, context, prompt):
            del context, prompt
            return {
                "schema_version": DECISION_SCHEMA_VERSION,
                "action": "accept_role",
                "surface": "whisper",
                "target": list(partner),
                "destination": None,
                "hostage_targets": None,
                "message": None,
                "reveal_color": False,
                "reveal_role": True,
                "confidence": 0.9,
                "rationale": "accept partner's role offer",
            }

    monkeypatch.setattr(
        "agents.eurydice.whisper_mode.make_provider",
        lambda name: Provider(),
        raising=False,
    )
    # The actual import in _llm_whisper_task is local; patch via importable name
    import agents.eurydice.llm_provider as llm_provider_mod

    monkeypatch.setattr(llm_provider_mod, "make_provider", lambda name: Provider())

    mode = InWhisperMode()
    mode.params = InWhisperParams(llm_control="whispers", llm_provider="fake")
    memory = ActionMemory()
    mode.mode_enter(belief_state, memory)

    # Drive FSM through ENTER -> ASSESS -> ROLE_EXCHANGE
    for _ in range(4):
        task = mode.select_task(belief_state, memory)
        if isinstance(task, AcceptRoleExchangeTask):
            break

    assert isinstance(task, AcceptRoleExchangeTask), (
        f"expected AcceptRoleExchangeTask, got {type(task).__name__}"
    )
    assert task.player_index == 1


def test_in_whisper_llm_control_can_proactively_offer_role(monkeypatch) -> None:
    """LLM-driven whisper hook should also drive proactive role offers."""
    from agents.eurydice.llm_context import DECISION_SCHEMA_VERSION

    belief_state = _state()
    belief_state.view = View.WHISPER
    belief_state.in_whisper = True
    belief_state.whisper_occupants = [0, 1]

    class Provider:
        name = "fake"

        def decide(self, context, prompt):
            del context, prompt
            return {
                "schema_version": DECISION_SCHEMA_VERSION,
                "action": "offer_role",
                "surface": "whisper",
                "target": None,
                "destination": None,
                "hostage_targets": None,
                "message": None,
                "reveal_color": False,
                "reveal_role": True,
                "confidence": 0.8,
                "rationale": "offer role to whisper occupant",
            }

    import agents.eurydice.llm_provider as llm_provider_mod

    monkeypatch.setattr(llm_provider_mod, "make_provider", lambda name: Provider())

    mode = InWhisperMode()
    mode.params = InWhisperParams(llm_control="whispers", llm_provider="fake")
    memory = ActionMemory()
    mode.mode_enter(belief_state, memory)

    for _ in range(4):
        task = mode.select_task(belief_state, memory)
        if isinstance(task, OfferRoleExchangeTask):
            break

    assert isinstance(task, OfferRoleExchangeTask), (
        f"expected OfferRoleExchangeTask, got {type(task).__name__}"
    )
