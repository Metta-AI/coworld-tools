"""Unit tests for Orpheus Stage 7 async buffers and outer loop."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from orpheus.action_memory import ActionMemory
from orpheus.belief_state import BeliefState
from orpheus.buffers import BeliefBuffer
from orpheus.idle import IdleMode, IdleTask
from orpheus.mode import Mode, ModeDirective, ModeParams, ModeRegistry
from orpheus.mode_buffer import ModeBuffer
from orpheus.outer_loop import OuterLoop
from orpheus.perception.types import FramePerception
from orpheus.pipeline import Pipeline
from orpheus.task import Task
from orpheus.types import View


def _wait_until(predicate, timeout: float = 2.0) -> bool:
    """Poll a predicate until it succeeds or timeout elapses."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return predicate()


def _tick(pipeline: Pipeline) -> None:
    """Run one pipeline tick with mocked lobby perception."""
    frame = np.zeros((128, 128), dtype=np.uint8)
    with patch(
        "orpheus.pipeline.parse_frame",
        return_value=FramePerception(view=View.LOBBY),
    ):
        pipeline.tick(frame)


@dataclass(frozen=True)
class FallbackParams(ModeParams):
    """Params accepted by FallbackMode."""

    marker: int = 0


class FallbackMode(Mode):
    """Test mode that records entries and otherwise idles."""

    params_type = FallbackParams

    def select_task(self, belief_state, action_memory) -> Task | None:
        """Return a no-op task."""
        return IdleTask()

    def mode_enter(self, belief_state, action_memory) -> None:
        """Record that fallback mode was entered."""
        belief_state.extra["fallback_enters"] = (
            belief_state.extra.get("fallback_enters", 0) + 1
        )

    def mode_switch_cleanup(
        self,
        belief_state,
        action_memory,
        new_mode_directive: ModeDirective,
    ) -> None:
        """Perform no cleanup."""
        pass


@pytest.fixture
def pipeline_factory():
    """Build a Pipeline with idle and fallback modes registered."""

    def _factory(
        *,
        mode_buffer: ModeBuffer | None = None,
        belief_buffer: BeliefBuffer | None = None,
        fallback_directive: ModeDirective | None = None,
        watchdog_threshold: int = 120,
        logger=None,
    ):
        send_input = MagicMock()
        send_chat = MagicMock()
        registry = ModeRegistry()
        registry.register("idle", IdleMode)
        registry.register("fallback_mode", FallbackMode)
        pipeline = Pipeline(
            initial_mode=IdleMode(),
            mode_registry=registry,
            send_input=send_input,
            send_chat=send_chat,
            mode_buffer=mode_buffer,
            belief_buffer=belief_buffer,
            fallback_directive=fallback_directive,
            watchdog_threshold=watchdog_threshold,
            logger=logger,
        )
        return pipeline, registry, send_input, send_chat

    return _factory


def test_belief_buffer_push_consume_blocking() -> None:
    """Pushed snapshots can be consumed once via the blocking API."""
    buffer = BeliefBuffer()
    belief_state = BeliefState(tick=7)
    action_memory = ActionMemory()

    buffer.push(belief_state, action_memory)

    snapshot = buffer.consume_blocking()
    assert snapshot is not None
    consumed_belief, consumed_memory = snapshot
    assert consumed_belief.tick == 7
    assert isinstance(consumed_memory, ActionMemory)
    assert buffer.consume_blocking(timeout=0.01) is None


def test_belief_buffer_overwrite_unconsumed() -> None:
    """The latest push wins when an older snapshot is still unconsumed."""
    buffer = BeliefBuffer()

    buffer.push(BeliefState(tick=1), ActionMemory())
    buffer.push(BeliefState(tick=2), ActionMemory())

    snapshot = buffer.consume_blocking(timeout=0.01)
    assert snapshot is not None
    belief_state, _ = snapshot
    assert belief_state.tick == 2
    assert buffer.try_consume() is None


def test_belief_buffer_consume_blocking_timeout() -> None:
    """Blocking consume returns None when no snapshot arrives before timeout."""
    assert BeliefBuffer().consume_blocking(timeout=0.05) is None


