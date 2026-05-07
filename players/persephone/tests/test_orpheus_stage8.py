"""Unit tests for Orpheus Stage 8 structured logging."""

from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from orpheus.action_memory import ActionMemory
from orpheus.belief_state import BeliefState
from orpheus.buffers import BeliefBuffer
from orpheus.hooks import HookPoint, HookRegistry
from orpheus.idle import IdleMode, IdleTask
from orpheus.logging import LogLevel, Logger, log_event
from orpheus.mode import Mode, ModeDirective, ModeParams, ModeRegistry
from orpheus.mode_buffer import ModeBuffer
from orpheus.outer_loop import OuterLoop
from orpheus.perception.types import FramePerception
from orpheus.pipeline import Pipeline
from orpheus.task import ActCommand, Task
from orpheus.types import View


def _entries(lines: list[str]) -> list[dict]:
    return [json.loads(line) for line in lines]


def _entry(lines: list[str], event_type: str) -> dict:
    for entry in _entries(lines):
        if entry.get("type") == event_type:
            return entry
    raise AssertionError(f"missing log entry type {event_type!r}: {lines!r}")


def _entries_of_type(lines: list[str], event_type: str) -> list[dict]:
    return [entry for entry in _entries(lines) if entry.get("type") == event_type]


def _wait_until(predicate, timeout: float = 0.5) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return predicate()


def _tick(pipeline: Pipeline, view: View = View.LOBBY) -> ActCommand:
    frame = np.zeros((128, 128), dtype=np.uint8)
    with patch(
        "orpheus.pipeline.parse_frame",
        return_value=FramePerception(view=view),
    ):
        return pipeline.tick(frame)


class SimpleMode(Mode):
    params_type = ModeParams

    def select_task(self, belief_state, action_memory) -> Task | None:
        return IdleTask()

    def mode_enter(self, belief_state, action_memory) -> None:
        pass

    def mode_switch_cleanup(
        self,
        belief_state,
        action_memory,
        new_mode_directive: ModeDirective,
    ) -> None:
        pass


@dataclass(frozen=True)
class FallbackParams(ModeParams):
    marker: int = 0


class FallbackMode(SimpleMode):
    params_type = FallbackParams


@pytest.fixture
def pipeline_factory():
    def _factory(
        *,
        logger=None,
        mode_buffer: ModeBuffer | None = None,
        fallback_directive: ModeDirective | None = None,
        watchdog_threshold: int = 120,
        hook_registry: HookRegistry | None = None,
    ):
        registry = ModeRegistry()
        registry.register("idle", IdleMode)
        registry.register("simple", SimpleMode)
        registry.register("fallback_mode", FallbackMode)
        pipeline = Pipeline(
            initial_mode=IdleMode(),
            mode_registry=registry,
            send_input=MagicMock(),
            send_chat=MagicMock(),
            mode_buffer=mode_buffer,
            fallback_directive=fallback_directive,
            watchdog_threshold=watchdog_threshold,
            hook_registry=hook_registry,
            logger=logger,
        )
        return pipeline

    return _factory


def test_log_levels_ordering() -> None:
    assert LogLevel.OFF < LogLevel.EVENTS < LogLevel.DECISIONS < LogLevel.VERBOSE


def test_logger_off_emits_nothing() -> None:
    lines: list[str] = []
    logger = Logger(level=LogLevel.OFF, sink=lines.append)

    logger.event("mode_transition", {"old": "idle", "new": "hunt"})

    assert lines == []


def test_logger_events_emits_only_events_level() -> None:
    lines: list[str] = []
    logger = Logger(level=LogLevel.EVENTS, sink=lines.append)

    logger.event("event", {})
    logger.event("decision", {}, level=LogLevel.DECISIONS)
    logger.event("verbose", {}, level=LogLevel.VERBOSE)

    assert [entry["type"] for entry in _entries(lines)] == ["event"]


def test_logger_decisions_emits_events_and_decisions() -> None:
    lines: list[str] = []
    logger = Logger(level=LogLevel.DECISIONS, sink=lines.append)

    logger.event("event", {})
    logger.event("decision", {}, level=LogLevel.DECISIONS)
    logger.event("verbose", {}, level=LogLevel.VERBOSE)

    assert [entry["type"] for entry in _entries(lines)] == ["event", "decision"]


