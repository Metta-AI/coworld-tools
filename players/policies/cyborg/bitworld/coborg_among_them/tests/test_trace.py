"""Trace sink unit tests."""

from __future__ import annotations

import io
import json

from agent_policies.frameworks.coborg.trace import TraceEvent

from policies.cyborg.bitworld.coborg_among_them.trace import (
    JsonStderrTraceSink,
)


def test_json_stderr_trace_sink_writes_one_line_per_event() -> None:
    buffer = io.StringIO()
    sink = JsonStderrTraceSink(stream=buffer)
    sink.record(TraceEvent(tick=1, name="mode_entered", data={"mode": "idle"}))
    sink.record(TraceEvent(tick=2, name="action_intent", data={"mode": "idle"}))

    lines = [line for line in buffer.getvalue().splitlines() if line]
    assert len(lines) == 2
    parsed = [json.loads(line) for line in lines]
    assert parsed[0]["tick"] == 1
    assert parsed[0]["name"] == "mode_entered"
    assert parsed[1]["name"] == "action_intent"


def test_json_stderr_trace_sink_emits_deterministic_keys() -> None:
    buffer = io.StringIO()
    sink = JsonStderrTraceSink(stream=buffer)
    sink.record(TraceEvent(tick=1, name="x", data={"b": 2, "a": 1}))
    line = buffer.getvalue().strip()
    parsed = json.loads(line)
    assert parsed == {"tick": 1, "name": "x", "data": {"a": 1, "b": 2}}