def test_belief_buffer_deep_copies_on_push() -> None:
    """Mutating the original state after push does not affect the snapshot."""
    buffer = BeliefBuffer()
    belief_state = BeliefState(tick=1)
    belief_state.extra["items"] = ["before"]
    action_memory = ActionMemory()
    action_memory.notes = ["before"]

    buffer.push(belief_state, action_memory)
    belief_state.extra["items"].append("after")
    action_memory.notes.append("after")

    snapshot = buffer.consume_blocking(timeout=0.01)
    assert snapshot is not None
    consumed_belief, consumed_memory = snapshot
    assert consumed_belief.extra["items"] == ["before"]
    assert consumed_memory.notes == ["before"]


def test_belief_buffer_thread_safety_basic() -> None:
    """A producer and blocking consumer can run concurrently without errors."""
    buffer = BeliefBuffer()
    stop = threading.Event()
    exceptions: list[BaseException] = []
    received: list[int] = []

    def producer() -> None:
        try:
            tick = 0
            while not stop.is_set():
                buffer.push(BeliefState(tick=tick), ActionMemory())
                tick += 1
                stop.wait(0.005)
        except BaseException as exc:
            exceptions.append(exc)

    def consumer() -> None:
        try:
            while not stop.is_set():
                snapshot = buffer.consume_blocking(timeout=0.05)
                if snapshot is not None:
                    belief_state, _ = snapshot
                    received.append(belief_state.tick)
        except BaseException as exc:
            exceptions.append(exc)

    threads = [
        threading.Thread(target=producer),
        threading.Thread(target=consumer),
    ]
    for thread in threads:
        thread.start()
    try:
        assert _wait_until(lambda: bool(received))
    finally:
        stop.set()
        for thread in threads:
            thread.join(timeout=1.0)

    assert exceptions == []
    assert received


def test_mode_buffer_thread_safety() -> None:
    """A producer and non-blocking consumer can share ModeBuffer safely."""
    buffer = ModeBuffer()
    stop = threading.Event()
    exceptions: list[BaseException] = []
    received: list[str] = []

    def producer() -> None:
        try:
            while not stop.is_set():
                buffer.push(ModeDirective(mode="idle", params=ModeParams()))
                stop.wait(0.005)
        except BaseException as exc:
            exceptions.append(exc)

    def consumer() -> None:
        try:
            while not stop.is_set():
                entry = buffer.consume()
                if entry is not None:
                    directive, _ = entry
                    received.append(directive.mode)
                stop.wait(0.005)
        except BaseException as exc:
            exceptions.append(exc)

    threads = [
        threading.Thread(target=producer),
        threading.Thread(target=consumer),
    ]
    for thread in threads:
        thread.start()
    try:
        assert _wait_until(lambda: bool(received))
    finally:
        stop.set()
        for thread in threads:
            thread.join(timeout=1.0)

    assert exceptions == []
    assert received


def test_mode_buffer_existing_api_unchanged() -> None:
    """ModeBuffer push, consume, and has_entry preserve Stage 6 semantics."""
    buffer = ModeBuffer()
    first = ModeDirective(mode="first", params=ModeParams())
    second = ModeDirective(mode="second", params=ModeParams())

    assert buffer.has_entry() is False
    assert buffer.consume() is None
    buffer.push(first, {"old": 1})
    assert buffer.has_entry() is True
    buffer.push(second, {"new": 2})
    assert buffer.consume() == (second, {"new": 2})
    assert buffer.has_entry() is False
    assert buffer.consume() is None


def test_outer_loop_calls_meta_decide() -> None:
    """OuterLoop consumes belief snapshots and calls meta_decide."""
    belief_buffer = BeliefBuffer()
    mode_buffer = ModeBuffer()
    called = threading.Event()

    def meta_decide(belief_state, action_memory):
        called.set()
        return ModeDirective(mode="idle", params=ModeParams()), None

    outer_loop = OuterLoop(meta_decide, belief_buffer, mode_buffer)
    outer_loop.start()
    try:
        belief_buffer.push(BeliefState(), ActionMemory())
        assert called.wait(timeout=0.5)
    finally:
        outer_loop.stop()