def test_logger_verbose_emits_all() -> None:
    lines: list[str] = []
    logger = Logger(level=LogLevel.VERBOSE, sink=lines.append)

    logger.event("event", {})
    logger.event("decision", {}, level=LogLevel.DECISIONS)
    logger.event("verbose", {}, level=LogLevel.VERBOSE)

    assert [entry["type"] for entry in _entries(lines)] == [
        "event",
        "decision",
        "verbose",
    ]


def test_logger_jsonl_format() -> None:
    lines: list[str] = []
    logger = Logger(level=LogLevel.EVENTS, sink=lines.append, clock=lambda: 12.5)

    logger.event("mode_transition", {"old": "idle", "new": "simple"})

    assert len(lines) == 1
    assert lines[0].endswith("\n")
    entry = json.loads(lines[0])
    for key in {"tick", "wall_clock", "mode", "task", "view", "level", "type"}:
        assert key in entry
    assert entry["wall_clock"] == 12.5
    assert entry["type"] == "mode_transition"


def test_logger_metadata_in_every_entry() -> None:
    lines: list[str] = []
    logger = Logger(level=LogLevel.EVENTS, sink=lines.append)
    logger.update_metadata(tick=4, mode="idle", task="IdleTask", view="lobby")

    logger.event("task_change", {"old": None, "new": "IdleTask"})

    entry = _entries(lines)[0]
    assert entry["tick"] == 4
    assert entry["mode"] == "idle"
    assert entry["task"] == "IdleTask"
    assert entry["view"] == "lobby"


def test_logger_callable_compat() -> None:
    lines: list[str] = []
    logger = Logger(level=LogLevel.EVENTS, sink=lines.append)

    logger("hello")

    entry = _entries(lines)[0]
    assert entry["type"] == "raw"
    assert entry["message"] == "hello"


def test_logger_default_str_handles_dataclasses() -> None:
    @dataclass
    class Payload:
        value: int

    lines: list[str] = []
    logger = Logger(level=LogLevel.EVENTS, sink=lines.append)

    logger.event("payload", {"payload": Payload(3)})

    entry = _entries(lines)[0]
    assert "Payload(value=3)" in entry["payload"]


def test_pipeline_emits_view_transition_event(pipeline_factory) -> None:
    lines: list[str] = []
    pipeline = pipeline_factory(logger=Logger(sink=lines.append))

    _tick(pipeline, View.LOBBY)
    _tick(pipeline, View.PLAYING)

    transitions = _entries_of_type(lines, "view_transition")
    assert any(
        entry["old"] == "lobby" and entry["new"] == "playing"
        for entry in transitions
    )


def test_pipeline_emits_task_change_event(pipeline_factory) -> None:
    lines: list[str] = []
    pipeline = pipeline_factory(logger=Logger(sink=lines.append))

    _tick(pipeline)

    entry = _entry(lines, "task_change")
    assert entry["old"] is None
    assert entry["new"] == "IdleTask"


def test_pipeline_emits_mode_transition_event(pipeline_factory) -> None:
    lines: list[str] = []
    buffer = ModeBuffer()
    buffer.push(ModeDirective(mode="simple", params=ModeParams()))
    pipeline = pipeline_factory(
        logger=Logger(sink=lines.append),
        mode_buffer=buffer,
    )

    _tick(pipeline)

    entry = _entry(lines, "mode_transition")
    assert entry["old"] == "idle"
    assert entry["new"] == "simple"
    assert "ModeDirective" in entry["directive"]


def test_pipeline_emits_watchdog_activation_event(pipeline_factory) -> None:
    lines: list[str] = []
    fallback = ModeDirective(mode="fallback_mode", params=FallbackParams())
    pipeline = pipeline_factory(
        logger=Logger(sink=lines.append),
        fallback_directive=fallback,
        watchdog_threshold=1,
    )

    _tick(pipeline)

    entry = _entry(lines, "watchdog_activation")
    assert entry["fallback_mode"] == "fallback_mode"
    assert entry["reason"] == "directive_timeout"


def test_pipeline_decisions_level_emits_select_task(pipeline_factory) -> None:
    lines: list[str] = []
    pipeline = pipeline_factory(logger=Logger(level=LogLevel.DECISIONS, sink=lines.append))

    _tick(pipeline)

    entry = _entry(lines, "select_task")
    assert entry["task_type"] == "IdleTask"
    assert entry["level"] == "decisions"


