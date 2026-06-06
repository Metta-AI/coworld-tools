"""Trace/metrics sink tests: newline-delimited JSON to a stream (design §11)."""

from __future__ import annotations

import io
import json

from players.crewrift.richardborg.trace import (
    StderrJsonMetricsSink,
    StderrJsonTraceSink,
)
from players.player_sdk.trace import TraceEvent


def test_trace_sink_writes_one_json_line_per_event() -> None:
    stream = io.StringIO()
    sink = StderrJsonTraceSink(stream)

    sink.record(TraceEvent(tick=1, name="mode_entered", data={"mode": "idle"}))
    sink.record(TraceEvent(tick=2, name="act_command", data={}))

    lines = stream.getvalue().splitlines()
    assert len(lines) == 2
    first = json.loads(lines[0])
    assert first == {
        "kind": "trace",
        "tick": 1,
        "event": "mode_entered",
        "data": {"mode": "idle"},
    }


def test_metrics_sink_records_each_sample_kind() -> None:
    stream = io.StringIO()
    sink = StderrJsonMetricsSink(stream)

    sink.counter("cyborg.mode.ran", tags={"mode": "idle"})
    sink.histogram("cyborg.step.latency_ms", 1.5)
    sink.gauge("cyborg.directive.age_ticks", 3)

    records = [json.loads(line) for line in stream.getvalue().splitlines()]
    assert [r["metric_kind"] for r in records] == ["counter", "histogram", "gauge"]
    assert records[0]["name"] == "cyborg.mode.ran"
    assert records[0]["tags"] == {"mode": "idle"}
    assert records[1]["value"] == 1.5
