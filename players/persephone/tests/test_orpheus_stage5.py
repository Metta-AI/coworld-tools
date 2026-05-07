"""Unit tests for the Orpheus Stage 5 hook system."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from orpheus.action_memory import ActionMemory
from orpheus.belief_state import BeliefState, PlayerInfo
from orpheus.hooks import HookPoint, HookRegistry
from orpheus.idle import IdleMode
from orpheus.mode import Mode, ModeRegistry
from orpheus.perception.types import FramePerception
from orpheus.pipeline import Pipeline
from orpheus.task import ActCommand
from orpheus.types import Room, View


@pytest.fixture
def pipeline_factory():
    """Build a Pipeline with mocked transports and optional hooks."""

    def _factory(
        mode: Mode | None = None,
        hook_registry: HookRegistry | None = None,
        current_mode_name: str = "idle",
        logger=None,
    ):
        send_input = MagicMock()
        send_chat = MagicMock()
        registry = ModeRegistry()
        pipeline = Pipeline(
            initial_mode=mode if mode is not None else IdleMode(),
            mode_registry=registry,
            send_input=send_input,
            send_chat=send_chat,
            hook_registry=hook_registry,
            current_mode_name=current_mode_name,
            logger=logger,
        )
        return pipeline, send_input, send_chat

    return _factory


def test_hook_point_enum_has_all_eight_values() -> None:
    """HookPoint exposes exactly the eight DESIGN.md hook point values."""
    expected = {
        "pre_perception",
        "post_perception",
        "pre_belief_update",
        "post_belief_update",
        "pre_decide",
        "post_decide",
        "pre_act",
        "post_act",
    }

    assert {hook_point.value for hook_point in HookPoint} == expected
    assert len(list(HookPoint)) == 8


def test_register_agent_level_hook() -> None:
    """Agent-level hooks fire regardless of active mode."""
    registry = HookRegistry()
    fired = []

    def hook(belief_state: BeliefState) -> None:
        fired.append(belief_state.tick)

    belief_state = BeliefState(tick=3)
    registry.register_hook(HookPoint.POST_BELIEF_UPDATE, hook)
    registry.dispatch(HookPoint.POST_BELIEF_UPDATE, "foo", belief_state)

    assert fired == [3]


def test_register_mode_level_hook() -> None:
    """Mode-level hooks fire only for their registered mode."""
    registry = HookRegistry()
    fired = []

    def hook(belief_state: BeliefState) -> None:
        fired.append(belief_state.tick)

    belief_state = BeliefState(tick=4)
    registry.register_hook(HookPoint.POST_BELIEF_UPDATE, hook, modes=["foo"])
    registry.dispatch(HookPoint.POST_BELIEF_UPDATE, "bar", belief_state)
    registry.dispatch(HookPoint.POST_BELIEF_UPDATE, "foo", belief_state)

    assert fired == [4]


def test_agent_hooks_fire_before_mode_hooks() -> None:
    """Agent-level hooks run before active-mode hooks."""
    registry = HookRegistry()
    order = []

    registry.register_hook(
        HookPoint.POST_BELIEF_UPDATE,
        lambda belief_state: order.append("agent"),
    )
    registry.register_hook(
        HookPoint.POST_BELIEF_UPDATE,
        lambda belief_state: order.append("mode"),
        modes=["idle"],
    )

    registry.dispatch(HookPoint.POST_BELIEF_UPDATE, "idle", BeliefState())

    assert order == ["agent", "mode"]


def test_fifo_within_each_layer() -> None:
    """Hooks preserve FIFO order within agent and mode layers."""
    registry = HookRegistry()
    order = []

    registry.register_hook(
        HookPoint.POST_BELIEF_UPDATE,
        lambda belief_state: order.append("agent-a"),
    )
    registry.register_hook(
        HookPoint.POST_BELIEF_UPDATE,
        lambda belief_state: order.append("agent-b"),
    )
    registry.register_hook(
        HookPoint.POST_BELIEF_UPDATE,
        lambda belief_state: order.append("mode-a"),
        modes=["idle"],
    )
    registry.register_hook(
        HookPoint.POST_BELIEF_UPDATE,
        lambda belief_state: order.append("mode-b"),
        modes=["idle"],
    )

    registry.dispatch(HookPoint.POST_BELIEF_UPDATE, "idle", BeliefState())

    assert order == ["agent-a", "agent-b", "mode-a", "mode-b"]


def test_pre_perception_returns_frame() -> None:
    """pre_perception carries frame mutations and returned replacements."""
    registry = HookRegistry()
    original = np.zeros((2, 2), dtype=np.uint8)
    replacement = np.ones((2, 2), dtype=np.uint8)

    def mutate_in_place(frame, belief_state: BeliefState):
        frame[:, :] = 7
        return None

    def replace_frame(frame, belief_state: BeliefState):
        assert np.array_equal(frame, np.full((2, 2), 7, dtype=np.uint8))
        return replacement

    registry.register_hook(HookPoint.PRE_PERCEPTION, mutate_in_place)
    registry.register_hook(HookPoint.PRE_PERCEPTION, replace_frame)

    result = registry.dispatch(
        HookPoint.PRE_PERCEPTION,
        None,
        BeliefState(),
        original,
    )

    assert np.array_equal(original, np.full((2, 2), 7, dtype=np.uint8))
    assert result is replacement


def test_pre_perception_no_hooks_returns_input_frame_unchanged() -> None:
    """pre_perception returns the original frame when no hooks are present."""
    registry = HookRegistry()
    frame = np.zeros((2, 2), dtype=np.uint8)

    result = registry.dispatch(
        HookPoint.PRE_PERCEPTION,
        None,
        BeliefState(),
        frame,
    )

    assert result is frame


def test_hook_can_mutate_belief_state() -> None:
    """Hook mutations are applied directly to the live belief state."""
    registry = HookRegistry()
    belief_state = BeliefState()

    def hook(belief_state: BeliefState) -> None:
        belief_state.tick = 999

    registry.register_hook(HookPoint.POST_BELIEF_UPDATE, hook)
    registry.dispatch(HookPoint.POST_BELIEF_UPDATE, None, belief_state)

    assert belief_state.tick == 999


def test_subsequent_hook_sees_prior_mutation() -> None:
    """Later hooks at the same point see earlier hook mutations."""
    registry = HookRegistry()
    seen = []

    def first(belief_state: BeliefState) -> None:
        belief_state.tick = 5

    def second(belief_state: BeliefState) -> None:
        seen.append(belief_state.tick)

    registry.register_hook(HookPoint.POST_BELIEF_UPDATE, first)
    registry.register_hook(HookPoint.POST_BELIEF_UPDATE, second)
    registry.dispatch(HookPoint.POST_BELIEF_UPDATE, None, BeliefState())

    assert seen == [5]


def test_crashing_hook_rolls_back_belief_state() -> None:
    """A failing hook restores all belief fields from its pre-hook snapshot."""
    registry = HookRegistry()
    original_player = PlayerInfo(room=Room.UNDERWORLD)
    belief_state = BeliefState(
        tick=42,
        my_index=3,
        my_color=7,
        players={1: original_player},
        extra={"stable": True},
    )

    def crashing_hook(belief_state: BeliefState) -> None:
        belief_state.tick = 1000
        belief_state.my_index = 9
        belief_state.my_color = 11
        belief_state.players[2] = PlayerInfo(room=Room.MORTAL_REALM)
        belief_state.extra["stable"] = False
        raise RuntimeError("boom")

    registry.register_hook(HookPoint.POST_BELIEF_UPDATE, crashing_hook)
    registry.dispatch(HookPoint.POST_BELIEF_UPDATE, None, belief_state)

    assert belief_state.tick == 42
    assert belief_state.my_index == 3
    assert belief_state.my_color == 7
    assert belief_state.players == {1: original_player}
    assert belief_state.extra == {"stable": True}


def test_crashing_hook_does_not_halt_pipeline() -> None:
    """Dispatch continues after a crashing hook with belief rolled back."""
    registry = HookRegistry()
    seen = []
    belief_state = BeliefState(tick=42)

    def crashing_hook(belief_state: BeliefState) -> None:
        belief_state.tick = 1000
        raise RuntimeError("boom")

    def normal_hook(belief_state: BeliefState) -> None:
        seen.append(belief_state.tick)

    registry.register_hook(HookPoint.POST_BELIEF_UPDATE, crashing_hook)
    registry.register_hook(HookPoint.POST_BELIEF_UPDATE, normal_hook)
    registry.dispatch(HookPoint.POST_BELIEF_UPDATE, None, belief_state)

    assert seen == [42]


def test_crashing_hook_logs_error() -> None:
    """A failing hook emits a hook_failed logger message."""
    registry = HookRegistry()
    messages = []

    def crashing_hook(belief_state: BeliefState) -> None:
        raise RuntimeError("boom")

    registry.register_hook(HookPoint.POST_BELIEF_UPDATE, crashing_hook)
    registry.dispatch(
        HookPoint.POST_BELIEF_UPDATE,
        "idle",
        BeliefState(),
        logger=messages.append,
    )

    assert len(messages) == 1
    assert "hook_failed" in messages[0]
    assert "point=post_belief_update" in messages[0]
    assert "RuntimeError" in messages[0]


def test_pipeline_fires_all_eight_hooks_in_order(pipeline_factory) -> None:
    """Pipeline dispatches each hook point in the documented phase order."""
    registry = HookRegistry()
    order = []

    def pre_perception(frame, belief_state: BeliefState):
        order.append(HookPoint.PRE_PERCEPTION)
        return None

    def post_perception(frame, perception, belief_state: BeliefState) -> None:
        order.append(HookPoint.POST_PERCEPTION)

    def pre_belief_update(perception, belief_state: BeliefState) -> None:
        order.append(HookPoint.PRE_BELIEF_UPDATE)

    def post_belief_update(belief_state: BeliefState) -> None:
        order.append(HookPoint.POST_BELIEF_UPDATE)

    def pre_decide(
        belief_state: BeliefState,
        action_memory: ActionMemory,
    ) -> None:
        order.append(HookPoint.PRE_DECIDE)

    def post_decide(
        belief_state: BeliefState,
        action_memory: ActionMemory,
    ) -> None:
        order.append(HookPoint.POST_DECIDE)

    def pre_act(
        belief_state: BeliefState,
        action_memory: ActionMemory,
    ) -> None:
        order.append(HookPoint.PRE_ACT)

    def post_act(
        belief_state: BeliefState,
        action_memory: ActionMemory,
        command: ActCommand,
    ) -> None:
        assert action_memory.last_command is command
        order.append(HookPoint.POST_ACT)

    registry.register_hook(HookPoint.PRE_PERCEPTION, pre_perception)
    registry.register_hook(HookPoint.POST_PERCEPTION, post_perception)
    registry.register_hook(HookPoint.PRE_BELIEF_UPDATE, pre_belief_update)
    registry.register_hook(HookPoint.POST_BELIEF_UPDATE, post_belief_update)
    registry.register_hook(HookPoint.PRE_DECIDE, pre_decide)
    registry.register_hook(HookPoint.POST_DECIDE, post_decide)
    registry.register_hook(HookPoint.PRE_ACT, pre_act)
    registry.register_hook(HookPoint.POST_ACT, post_act)

    pipeline, _, _ = pipeline_factory(hook_registry=registry)
    frame = np.zeros((128, 128), dtype=np.uint8)

    with patch(
        "orpheus.pipeline.parse_frame",
        return_value=FramePerception(view=View.LOBBY),
    ):
        pipeline.tick(frame)

    assert order == [
        HookPoint.PRE_PERCEPTION,
        HookPoint.POST_PERCEPTION,
        HookPoint.PRE_BELIEF_UPDATE,
        HookPoint.POST_BELIEF_UPDATE,
        HookPoint.PRE_DECIDE,
        HookPoint.POST_DECIDE,
        HookPoint.PRE_ACT,
        HookPoint.POST_ACT,
    ]


def test_pipeline_pre_perception_hook_modifies_frame(pipeline_factory) -> None:
    """Pipeline passes the pre_perception replacement frame to parse_frame."""
    registry = HookRegistry()
    original = np.zeros((128, 128), dtype=np.uint8)
    modified = np.ones((128, 128), dtype=np.uint8)

    def replace_frame(frame, belief_state: BeliefState):
        return modified

    registry.register_hook(HookPoint.PRE_PERCEPTION, replace_frame)
    pipeline, _, _ = pipeline_factory(hook_registry=registry)
    parse_mock = MagicMock(return_value=FramePerception(view=View.LOBBY))

    with patch("orpheus.pipeline.parse_frame", parse_mock):
        pipeline.tick(original)

    called_frame = parse_mock.call_args.args[0]
    assert np.array_equal(called_frame, modified)
    assert not np.array_equal(called_frame, original)


def test_mode_specific_hooks_only_fire_when_mode_active(
    pipeline_factory,
) -> None:
    """Pipeline dispatch excludes mode hooks for inactive modes."""
    registry = HookRegistry()
    fired = []
    registry.register_hook(
        HookPoint.POST_BELIEF_UPDATE,
        lambda belief_state: fired.append(True),
        modes=["other"],
    )
    pipeline, _, _ = pipeline_factory(
        hook_registry=registry,
        current_mode_name="idle",
    )
    frame = np.zeros((128, 128), dtype=np.uint8)

    with patch(
        "orpheus.pipeline.parse_frame",
        return_value=FramePerception(view=View.LOBBY),
    ):
        pipeline.tick(frame)

    assert fired == []


def test_hook_registry_isolated_between_pipelines(pipeline_factory) -> None:
    """Hooks registered on one registry do not affect another pipeline."""
    registry_a = HookRegistry()
    registry_b = HookRegistry()
    fired = []
    registry_a.register_hook(
        HookPoint.POST_BELIEF_UPDATE,
        lambda belief_state: fired.append("a"),
    )
    pipeline_a, _, _ = pipeline_factory(hook_registry=registry_a)
    pipeline_b, _, _ = pipeline_factory(hook_registry=registry_b)
    frame = np.zeros((128, 128), dtype=np.uint8)

    with patch(
        "orpheus.pipeline.parse_frame",
        return_value=FramePerception(view=View.LOBBY),
    ):
        pipeline_b.tick(frame)
        assert fired == []
        pipeline_a.tick(frame)

    assert fired == ["a"]