def test_pipeline_verbose_level_emits_act_command(pipeline_factory) -> None:
    lines: list[str] = []
    pipeline = pipeline_factory(logger=Logger(level=LogLevel.VERBOSE, sink=lines.append))

    _tick(pipeline)

    entry = _entry(lines, "act_command")
    assert entry["level"] == "verbose"
    assert "ActCommand" in entry["command"]


def test_pipeline_verbose_level_emits_perception(pipeline_factory) -> None:
    lines: list[str] = []
    pipeline = pipeline_factory(logger=Logger(level=LogLevel.VERBOSE, sink=lines.append))

    _tick(pipeline)

    entry = _entry(lines, "perception")
    assert entry["level"] == "verbose"
    assert "FramePerception" in entry["perception"]


def test_outer_loop_emits_outer_loop_cycle_event() -> None:
    lines: list[str] = []
    belief_buffer = BeliefBuffer()
    mode_buffer = ModeBuffer()
    directive = ModeDirective(mode="idle", params=ModeParams())

    def meta_decide(belief_state, action_memory):
        return directive, {"ok": True}

    outer_loop = OuterLoop(
        meta_decide,
        belief_buffer,
        mode_buffer,
        logger=Logger(sink=lines.append),
    )
    outer_loop.start()
    try:
        belief_buffer.push(BeliefState(tick=7), ActionMemory())
        assert _wait_until(lambda: any('"type": "outer_loop_cycle"' in line for line in lines))
    finally:
        outer_loop.stop()

    entry = _entry(lines, "outer_loop_cycle")
    assert entry["consumed_tick"] == 7
    assert entry["staleness"] is None
    assert "ModeDirective" in entry["directive"]


def test_outer_loop_meta_decide_failed_event() -> None:
    lines: list[str] = []
    belief_buffer = BeliefBuffer()

    def meta_decide(belief_state, action_memory):
        raise RuntimeError("boom")

    outer_loop = OuterLoop(
        meta_decide,
        belief_buffer,
        ModeBuffer(),
        logger=Logger(sink=lines.append),
    )
    outer_loop.start()
    try:
        belief_buffer.push(BeliefState(tick=3), ActionMemory())
        assert _wait_until(lambda: any('"type": "meta_decide_failed"' in line for line in lines))
    finally:
        outer_loop.stop()

    entry = _entry(lines, "meta_decide_failed")
    assert entry["consumed_tick"] == 3
    assert "RuntimeError" in entry["exception"]


def test_hook_failure_event() -> None:
    lines: list[str] = []
    registry = HookRegistry()

    def crashing_hook(belief_state: BeliefState) -> None:
        raise ValueError("bad hook")

    registry.register_hook(HookPoint.POST_BELIEF_UPDATE, crashing_hook)
    registry.dispatch(
        HookPoint.POST_BELIEF_UPDATE,
        "idle",
        BeliefState(tick=11),
        logger=Logger(sink=lines.append),
    )

    entry = _entry(lines, "hook_failure")
    assert entry["hook_point"] == "post_belief_update"
    assert entry["mode"] == "idle"
    assert entry["hook_name"] == "crashing_hook"
    assert "ValueError" in entry["exception"]
    assert "Traceback" in entry["traceback"]


def test_log_event_helper_works_from_a_hook(pipeline_factory) -> None:
    lines: list[str] = []
    hooks = HookRegistry()

    def custom_hook(belief_state: BeliefState) -> None:
        log_event(belief_state._logger, "custom", {"x": 1})

    hooks.register_hook(HookPoint.POST_BELIEF_UPDATE, custom_hook)
    pipeline = pipeline_factory(
        hook_registry=hooks,
        logger=Logger(sink=lines.append),
    )

    _tick(pipeline)

    entry = _entry(lines, "custom")
    assert entry["x"] == 1
    assert entry["tick"] == 1


def test_callable_only_logger_still_gets_old_strings(pipeline_factory) -> None:
    messages: list[str] = []
    fallback = ModeDirective(mode="fallback_mode", params=FallbackParams())
    pipeline = pipeline_factory(
        logger=messages.append,
        fallback_directive=fallback,
        watchdog_threshold=1,
    )

    _tick(pipeline)

    assert any(message.startswith("watchdog_fired: ") for message in messages)