def test_outer_loop_pushes_to_mode_buffer() -> None:
    """OuterLoop writes meta_decide's directive to the mode buffer."""
    belief_buffer = BeliefBuffer()
    mode_buffer = ModeBuffer()
    directive = ModeDirective(mode="fallback_mode", params=FallbackParams())

    def meta_decide(belief_state, action_memory):
        return directive, {"score": 1}

    outer_loop = OuterLoop(meta_decide, belief_buffer, mode_buffer)
    outer_loop.start()
    try:
        belief_buffer.push(BeliefState(), ActionMemory())
        assert _wait_until(mode_buffer.has_entry)
    finally:
        outer_loop.stop()

    assert mode_buffer.consume() == (directive, {"score": 1})


def test_outer_loop_meta_decide_exception_does_not_kill_loop() -> None:
    """A meta_decide failure is logged/skipped and the loop handles later input."""
    belief_buffer = BeliefBuffer()
    mode_buffer = ModeBuffer()
    first_called = threading.Event()
    second_called = threading.Event()
    calls = 0

    def meta_decide(belief_state, action_memory):
        nonlocal calls
        calls += 1
        if calls == 1:
            first_called.set()
            raise RuntimeError("first boom")
        second_called.set()
        return ModeDirective(mode="idle", params=ModeParams()), None

    outer_loop = OuterLoop(meta_decide, belief_buffer, mode_buffer)
    outer_loop.start()
    try:
        belief_buffer.push(BeliefState(tick=1), ActionMemory())
        assert first_called.wait(timeout=0.5)
        belief_buffer.push(BeliefState(tick=2), ActionMemory())
        assert second_called.wait(timeout=0.5)
    finally:
        outer_loop.stop()

    assert calls == 2


def test_outer_loop_stop_terminates_thread() -> None:
    """stop() signals the background thread and waits for it to exit."""
    outer_loop = OuterLoop(
        lambda belief_state, action_memory: (
            ModeDirective(mode="idle", params=ModeParams()),
            None,
        ),
        BeliefBuffer(),
        ModeBuffer(),
    )

    outer_loop.start()
    outer_loop.stop(timeout=1.0)

    assert outer_loop._thread is not None
    assert outer_loop._thread.is_alive() is False


def test_outer_loop_logs_meta_decide_exceptions() -> None:
    """meta_decide exceptions are logged without terminating the loop."""
    logs: list[str] = []
    belief_buffer = BeliefBuffer()

    def meta_decide(belief_state, action_memory):
        raise ValueError("bad strategy")

    outer_loop = OuterLoop(meta_decide, belief_buffer, ModeBuffer(), logger=logs.append)
    outer_loop.start()
    try:
        belief_buffer.push(BeliefState(), ActionMemory())
        assert _wait_until(
            lambda: any("meta_decide_failed" in message for message in logs)
        )
    finally:
        outer_loop.stop()


def test_pipeline_pushes_belief_to_buffer_each_tick(pipeline_factory) -> None:
    """Pipeline writes a belief/action snapshot after belief update each tick."""
    belief_buffer = BeliefBuffer()
    pipeline, _, _, _ = pipeline_factory(belief_buffer=belief_buffer)

    _tick(pipeline)

    snapshot = belief_buffer.try_consume()
    assert snapshot is not None
    belief_state, action_memory = snapshot
    assert belief_state.tick == 1
    assert isinstance(action_memory, ActionMemory)


def test_pipeline_belief_buffer_snapshot_is_deep_copy(pipeline_factory) -> None:
    """Buffered pipeline snapshots are isolated from later live mutations."""
    belief_buffer = BeliefBuffer()
    pipeline, _, _, _ = pipeline_factory(belief_buffer=belief_buffer)

    _tick(pipeline)
    pipeline.belief_state.extra["live_only"] = True

    snapshot = belief_buffer.try_consume()
    assert snapshot is not None
    belief_state, _ = snapshot
    assert "live_only" not in belief_state.extra


