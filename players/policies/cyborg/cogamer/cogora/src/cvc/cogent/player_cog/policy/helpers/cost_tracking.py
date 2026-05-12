"""LLM API token usage and cost tracking.

Adapted from llm-agent's cost_tracker.py. Aggregates token counts across
policy generation and review calls. Works with cog-cyborg's existing
CodeReviewResponse.metadata fields (input_tokens, output_tokens, api_latency_ms).
"""

from __future__ import annotations

import time
from dataclasses import dataclass


@dataclass
class CallRecord:
    """One LLM API call."""

    input_tokens: int
    output_tokens: int
    latency_ms: float
    model: str = ""
    trigger: str = ""


class CostTracker:
    """Tracks LLM API token usage across policy calls."""

    def __init__(self) -> None:
        self._calls: list[CallRecord] = []
        self._start_time: float | None = None

    def start_timer(self) -> None:
        if self._start_time is None:
            self._start_time = time.monotonic()

    def reset(self) -> None:
        self._calls.clear()
        self._start_time = None

    def record(
        self,
        *,
        input_tokens: int,
        output_tokens: int,
        latency_ms: float = 0.0,
        model: str = "",
        trigger: str = "",
    ) -> None:
        if self._start_time is None:
            self._start_time = time.monotonic()
        self._calls.append(
            CallRecord(
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                latency_ms=latency_ms,
                model=model,
                trigger=trigger,
            )
        )

    def record_from_metadata(self, metadata: dict[str, object]) -> None:
        """Record from a CodeReviewResponse.metadata dict."""
        input_tokens = int(metadata.get("input_tokens", 0) or 0)
        output_tokens = int(metadata.get("output_tokens", 0) or 0)
        latency_ms = float(metadata.get("api_latency_ms", 0.0) or 0.0)
        model = str(metadata.get("model", ""))
        trigger = str(metadata.get("trigger_name", ""))
        self.record(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            latency_ms=latency_ms,
            model=model,
            trigger=trigger,
        )

    @property
    def total_calls(self) -> int:
        return len(self._calls)

    @property
    def total_input_tokens(self) -> int:
        return sum(c.input_tokens for c in self._calls)

    @property
    def total_output_tokens(self) -> int:
        return sum(c.output_tokens for c in self._calls)

    @property
    def total_tokens(self) -> int:
        return self.total_input_tokens + self.total_output_tokens

    @property
    def total_latency_ms(self) -> float:
        return sum(c.latency_ms for c in self._calls)

    @property
    def elapsed_seconds(self) -> float:
        if self._start_time is None:
            return 0.0
        return time.monotonic() - self._start_time

    def summary(self) -> dict[str, int | float]:
        return {
            "total_calls": self.total_calls,
            "total_tokens": self.total_tokens,
            "total_input_tokens": self.total_input_tokens,
            "total_output_tokens": self.total_output_tokens,
            "total_latency_ms": self.total_latency_ms,
            "elapsed_seconds": round(self.elapsed_seconds, 1),
        }

    def summary_by_model(self) -> dict[str, dict[str, int | float]]:
        by_model: dict[str, list[CallRecord]] = {}
        for call in self._calls:
            key = call.model or "unknown"
            by_model.setdefault(key, []).append(call)
        return {
            model: {
                "calls": len(calls),
                "input_tokens": sum(c.input_tokens for c in calls),
                "output_tokens": sum(c.output_tokens for c in calls),
                "total_tokens": sum(c.input_tokens + c.output_tokens for c in calls),
                "total_latency_ms": sum(c.latency_ms for c in calls),
            }
            for model, calls in sorted(by_model.items())
        }
