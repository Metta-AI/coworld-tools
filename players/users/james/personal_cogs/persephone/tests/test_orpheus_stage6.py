"""Unit tests for the Orpheus Stage 6 mode-switch lifecycle."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from orpheus.action_memory import ActionMemory
from orpheus.belief_state import BeliefState
from orpheus.hooks import HookRegistry
from orpheus.idle import IdleMode, IdleTask
from orpheus.mode import Mode, ModeDirective, ModeParams, ModeRegistry
from orpheus.mode_buffer import ModeBuffer
from orpheus.perception.types import FramePerception
from orpheus.pipeline import Pipeline
from orpheus.task import Task
from orpheus.types import View


def _tick(pipeline: Pipeline) -> None:
    """Run one pipeline tick with mocked lobby perception."""
    frame = np.zeros((128, 128), dtype=np.uint8)
    with patch(
        "orpheus.pipeline.parse_frame",
        return_value=FramePerception(view=View.LOBBY),
    ):
        pipeline.tick(frame)


class SimpleMode(Mode):
    """Mode that always selects IdleTask."""

    params_type = ModeParams

    def select_task(self, belief_state, action_memory) -> Task | None:
        """Return a no-op task."""
        return IdleTask()

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


@dataclass(frozen=True)
class KnownParams(ModeParams):
    """Params accepted by KnownParamsMode."""

    value: int = 0


@dataclass(frozen=True)
class OtherParams(ModeParams):
    """Params intentionally unrelated to KnownParams."""

    value: int = 0


class KnownParamsMode(SimpleMode):
    """Simple mode with a non-default params type."""

    params_type = KnownParams


@pytest.fixture
def pipeline_factory():
    """Build a Pipeline with mocked transports, idle registered, and optional modes."""

    def _factory(
        mode: Mode | None = None,
        hook_registry: HookRegistry | None = None,
        current_mode_name: str = "idle",
        mode_buffer: ModeBuffer | None = None,
        logger: Callable[[str], None] | None = None,
        registered_modes: dict[str, type[Mode]] | None = None,
    ):
        send_input = MagicMock()
        send_chat = MagicMock()
        registry = ModeRegistry()
        registry.register("idle", IdleMode)
        if registered_modes is not None:
            for name, mode_cls in registered_modes.items():
                registry.register(name, mode_cls)
        pipeline = Pipeline(
            initial_mode=mode if mode is not None else IdleMode(),
            mode_registry=registry,
            send_input=send_input,
            send_chat=send_chat,
            hook_registry=hook_registry,
            current_mode_name=current_mode_name,
            mode_buffer=mode_buffer,
            logger=logger,
        )
        return pipeline, registry, send_input, send_chat

    return _factory


def test_mode_buffer_push_consume() -> None:
    """ModeBuffer tracks entries and consumes exactly once."""
    buffer = ModeBuffer()
    directive = ModeDirective(mode="idle", params=ModeParams())

    buffer.push(directive, {"x": 1})

    assert buffer.has_entry() is True
    assert buffer.consume() == (directive, {"x": 1})
    assert buffer.has_entry() is False


def test_mode_buffer_overwrites_unconsumed() -> None:
    """Pushing twice leaves only the latest unconsumed directive."""
    buffer = ModeBuffer()
    first = ModeDirective(mode="first", params=ModeParams())
    second = ModeDirective(mode="second", params=ModeParams())

    buffer.push(first, {"old": 1})
    buffer.push(second, {"new": 2})

    assert buffer.consume() == (second, {"new": 2})
    assert buffer.consume() is None


def test_mode_buffer_consume_empty() -> None:
    """Consuming an empty ModeBuffer returns None."""
    assert ModeBuffer().consume() is None


def test_pipeline_no_buffer_entry_keeps_current_mode(pipeline_factory) -> None:
    """A tick with no pending directive keeps the active mode unchanged."""
    initial = IdleMode()
    pipeline, _, _, _ = pipeline_factory(mode=initial)

    _tick(pipeline)

    assert pipeline.current_mode is initial
    assert pipeline.current_mode_name == "idle"


def test_pipeline_consumes_buffer_and_switches_mode(pipeline_factory) -> None:
    """A valid buffered directive activates the registered target mode."""
    buffer = ModeBuffer()
    buffer.push(ModeDirective(mode="test_mode", params=ModeParams()))
    pipeline, _, _, _ = pipeline_factory(
        mode_buffer=buffer,
        registered_modes={"test_mode": SimpleMode},
    )

    _tick(pipeline)

    assert pipeline.current_mode_name == "test_mode"
    assert isinstance(pipeline.current_mode, SimpleMode)
    assert buffer.has_entry() is False


def test_mode_switch_calls_cleanup_then_enter(pipeline_factory) -> None:
    """Mode switching runs old cleanup before new enter with the final directive."""
    events = []
    directive = ModeDirective(mode="new_mode", params=ModeParams())

    class OldMode(SimpleMode):
        """Departing mode that records cleanup."""

        def mode_switch_cleanup(
            self,
            belief_state,
            action_memory,
            new_mode_directive: ModeDirective,
        ) -> None:
            events.append(("cleanup", new_mode_directive))

    class NewMode(SimpleMode):
        """Entering mode that records entry."""

        def mode_enter(self, belief_state, action_memory) -> None:
            events.append(("enter", belief_state.tick))

    buffer = ModeBuffer()
    buffer.push(directive)
    pipeline, _, _, _ = pipeline_factory(
        mode=OldMode(),
        current_mode_name="old_mode",
        mode_buffer=buffer,
        registered_modes={"old_mode": OldMode, "new_mode": NewMode},
    )

    _tick(pipeline)

    assert events == [("cleanup", directive), ("enter", 1)]
    assert isinstance(pipeline.current_mode, NewMode)


def test_mode_switch_does_not_clear_action_memory(pipeline_factory) -> None:
    """Mode switching preserves ActionMemory when the selected task is unchanged."""
    buffer = ModeBuffer()
    buffer.push(ModeDirective(mode="new_mode", params=ModeParams()))
    pipeline, _, _, _ = pipeline_factory(
        mode_buffer=buffer,
        registered_modes={"new_mode": SimpleMode},
    )
    pipeline.current_task = IdleTask()
    pipeline.action_memory.ticks_active = 5

    _tick(pipeline)

    assert pipeline.action_memory.ticks_active >= 5
    assert pipeline.action_memory.ticks_active == 6


def test_invalid_directive_mode_unknown(pipeline_factory) -> None:
    """Unknown target modes are rejected and logged."""
    messages = []
    buffer = ModeBuffer()
    buffer.push(ModeDirective(mode="not_registered", params=ModeParams()))
    initial = IdleMode()
    pipeline, _, _, _ = pipeline_factory(
        mode=initial,
        mode_buffer=buffer,
        logger=messages.append,
    )

    _tick(pipeline)

    assert pipeline.current_mode is initial
    assert pipeline.current_mode_name == "idle"
    assert any("invalid_directive" in message for message in messages)


def test_invalid_directive_params_wrong_type(pipeline_factory) -> None:
    """Directives with params that do not match the target mode are rejected."""
    messages = []
    buffer = ModeBuffer()
    buffer.push(ModeDirective(mode="known", params=OtherParams(1)))
    initial = IdleMode()
    pipeline, _, _, _ = pipeline_factory(
        mode=initial,
        mode_buffer=buffer,
        logger=messages.append,
        registered_modes={"known": KnownParamsMode},
    )

    _tick(pipeline)

    assert pipeline.current_mode is initial
    assert pipeline.current_mode_name == "idle"
    assert any("invalid_directive" in message for message in messages)


def test_directive_reaffirmation_is_noop(pipeline_factory) -> None:
    """A directive matching the current mode and params skips cleanup and enter."""
    calls = []

    class SentinelMode(SimpleMode):
        """Mode that records lifecycle calls."""

        def mode_enter(self, belief_state, action_memory) -> None:
            calls.append("enter")

        def mode_switch_cleanup(
            self,
            belief_state,
            action_memory,
            new_mode_directive: ModeDirective,
        ) -> None:
            calls.append("cleanup")

    initial = SentinelMode()
    buffer = ModeBuffer()
    buffer.push(ModeDirective(mode="sentinel", params=initial.params))
    pipeline, _, _, _ = pipeline_factory(
        mode=initial,
        current_mode_name="sentinel",
        mode_buffer=buffer,
        registered_modes={"sentinel": SentinelMode},
    )

    _tick(pipeline)

    assert pipeline.current_mode is initial
    assert calls == []


def test_inferences_replaced_wholesale(pipeline_factory) -> None:
    """Non-None buffered inferences replace the belief namespace wholesale."""
    buffer = ModeBuffer()
    buffer.push(
        ModeDirective(mode="idle", params=ModeParams()),
        inferences={"new": 2},
    )
    pipeline, _, _, _ = pipeline_factory(mode_buffer=buffer)
    pipeline.belief_state.inferences = {"old": 1}

    _tick(pipeline)

    assert pipeline.belief_state.inferences == {"new": 2}


def test_inferences_none_leaves_unchanged(pipeline_factory) -> None:
    """A None inference payload leaves existing inferences untouched."""
    buffer = ModeBuffer()
    buffer.push(ModeDirective(mode="idle", params=ModeParams()), inferences=None)
    pipeline, _, _, _ = pipeline_factory(mode_buffer=buffer)
    pipeline.belief_state.inferences = {"old": 1}

    _tick(pipeline)

    assert pipeline.belief_state.inferences == {"old": 1}


def test_mode_switch_callback_can_mutate_belief_state(pipeline_factory) -> None:
    """Mode-switch callbacks can mutate the live belief state."""
    hooks = HookRegistry()

    def callback(
        belief_state: BeliefState,
        action_memory: ActionMemory,
        directive: ModeDirective,
    ) -> None:
        belief_state.inferences["x"] = 1

    hooks.register_mode_switch_callback(callback)
    buffer = ModeBuffer()
    buffer.push(ModeDirective(mode="test_mode", params=ModeParams()))
    pipeline, _, _, _ = pipeline_factory(
        hook_registry=hooks,
        mode_buffer=buffer,
        registered_modes={"test_mode": SimpleMode},
    )

    _tick(pipeline)

    assert pipeline.belief_state.inferences["x"] == 1


def test_mode_switch_callback_can_override_directive(pipeline_factory) -> None:
    """A valid callback override replaces the consumed directive."""
    hooks = HookRegistry()

    def callback(
        belief_state: BeliefState,
        action_memory: ActionMemory,
        directive: ModeDirective,
    ) -> ModeDirective:
        return ModeDirective(mode="mode_b", params=ModeParams())

    hooks.register_mode_switch_callback(callback)
    buffer = ModeBuffer()
    buffer.push(ModeDirective(mode="mode_a", params=ModeParams()))
    pipeline, _, _, _ = pipeline_factory(
        hook_registry=hooks,
        mode_buffer=buffer,
        registered_modes={"mode_a": SimpleMode, "mode_b": SimpleMode},
    )

    _tick(pipeline)

    assert pipeline.current_mode_name == "mode_b"


def test_mode_switch_callback_invalid_override_is_discarded(
    pipeline_factory,
) -> None:
    """Invalid callback overrides are logged and the previous directive proceeds."""
    messages = []
    hooks = HookRegistry()

    def callback(
        belief_state: BeliefState,
        action_memory: ActionMemory,
        directive: ModeDirective,
    ) -> ModeDirective:
        return ModeDirective(mode="missing", params=ModeParams())

    hooks.register_mode_switch_callback(callback)
    buffer = ModeBuffer()
    buffer.push(ModeDirective(mode="mode_a", params=ModeParams()))
    pipeline, _, _, _ = pipeline_factory(
        hook_registry=hooks,
        mode_buffer=buffer,
        logger=messages.append,
        registered_modes={"mode_a": SimpleMode},
    )

    _tick(pipeline)

    assert pipeline.current_mode_name == "mode_a"
    assert any("invalid_mode_switch_override" in message for message in messages)


def test_agent_callbacks_fire_before_mode_callbacks(pipeline_factory) -> None:
    """Mode-switch callbacks preserve agent-then-departing-mode order."""
    order = []
    hooks = HookRegistry()
    hooks.register_mode_switch_callback(
        lambda belief_state, action_memory, directive: order.append("agent")
    )
    hooks.register_mode_switch_callback(
        lambda belief_state, action_memory, directive: order.append("mode"),
        modes=["idle"],
    )
    buffer = ModeBuffer()
    buffer.push(ModeDirective(mode="mode_a", params=ModeParams()))
    pipeline, _, _, _ = pipeline_factory(
        hook_registry=hooks,
        mode_buffer=buffer,
        registered_modes={"mode_a": SimpleMode},
    )

    _tick(pipeline)

    assert order == ["agent", "mode"]


def test_mode_callbacks_only_fire_for_active_mode(pipeline_factory) -> None:
    """Mode-scoped callbacks fire only when departing their registered mode."""
    fired = []
    hooks = HookRegistry()
    hooks.register_mode_switch_callback(
        lambda belief_state, action_memory, directive: fired.append(True),
        modes=["mode_b"],
    )
    buffer = ModeBuffer()
    buffer.push(ModeDirective(mode="mode_a", params=ModeParams()))
    pipeline, _, _, _ = pipeline_factory(
        hook_registry=hooks,
        mode_buffer=buffer,
        registered_modes={"mode_a": SimpleMode, "mode_b": SimpleMode},
    )

    _tick(pipeline)

    assert fired == []
    assert pipeline.current_mode_name == "mode_a"


def test_callback_exception_rolls_back_belief_state(pipeline_factory) -> None:
    """A crashing mode-switch callback restores belief fields from its snapshot."""
    hooks = HookRegistry()

    def callback(
        belief_state: BeliefState,
        action_memory: ActionMemory,
        directive: ModeDirective,
    ) -> None:
        belief_state.tick = 999
        belief_state.inferences["bad"] = True
        raise RuntimeError("boom")

    hooks.register_mode_switch_callback(callback)
    buffer = ModeBuffer()
    buffer.push(ModeDirective(mode="mode_a", params=ModeParams()))
    pipeline, _, _, _ = pipeline_factory(
        hook_registry=hooks,
        mode_buffer=buffer,
        registered_modes={"mode_a": SimpleMode},
    )

    _tick(pipeline)

    assert pipeline.belief_state.tick == 1
    assert pipeline.belief_state.inferences == {}
    assert pipeline.current_mode_name == "mode_a"


def test_callback_exception_does_not_halt_switch(pipeline_factory) -> None:
    """Dispatch continues after a crashing mode-switch callback."""
    seen = []
    hooks = HookRegistry()

    def crashing(
        belief_state: BeliefState,
        action_memory: ActionMemory,
        directive: ModeDirective,
    ) -> None:
        belief_state.tick = 999
        raise RuntimeError("boom")

    def normal(
        belief_state: BeliefState,
        action_memory: ActionMemory,
        directive: ModeDirective,
    ) -> None:
        seen.append((belief_state.tick, directive.mode))

    hooks.register_mode_switch_callback(crashing)
    hooks.register_mode_switch_callback(normal)
    buffer = ModeBuffer()
    buffer.push(ModeDirective(mode="mode_a", params=ModeParams()))
    pipeline, _, _, _ = pipeline_factory(
        hook_registry=hooks,
        mode_buffer=buffer,
        registered_modes={"mode_a": SimpleMode},
    )

    _tick(pipeline)

    assert seen == [(1, "mode_a")]
    assert pipeline.current_mode_name == "mode_a"
