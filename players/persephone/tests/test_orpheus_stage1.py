"""Unit tests for the Orpheus Stage 1 inner-loop skeleton."""

from __future__ import annotations

from unittest.mock import MagicMock, call, patch

import numpy as np
import pytest

from orpheus.action_memory import ActionMemory
from orpheus.belief_state import BeliefState
from orpheus.idle import IdleMode, IdleTask
from orpheus.mode import Mode, ModeDirective, ModeRegistry
from orpheus.perception.types import FramePerception
from orpheus.pipeline import Pipeline, _tasks_equivalent
from orpheus.task import ActCommand, Task
from orpheus.types import View


@pytest.fixture
def pipeline_factory():
    """Build a Pipeline with mocked transports."""

    def _factory(mode: Mode | None = None):
        send_input = MagicMock()
        send_chat = MagicMock()
        registry = ModeRegistry()
        pipeline = Pipeline(
            initial_mode=mode if mode is not None else IdleMode(),
            mode_registry=registry,
            send_input=send_input,
            send_chat=send_chat,
        )
        return pipeline, send_input, send_chat

    return _factory


def test_idle_task_constructible_and_accepts_all_views() -> None:
    """IdleTask constructs and is valid in every known view."""
    assert IdleTask() is not None
    assert set(View) <= IdleTask.valid_views


def test_idle_task_returns_noop_act_command() -> None:
    """IdleTask emits the default noop ActCommand."""
    command = IdleTask().select_action(BeliefState(), ActionMemory())

    assert command == ActCommand()


def test_idle_mode_returns_idle_task_each_tick() -> None:
    """IdleMode returns equivalent IdleTask instances across ticks."""
    mode = IdleMode()
    belief_state = BeliefState()
    action_memory = ActionMemory()

    first_task = mode.select_task(belief_state, action_memory)
    second_task = mode.select_task(belief_state, action_memory)

    assert isinstance(first_task, IdleTask)
    assert isinstance(second_task, IdleTask)
    assert _tasks_equivalent(first_task, second_task)


def test_pipeline_ticks_without_error_and_sends_zero_input(
    pipeline_factory,
) -> None:
    """Pipeline emits one zero-input packet per idle tick."""
    pipeline, send_input, send_chat = pipeline_factory()
    frame = np.zeros((128, 128), dtype=np.uint8)

    with patch(
        "orpheus.pipeline.parse_frame",
        return_value=FramePerception(view=View.LOBBY),
    ):
        for _ in range(5):
            pipeline.tick(frame)

    assert pipeline.belief_state.tick == 5
    assert send_input.call_count == 5
    assert send_input.call_args_list == [call(0)] * 5
    send_chat.assert_not_called()


def test_send_act_command_lowers_correctly(pipeline_factory) -> None:
    """ActCommand lowering sends reset, button, and chat packets correctly."""
    pipeline, send_input, send_chat = pipeline_factory()

    pipeline._send_act_command(ActCommand())
    send_input.assert_called_once_with(0)
    send_chat.assert_not_called()
    send_input.reset_mock()
    send_chat.reset_mock()

    pipeline._send_act_command(ActCommand(buttons=0x20))
    send_input.assert_called_once_with(0x20)
    send_chat.assert_not_called()
    send_input.reset_mock()
    send_chat.reset_mock()

    pipeline._send_act_command(ActCommand(buttons=0xFF))
    send_input.assert_called_once_with(0x7F)
    send_chat.assert_not_called()
    send_input.reset_mock()
    send_chat.reset_mock()

    pipeline._send_act_command(ActCommand(chat_text="hi"))
    send_input.assert_called_once_with(0)
    send_chat.assert_called_once_with("hi")
    send_input.reset_mock()
    send_chat.reset_mock()

    pipeline._send_act_command(ActCommand(buttons=0x10, chat_text="ok"))
    send_input.assert_called_once_with(0x10)
    send_chat.assert_called_once_with("ok")
    send_input.reset_mock()
    send_chat.reset_mock()

    pipeline._send_act_command(
        ActCommand(reset_input=True, buttons=0x40, chat_text="ignored")
    )
    send_input.assert_called_once_with(0xFF)
    send_chat.assert_not_called()


