"""CogletTrace — optional JSONL event recorder for coglet runtimes.

Stub: the original coglet.trace was not present in the source repo.
Only the interface used by CogletRuntime is defined here.
"""

from __future__ import annotations

from typing import Any


class CogletTrace:
    """Records coglet events to a JSONL file."""

    def record(self, coglet_name: str, event_type: str, channel: str, data: Any) -> None:
        """Record a trace event."""

    def close(self) -> None:
        """Close the trace file."""
