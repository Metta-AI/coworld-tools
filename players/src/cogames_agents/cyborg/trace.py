from __future__ import annotations

from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field


class TraceEvent(BaseModel):
    """One framework boundary event."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    tick: int
    name: str
    data: dict[str, Any] = Field(default_factory=dict)


class TraceSink(Protocol):
    """Trace sink protocol used by the runtime and strategy runners."""

    def record(self, event: TraceEvent) -> None: ...


class NullTraceSink:
    """Trace sink that drops events."""

    def record(self, event: TraceEvent) -> None:
        del event


class ListTraceSink:
    """In-memory trace sink for tests and small examples."""

    def __init__(self) -> None:
        self.events: list[TraceEvent] = []

    def record(self, event: TraceEvent) -> None:
        self.events.append(event)

    def names(self) -> list[str]:
        return [event.name for event in self.events]
