"""Tests for mapping validated LLM decisions into Orpheus execution."""

from __future__ import annotations

from agents.eurydice.llm_action_mode import LLMActionMode, LLMActionParams
from agents.eurydice.llm_context import DECISION_SCHEMA_VERSION
from agents.eurydice.llm_executor import directive_for_decision
from agents.eurydice.advanced_modes import (
    HoldPositionMode,
    HostageSelectMode,
    HostageSelectParams,
)
from agents.eurydice.ext_keys import MODE_COMPLETE
from agents.eurydice.modes import ProbeTargetParams
from agents.eurydice.policy import build_registry
from orpheus.belief_state import BeliefState, PlayerInfo
from orpheus.perception.types import HostageGrid, PlayerShape, View
from orpheus.tasks import (
    CloseViewTask,
    IdleTask,
    MoveToTask,
    RequestEntryTask,
    SelectHostagesTask,
    SendMessageTask,
)


def _decision(action: str, **overrides) -> dict:
    value = {
        "schema_version": DECISION_SCHEMA_VERSION,
        "action": action,
        "surface": None,
        "target": None,
        "destination": None,
        "hostage_targets": None,
        "message": None,
        "reveal_color": False,
        "reveal_role": False,
        "confidence": 0.8,
        "rationale": "test",
    }
    value.update(overrides)
    return value


def test_probe_decision_maps_to_probe_target_directive() -> None:
    directive = directive_for_decision(
        _decision("probe_player", target=[14, 1]),
    )

    assert directive is not None
    assert directive.mode == "probe_target"
    assert directive.params == ProbeTargetParams(target=(14, 1))


def test_move_decision_maps_to_registered_llm_action_mode() -> None:
    directive = directive_for_decision(
        _decision("move_to", destination=[80, 70]),
    )
    registry = build_registry()

    assert directive is not None
    assert directive.mode == "llm_action"
    assert isinstance(directive.params, LLMActionParams)
    assert directive.params.destination == (80, 70)
    mode_cls = registry.get(directive.mode)
    assert mode_cls is not None
    assert isinstance(directive.params, mode_cls.params_type)


def test_hostage_decision_maps_targets_to_hostage_params() -> None:
    directive = directive_for_decision(
        _decision("select_hostage", hostage_targets=[[14, 1]]),
    )

    assert directive is not None
    assert directive.mode == "hostage_select"
    assert directive.params == HostageSelectParams(move=((14, 1),))


def test_llm_action_mode_selects_move_task() -> None:
    mode = LLMActionMode()
    mode.params = LLMActionParams(action="move_to", destination=(80, 70))

    task = mode.select_task(BeliefState(view=View.PLAYING), object())

    assert task == MoveToTask(80, 70)


def test_llm_action_mode_requests_whisper_entry_for_join() -> None:
    state = BeliefState(view=View.PLAYING, player_count=4)
    state.players[1] = PlayerInfo()
    mode = LLMActionMode()
    mode.params = LLMActionParams(action="join_whisper", target=(14, 1))

    task = mode.select_task(state, object())

    assert task == RequestEntryTask(player_index=1)


def test_llm_action_mode_sends_global_only_from_global_view() -> None:
    mode = LLMActionMode()
    mode.params = LLMActionParams(action="send_global", message="WHO HAS HADES")

    open_task = mode.select_task(BeliefState(view=View.PLAYING), object())
    send_task = mode.select_task(BeliefState(view=View.GLOBAL_CHAT), object())

    assert type(open_task).__name__ == "OpenGlobalChatTask"
    assert send_task == SendMessageTask(text="WHO HAS HADES", channel="global")


def test_llm_action_mode_closes_overlay_before_cross_open() -> None:
    mode = LLMActionMode()
    mode.params = LLMActionParams(action="open_info")

    task = mode.select_task(BeliefState(view=View.GLOBAL_CHAT), object())

    assert task == CloseViewTask()


def test_llm_action_mode_completes_stale_move_after_view_change() -> None:
    state = BeliefState(view=View.WHISPER)
    mode = LLMActionMode()
    mode.mode_enter(state, object())
    mode.params = LLMActionParams(action="move_to", destination=(80, 70))

    task = mode.select_task(state, object())

    assert isinstance(task, IdleTask)
    assert state.extra[MODE_COMPLETE] is True


def test_llm_action_mode_does_not_send_stale_whisper_from_playing() -> None:
    state = BeliefState(view=View.PLAYING)
    mode = LLMActionMode()
    mode.mode_enter(state, object())
    mode.params = LLMActionParams(action="send_whisper", message="SECRET")

    task = mode.select_task(state, object())

    assert isinstance(task, IdleTask)
    assert state.extra[MODE_COMPLETE] is True


def test_hostage_select_mode_uses_llm_requested_grid_position() -> None:
    state = BeliefState(view=View.HOSTAGE_SELECT)
    state.hostage_selections = HostageGrid(
        eligible_colors=[14, 8],
        eligible_shapes=[PlayerShape.SQUARE, PlayerShape.TRIANGLE],
        count_label="0/1 HOSTAGES",
    )
    mode = HostageSelectMode()
    mode.params = HostageSelectParams(move=((8, 2),))

    task = mode.select_task(state, object())

    assert task == SelectHostagesTask((1,))


def test_hostage_select_mode_completes_after_phase_advances() -> None:
    state = BeliefState(view=View.LEADER_SUMMIT)
    mode = HostageSelectMode()
    mode.mode_enter(state, object())

    task = mode.select_task(state, object())

    assert isinstance(task, IdleTask)
    assert state.extra[MODE_COMPLETE] is True


def test_hold_position_mode_completes_in_hostage_exchange() -> None:
    state = BeliefState(view=View.HOSTAGE_EXCHANGE)
    mode = HoldPositionMode()
    mode.mode_enter(state, object())

    task = mode.select_task(state, object())

    assert isinstance(task, IdleTask)
    assert state.extra[MODE_COMPLETE] is True
