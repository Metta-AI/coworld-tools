"""Structured JSONL logging for the Orpheus runtime."""

from __future__ import annotations

from collections.abc import Callable
from enum import Enum
import json
import sys
import time


class LogLevel(Enum):
    """Logging verbosity levels in increasing order."""

    OFF = "off"
    EVENTS = "events"
    DECISIONS = "decisions"
    VERBOSE = "verbose"

    def __lt__(self, other: object) -> bool:
        if not isinstance(other, LogLevel):
            return NotImplemented
        return _LOG_LEVEL_RANK[self] < _LOG_LEVEL_RANK[other]

    def __le__(self, other: object) -> bool:
        if not isinstance(other, LogLevel):
            return NotImplemented
        return _LOG_LEVEL_RANK[self] <= _LOG_LEVEL_RANK[other]

    def __gt__(self, other: object) -> bool:
        if not isinstance(other, LogLevel):
            return NotImplemented
        return _LOG_LEVEL_RANK[self] > _LOG_LEVEL_RANK[other]

    def __ge__(self, other: object) -> bool:
        if not isinstance(other, LogLevel):
            return NotImplemented
        return _LOG_LEVEL_RANK[self] >= _LOG_LEVEL_RANK[other]


_LOG_LEVEL_RANK = {
    LogLevel.OFF: 0,
    LogLevel.EVENTS: 1,
    LogLevel.DECISIONS: 2,
    LogLevel.VERBOSE: 3,
}


class Logger:
    """Structured JSONL logger for the Orpheus pipeline.

    Backward compatible with the existing Callable[[str], None] interface:
    Logger instances are callable. Calling logger(some_string) emits a "raw"
    entry at events level. Calling logger.event(category, data, level) emits a
    structured JSONL entry that respects the configured level.
    """

    def __init__(
        self,
        level: LogLevel | str = LogLevel.EVENTS,
        sink: Callable[[str], None] | None = None,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self.level = _coerce_level(level)
        self._sink = sink if sink is not None else sys.stderr.write
        self._clock = clock if clock is not None else time.time
        self._metadata: dict[str, object] = {
            "tick": None,
            "mode": None,
            "task": None,
            "view": None,
        }

    def __call__(self, message: str) -> None:
        """Backward-compat: existing callable callers emit raw events."""
        self.event("raw", {"message": message})

    def event(
        self,
        category: str,
        data: dict,
        level: LogLevel | str = LogLevel.EVENTS,
    ) -> None:
        """Emit a JSONL entry if ``level`` is enabled at ``self.level``."""
        requested = _coerce_level(level)
        if not _level_enabled(configured=self.level, requested=requested):
            return

        entry = {
            "tick": self._metadata.get("tick"),
            "wall_clock": self._clock(),
            "mode": self._metadata.get("mode"),
            "task": self._metadata.get("task"),
            "view": self._metadata.get("view"),
            "level": requested.value,
            "type": category,
            **data,
        }
        line = json.dumps(entry, default=str) + "\n"
        self._sink(line)

    def update_metadata(self, **kwargs: object) -> None:
        """Set tick/mode/task/view metadata."""
        self._metadata.update(kwargs)


def log_event(
    logger: object,
    category: str,
    data: dict,
    level: LogLevel | str = LogLevel.EVENTS,
) -> None:
    """Emit a structured event when ``logger`` is a Logger instance."""
    if isinstance(logger, Logger):
        logger.event(category, data, level)


def _level_enabled(configured: LogLevel, requested: LogLevel) -> bool:
    if configured is LogLevel.OFF:
        return False
    return _LOG_LEVEL_RANK[requested] <= _LOG_LEVEL_RANK[configured]


def _coerce_level(level: LogLevel | str) -> LogLevel:
    if isinstance(level, LogLevel):
        return level
    return LogLevel(level)


__all__ = ["LogLevel", "Logger", "log_event"]
