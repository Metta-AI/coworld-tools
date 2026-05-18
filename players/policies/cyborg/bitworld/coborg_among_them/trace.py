"""Stderr-only trace and metrics sinks.

Per PLAN §8 and D3, all agent logs/traces go to stderr so the Coworld runner's
``capture-stderr`` flow picks them up. Stdout is reserved for the WebSocket
protocol channel even though we use a side-band WS connection — keeping the
discipline avoids regressions when dependencies print uninvited.
"""

from __future__ import annotations

import json
import logging
import sys
from typing import TextIO

from agent_policies.frameworks.coborg.trace import (
    LoggingMetricsSink,
    LoggingTraceSink,
    MetricsSink,
    TraceEvent,
    TraceSink,
)

LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s %(message)s"


def configure_stderr_logging(level: int = logging.INFO) -> None:
    """Route the root logger to stderr with a consistent format.

    Idempotent: re-running clears the existing root handlers first so test
    runs don't accumulate duplicates.
    """

    root = logging.getLogger()
    for handler in list(root.handlers):
        root.removeHandler(handler)
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter(LOG_FORMAT))
    root.addHandler(handler)
    root.setLevel(level)


class JsonStderrTraceSink:
    """Write one JSON-line per :class:`TraceEvent` to stderr.

    Mirrors the structured trace shape used by ``guided_bot``'s ``trace.py``,
    so downstream parsers and replay tools work against both agents.
    """

    def __init__(self, stream: TextIO | None = None) -> None:
        self._stream = stream if stream is not None else sys.stderr

    def record(self, event: TraceEvent) -> None:
        line = json.dumps(
            event.model_dump(mode="json"), separators=(",", ":"), sort_keys=True
        )
        self._stream.write(line)
        self._stream.write("\n")
        self._stream.flush()


def build_stderr_sinks() -> tuple[TraceSink, MetricsSink]:
    """Return (trace, metrics) sinks wired to stderr via the structured logger."""

    return LoggingTraceSink(), LoggingMetricsSink()
