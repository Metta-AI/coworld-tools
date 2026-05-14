"""End-to-end runtime assembly tests."""

from __future__ import annotations

from agent_policies.frameworks.coborg.trace import ListTraceSink

from agent_policies.policies.cyborg.bitworld.coborg_among_them import (
    build_runtime,
)
from agent_policies.policies.cyborg.bitworld.coborg_among_them.types import (
    PACKED_FRAME_BYTES,
    AmongThemObservation,
)


def _noop_frame() -> bytes:
    return bytes(PACKED_FRAME_BYTES)


def test_build_runtime_step_returns_input_packet() -> None:
    trace = ListTraceSink()
    runtime = build_runtime(trace_sink=trace)
    try:
        command = runtime.step(AmongThemObservation(packed_frame=_noop_frame()))
    finally:
        runtime.close()
    assert command.packets == (bytes([0x00, 0x00]),)


def test_build_runtime_emits_canonical_trace_events() -> None:
    trace = ListTraceSink()
    runtime = build_runtime(trace_sink=trace)
    try:
        for _ in range(3):
            runtime.step(AmongThemObservation(packed_frame=_noop_frame()))
    finally:
        runtime.close()
    names = set(trace.names())
    assert {"mode_entered", "perception", "action_intent", "act_command"} <= names


def test_runtime_increments_tick_and_belief() -> None:
    runtime = build_runtime()
    try:
        for _ in range(5):
            runtime.step(AmongThemObservation(packed_frame=_noop_frame()))
        assert runtime.tick == 5
        assert runtime.belief.tick == 5
    finally:
        runtime.close()
