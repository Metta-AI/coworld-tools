"""Trace and metrics sinks that emit newline-delimited JSON to stderr.

The Coworld contract is **stdout = protocol channel, stderr = logs/traces**
(design §11, AGENTS.md §"Packaging"). These sinks satisfy the SDK's ``TraceSink``
and ``MetricsSink`` protocols (:mod:`players.player_sdk.trace`) and write one JSON
object per line to stderr so a log collector can parse them without touching the
protocol stream.
"""

from __future__ import annotations

import json
import sys
from typing import Any, TextIO

from players.player_sdk.trace import MetricSample, TraceEvent


class StderrJsonTraceSink:
    """Trace sink writing one JSON line per event to stderr."""

    def __init__(self, stream: TextIO | None = None) -> None:
        self._stream = stream if stream is not None else sys.stderr

    def record(self, event: TraceEvent) -> None:
        line = json.dumps(
            {
                "kind": "trace",
                "tick": event.tick,
                "event": event.name,
                "data": event.data,
            },
            default=str,
        )
        print(line, file=self._stream, flush=True)


class StderrJsonMetricsSink:
    """Metrics sink writing one JSON line per sample to stderr."""

    def __init__(self, stream: TextIO | None = None) -> None:
        self._stream = stream if stream is not None else sys.stderr

    def _emit(self, sample: MetricSample) -> None:
        line = json.dumps(
            {
                "kind": "metric",
                "metric_kind": sample.kind,
                "name": sample.name,
                "value": sample.value,
                "tags": sample.tags,
            },
            default=str,
        )
        print(line, file=self._stream, flush=True)

    def counter(
        self, name: str, value: float = 1.0, tags: dict[str, Any] | None = None
    ) -> None:
        self._emit(
            MetricSample(kind="counter", name=name, value=value, tags=dict(tags or {}))
        )

    def histogram(
        self, name: str, value: float, tags: dict[str, Any] | None = None
    ) -> None:
        self._emit(
            MetricSample(
                kind="histogram", name=name, value=value, tags=dict(tags or {})
            )
        )

    def gauge(
        self, name: str, value: float, tags: dict[str, Any] | None = None
    ) -> None:
        self._emit(
            MetricSample(kind="gauge", name=name, value=value, tags=dict(tags or {}))
        )