def test_task_change_clears_action_memory(pipeline_factory) -> None:
    """ActionMemory clears when the active task changes."""

    class TaskA(Task):
        """First task emitted by SwitchingMode."""

        valid_views: set[View] = {View.LOBBY, View.PLAYING}

        def select_action(self, belief_state, action_memory) -> ActCommand:
            """Emit a non-noop TaskA button."""
            return ActCommand(buttons=0x01)

    class TaskB(Task):
        """Second task emitted by SwitchingMode."""

        valid_views: set[View] = {View.LOBBY, View.PLAYING}

        def select_action(self, belief_state, action_memory) -> ActCommand:
            """Emit a non-noop TaskB button."""
            return ActCommand(buttons=0x02)

    class SwitchingMode(Mode):
        """Return TaskA for three ticks, then TaskB."""

        def __init__(self) -> None:
            self.tick_count = 0

        def select_task(self, belief_state, action_memory) -> Task | None:
            """Select TaskA for initial ticks, then switch to TaskB."""
            task = TaskA() if self.tick_count < 3 else TaskB()
            self.tick_count += 1
            return task

        def mode_enter(self, belief_state, action_memory) -> None:
            """Perform no setup."""
            pass

        def mode_switch_cleanup(
            self,
            belief_state,
            action_memory,
            new_mode_directive: ModeDirective,
        ) -> None:
            """Perform no cleanup."""
            pass

    pipeline, _, _ = pipeline_factory(SwitchingMode())
    frame = np.zeros((128, 128), dtype=np.uint8)

    with patch(
        "orpheus.pipeline.parse_frame",
        return_value=FramePerception(view=View.LOBBY),
    ):
        for _ in range(3):
            pipeline.tick(frame)
        assert pipeline.action_memory.ticks_active == 3

        pipeline.tick(frame)

    assert pipeline.action_memory.ticks_active == 1
    assert isinstance(pipeline.current_task, TaskB)


def test_valid_views_mismatch_emits_noop_without_calling_select_action(
    pipeline_factory,
) -> None:
    """Pipeline skips task action selection when the view is invalid."""

    class PlayingOnlyTask(Task):
        """Task that must only run in PLAYING view."""

        valid_views: set[View] = {View.PLAYING}
        select_action = MagicMock(
            side_effect=AssertionError("should not be called")
        )

        def __init__(self) -> None:
            self.select_action.reset_mock()

    class PlayingOnlyMode(Mode):
        """Mode that returns a playing-only task."""

        def __init__(self) -> None:
            self.task = PlayingOnlyTask()

        def select_task(self, belief_state, action_memory) -> Task | None:
            """Return the playing-only task."""
            return self.task

        def mode_enter(self, belief_state, action_memory) -> None:
            """Perform no setup."""
            pass

        def mode_switch_cleanup(
            self,
            belief_state,
            action_memory,
            new_mode_directive: ModeDirective,
        ) -> None:
            """Perform no cleanup."""
            pass

    mode = PlayingOnlyMode()
    pipeline, _, _ = pipeline_factory(mode)
    frame = np.zeros((128, 128), dtype=np.uint8)

    with patch(
        "orpheus.pipeline.parse_frame",
        return_value=FramePerception(view=View.LOBBY),
    ):
        command = pipeline.tick(frame)

    assert command == ActCommand()
    mode.task.select_action.assert_not_called()


def test_whisper_exit_clears_whisper_only_fields(pipeline_factory) -> None:
    """Leaving whisper view clears whisper-only belief fields."""
    pipeline, _, _ = pipeline_factory()
    bs = pipeline.belief_state
    bs.in_whisper = True
    bs.whisper_occupants = [1, 2, 3]
    bs.pending_offers = {"role": True, "color": True}
    bs.active_color_offers = [1]
    bs.active_role_offers = [2]
    bs.last_exchange_event = {
        "type": "offered_lead",
        "tick": 10,
        "participants": [1],
    }
    bs.pending_entry = 5
    bs.menu_state = "something"
    frame = np.zeros((128, 128), dtype=np.uint8)

    with patch(
        "orpheus.pipeline.parse_frame",
        return_value=FramePerception(view=View.PLAYING),
    ):
        pipeline.tick(frame)

    assert bs.in_whisper is False
    assert bs.whisper_occupants == []
    assert bs.pending_offers == {"role": False, "color": False}
    assert bs.active_color_offers == []
    assert bs.active_role_offers == []
    assert bs.last_exchange_event is None
    assert bs.pending_entry is None
    assert bs.menu_state is None


def test_cooldowns_tick_down_and_expire(pipeline_factory) -> None:
    """Cooldowns decrement each tick and entries expire at zero."""
    pipeline, _, _ = pipeline_factory()
    pipeline.belief_state.cooldowns = {"chat": 3, "shout": 1}
    frame = np.zeros((128, 128), dtype=np.uint8)

    with patch(
        "orpheus.pipeline.parse_frame",
        return_value=FramePerception(view=View.LOBBY),
    ):
        pipeline.tick(frame)

    assert pipeline.belief_state.cooldowns == {"chat": 2}