def test_watchdog_fires_after_threshold_ticks(pipeline_factory) -> None:
    """A directive drought switches to the configured fallback mode."""
    fallback = ModeDirective(mode="fallback_mode", params=FallbackParams())
    pipeline, _, _, _ = pipeline_factory(
        fallback_directive=fallback,
        watchdog_threshold=5,
    )

    for _ in range(5):
        _tick(pipeline)

    assert pipeline.current_mode_name == "fallback_mode"


def test_watchdog_does_not_fire_when_directives_arrive(pipeline_factory) -> None:
    """Reaffirmation directives reset the watchdog liveness counter."""
    mode_buffer = ModeBuffer()
    pipeline, _, _, _ = pipeline_factory(
        mode_buffer=mode_buffer,
        fallback_directive=ModeDirective(
            mode="fallback_mode",
            params=FallbackParams(),
        ),
        watchdog_threshold=3,
    )

    for _ in range(10):
        mode_buffer.push(ModeDirective(mode="idle", params=ModeParams()))
        _tick(pipeline)

    assert pipeline.current_mode_name == "idle"
    assert pipeline._watchdog_fired is False
    assert pipeline.ticks_since_last_mode_directive == 0


def test_watchdog_fires_only_once_per_drought(pipeline_factory) -> None:
    """Watchdog fires once per drought, then can fire again after real output."""
    logs: list[str] = []
    mode_buffer = ModeBuffer()
    fallback = ModeDirective(mode="fallback_mode", params=FallbackParams())
    pipeline, _, _, _ = pipeline_factory(
        mode_buffer=mode_buffer,
        fallback_directive=fallback,
        watchdog_threshold=3,
        logger=logs.append,
    )

    for _ in range(10):
        _tick(pipeline)

    assert pipeline.current_mode_name == "fallback_mode"
    assert pipeline.belief_state.extra["fallback_enters"] == 1
    assert sum("watchdog_fired" in message for message in logs) == 1

    mode_buffer.push(ModeDirective(mode="idle", params=ModeParams()))
    _tick(pipeline)
    assert pipeline.current_mode_name == "idle"
    assert pipeline._watchdog_fired is False

    for _ in range(3):
        _tick(pipeline)

    assert pipeline.current_mode_name == "fallback_mode"
    assert pipeline.belief_state.extra["fallback_enters"] == 2
    assert sum("watchdog_fired" in message for message in logs) == 2


def test_watchdog_default_fallback_reaffirms_current_mode(pipeline_factory) -> None:
    """Without an explicit fallback, watchdog reaffirms the current mode."""
    pipeline, _, _, _ = pipeline_factory(watchdog_threshold=3)

    for _ in range(3):
        _tick(pipeline)

    assert pipeline.current_mode_name == "idle"
    assert pipeline._watchdog_fired is True
    assert pipeline.ticks_since_last_mode_directive == 0

    for _ in range(2):
        _tick(pipeline)

    assert pipeline.current_mode_name == "idle"
    assert pipeline._watchdog_fired is True
    assert pipeline.ticks_since_last_mode_directive == 2


def test_outer_loop_pipeline_round_trip(pipeline_factory) -> None:
    """Real OuterLoop and Pipeline exchange snapshots and directives."""
    belief_buffer = BeliefBuffer()
    mode_buffer = ModeBuffer()
    directive = ModeDirective(mode="fallback_mode", params=FallbackParams())
    pipeline, _, _, _ = pipeline_factory(
        mode_buffer=mode_buffer,
        belief_buffer=belief_buffer,
        watchdog_threshold=999,
    )

    def meta_decide(belief_state, action_memory):
        return directive, None

    outer_loop = OuterLoop(meta_decide, belief_buffer, mode_buffer)
    outer_loop.start()
    try:
        for _ in range(3):
            _tick(pipeline)
        assert _wait_until(
            lambda: mode_buffer.has_entry() or pipeline.current_mode_name == "fallback_mode",
        )
        def consumed_fallback_directive() -> bool:
            if pipeline.current_mode_name == "fallback_mode":
                return True
            _tick(pipeline)
            return pipeline.current_mode_name == "fallback_mode"

        assert _wait_until(consumed_fallback_directive)
    finally:
        outer_loop.stop()
