"""Tests for optional runtime LLM control in Eurydice meta_decide."""

from __future__ import annotations

from orpheus.action_memory import ActionMemory
from orpheus.belief_state import BeliefState, PlayerInfo
from orpheus.perception.types import HostageGrid, PlayerShape, Room, View

from agents.eurydice.advanced_modes import HostageSelectParams
from agents.eurydice.llm_context import DECISION_SCHEMA_VERSION
from agents.eurydice.meta_decide import meta_decide
from agents.eurydice.modes import ProbeTargetParams
from agents.eurydice.pipeline import initialize_eurydice_state, player_index_to_id
from agents.eurydice.whisper_mode import InWhisperMode, InWhisperParams
from orpheus.tasks import GrantEntryTask


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
    belief_state.players[1] = PlayerInfo(
        position=(70, 50, belief_state.tick),
        room=Room.UNDERWORLD,
    )
    return belief_state


def test_meta_decide_targets_control_can_replace_systematic_probe() -> None:
    belief_state = _state()
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


def test_meta_decide_throttles_expensive_provider_between_calls(monkeypatch) -> None:
    belief_state = _state()
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
