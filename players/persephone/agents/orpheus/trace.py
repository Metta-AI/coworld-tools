"""Trace writer for the Orpheus agent.

Opt-in JSONL tracing system. Enable via ORPHEUS_TRACE_DIR environment
variable. Produces structured trace files for post-mortem debugging,
LLM evaluation, and task analysis.

See TRACING.md for the full design specification.

Usage:
    tracer = TraceWriter.from_env()  # Returns None if disabled
    if tracer:
        tracer.event("phase_change", {"from": "lobby", "to": "playing"})
        tracer.decision(...)
        tracer.close()
"""

from __future__ import annotations

import atexit
import json
import logging
import os
import time
from datetime import datetime, timezone
from enum import IntEnum
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Trace level
# ---------------------------------------------------------------------------


class TraceLevel(IntEnum):
    """Controls which trace streams are active.

    Cumulative: higher levels include all lower-level streams.
    """

    OFF = 0
    EVENTS = 1       # events.jsonl only
    DECISIONS = 2    # events + decisions + tasks
    FULL = 3         # all streams including chat (with LLM prompts)


_LEVEL_NAMES: dict[str, TraceLevel] = {
    "off": TraceLevel.OFF,
    "events": TraceLevel.EVENTS,
    "decisions": TraceLevel.DECISIONS,
    "full": TraceLevel.FULL,
}


# ---------------------------------------------------------------------------
# Stream handle wrapper (per-file I/O with disable-on-error)
# ---------------------------------------------------------------------------


class _Stream:
    """A single JSONL output stream with fault-tolerant writes."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._file = open(path, "a", encoding="utf-8")
        self._disabled = False

    def write(self, record: dict[str, Any]) -> None:
        """Write a JSON record as one line. Disables on I/O error."""
        if self._disabled:
            return
        try:
            line = json.dumps(record, separators=(",", ":"), default=str)
            self._file.write(line + "\n")
            self._file.flush()
        except Exception as e:
            self._disabled = True
            logger.warning("Trace stream %s disabled: %s", self._path.name, e)

    def close(self) -> None:
        """Close the underlying file handle."""
        if not self._disabled:
            try:
                self._file.close()
            except Exception:
                pass


# ---------------------------------------------------------------------------
# TraceWriter
# ---------------------------------------------------------------------------


class TraceWriter:
    """Structured trace writer for the Orpheus agent.

    Manages multiple JSONL output streams and provides typed methods
    for each trace category. All writes are fire-and-forget; I/O errors
    disable the affected stream without crashing the agent.

    Use from_env() to create an instance (returns None when disabled).
    """

    def __init__(
        self,
        session_dir: Path,
        level: TraceLevel,
        meta: dict[str, str] | None = None,
    ) -> None:
        self._session_dir = session_dir
        self._level = level
        self._meta = meta or {}
        self._start_time = time.monotonic()
        self._start_unix_ms = int(time.time() * 1000)
        self._session_id = session_dir.name

        # Counters for manifest
        self._counters: dict[str, int] = {
            "total_frames": 0,
            "total_decisions": 0,
            "total_task_transitions": 0,
            "total_chats_sent": 0,
            "total_chats_received": 0,
        }
        self._phases_seen: set[str] = set()
        self._identity: dict[str, Any] = {}
        self._result: dict[str, Any] = {}
        self._config: dict[str, Any] = {}
        self._ended_reason: str = "unknown"

        # Open streams based on level
        self._events: _Stream | None = None
        self._decisions: _Stream | None = None
        self._tasks: _Stream | None = None
        self._chat: _Stream | None = None

        if level >= TraceLevel.EVENTS:
            self._events = _Stream(session_dir / "events.jsonl")
        if level >= TraceLevel.DECISIONS:
            self._decisions = _Stream(session_dir / "decisions.jsonl")
            self._tasks = _Stream(session_dir / "tasks.jsonl")
        if level >= TraceLevel.FULL:
            self._chat = _Stream(session_dir / "chat.jsonl")

        # Register atexit to flush manifest on unexpected exit
        atexit.register(self._atexit_close)

        logger.info(
            "Tracing enabled: %s (level=%s)",
            session_dir,
            level.name.lower(),
        )

    # -------------------------------------------------------------------
    # Factory
    # -------------------------------------------------------------------

    @classmethod
    def from_env(
        cls,
        *,
        trace_dir: str | None = None,
        trace_level: str | None = None,
        trace_meta: str | None = None,
    ) -> TraceWriter | None:
        """Create a TraceWriter from environment variables / kwargs.

        Kwargs override env vars. Returns None if tracing is disabled
        (no directory specified or level is OFF).

        Env vars:
            ORPHEUS_TRACE_DIR   -- root directory for trace output
            ORPHEUS_TRACE_LEVEL -- "events", "decisions", or "full"
            ORPHEUS_TRACE_META  -- comma-separated key=value pairs
        """
        dir_str = trace_dir or os.environ.get("ORPHEUS_TRACE_DIR")
        if not dir_str:
            return None

        level_str = (trace_level or os.environ.get("ORPHEUS_TRACE_LEVEL", "full")).lower()
        level = _LEVEL_NAMES.get(level_str, TraceLevel.FULL)
        if level == TraceLevel.OFF:
            return None

        # Parse meta
        meta_str = trace_meta or os.environ.get("ORPHEUS_TRACE_META", "")
        meta: dict[str, str] = {}
        if meta_str:
            for pair in meta_str.split(","):
                if "=" in pair:
                    k, v = pair.split("=", 1)
                    meta[k.strip()] = v.strip()

        # Create session directory
        now = datetime.now(timezone.utc)
        session_id = f"{now.strftime('%Y-%m-%dT%H%M%SZ')}_{os.getpid()}"
        session_dir = Path(dir_str) / session_id

        try:
            session_dir.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            logger.warning("Cannot create trace directory %s: %s", session_dir, e)
            return None

        return cls(session_dir=session_dir, level=level, meta=meta)

    # -------------------------------------------------------------------
    # Common record builder
    # -------------------------------------------------------------------

    def _base(self, tick: int) -> dict[str, Any]:
        """Build common fields for a trace record."""
        wall_ms = int((time.monotonic() - self._start_time) * 1000)
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + \
            f"{datetime.now(timezone.utc).microsecond // 1000:03d}Z"
        return {"tick": tick, "wall_ms": wall_ms, "ts": ts}

    # -------------------------------------------------------------------
    # Public methods -- events
    # -------------------------------------------------------------------

    def event(self, event_type: str, payload: dict[str, Any], *, tick: int = 0) -> None:
        """Emit an edge-triggered event.

        Args:
            event_type: Freeform event type string (e.g., "phase_change").
            payload: Arbitrary dict of event-specific data.
            tick: Current frame counter.
        """
        if not self._events:
            return
        record = self._base(tick)
        record["type"] = event_type
        record.update(payload)
        self._events.write(record)

        # Track phases for manifest
        if event_type == "phase_change":
            self._phases_seen.add(payload.get("to", ""))
        elif event_type == "identity":
            self._identity = dict(payload)
        elif event_type == "game_over":
            self._result = dict(payload)

    # -------------------------------------------------------------------
    # Public methods -- decisions
    # -------------------------------------------------------------------

    def decision(
        self,
        *,
        tick: int,
        decision_num: int,
        task: str,
        params: dict[str, Any],
        reasoning: str,
        latency_ms: float,
        context_summary: str,
        prev_task: str,
        prev_task_duration_ticks: int,
    ) -> None:
        """Log a slow-loop LLM decision."""
        if not self._decisions:
            return
        record = self._base(tick)
        record.update({
            "decision_num": decision_num,
            "task": task,
            "params": params,
            "reasoning": reasoning,
            "latency_ms": round(latency_ms, 1),
            "context_summary": context_summary,
            "prev_task": prev_task,
            "prev_task_duration_ticks": prev_task_duration_ticks,
        })
        self._decisions.write(record)
        self._counters["total_decisions"] = decision_num

    # -------------------------------------------------------------------
    # Public methods -- task transitions
    # -------------------------------------------------------------------

    def task_transition(
        self,
        *,
        tick: int,
        from_task: str,
        to_task: str,
        from_duration_ticks: int,
        from_duration_ms: float,
        trigger: str,
        params: dict[str, Any] | None = None,
    ) -> None:
        """Log a task transition."""
        if not self._tasks:
            return
        record = self._base(tick)
        record.update({
            "from": from_task,
            "to": to_task,
            "from_duration_ticks": from_duration_ticks,
            "from_duration_ms": round(from_duration_ms, 1),
            "trigger": trigger,
            "params": params or {},
        })
        self._tasks.write(record)
        self._counters["total_task_transitions"] += 1

    # -------------------------------------------------------------------
    # Public methods -- chat
    # -------------------------------------------------------------------

    def chat(
        self,
        *,
        tick: int,
        direction: str,
        **kwargs: Any,
    ) -> None:
        """Log a chat event (outbound LLM generation or inbound message).

        For outbound: pass system_prompt, user_prompt, response, latency_ms,
                      occupants, message_count_before.
        For inbound:  pass sender_color, text, is_system.
        """
        if not self._chat:
            return
        record = self._base(tick)
        record["direction"] = direction
        record.update(kwargs)
        self._chat.write(record)

        if direction == "outbound":
            self._counters["total_chats_sent"] += 1
        elif direction == "inbound":
            self._counters["total_chats_received"] += 1

    # -------------------------------------------------------------------
    # Configuration recording
    # -------------------------------------------------------------------

    def set_config(self, config: dict[str, Any]) -> None:
        """Record agent configuration for the manifest."""
        self._config = dict(config)

    def set_ended_reason(self, reason: str) -> None:
        """Record why the session ended."""
        self._ended_reason = reason

    def increment_frames(self) -> None:
        """Increment the total frames counter. Called by the fast loop."""
        self._counters["total_frames"] += 1

    # -------------------------------------------------------------------
    # Lifecycle
    # -------------------------------------------------------------------

    def close(self) -> None:
        """Write manifest and close all streams.

        Safe to call multiple times.
        """
        self._write_manifest()

        for stream in (self._events, self._decisions, self._tasks, self._chat):
            if stream:
                stream.close()

        # Unregister atexit so we don't double-close
        try:
            atexit.unregister(self._atexit_close)
        except Exception:
            pass

    def _atexit_close(self) -> None:
        """Called by atexit for unexpected exits."""
        self._ended_reason = "atexit"
        self.close()

    def _write_manifest(self) -> None:
        """Write the session manifest to manifest.json."""
        manifest = {
            "schema_version": 1,
            "session_id": self._session_id,
            "agent": "orpheus",
            "started_unix_ms": self._start_unix_ms,
            "ended_unix_ms": int(time.time() * 1000),
            "ended_reason": self._ended_reason,
            "config": self._config,
            "identity": self._identity,
            "counters": dict(self._counters),
            "phases_seen": sorted(self._phases_seen),
            "result": self._result,
            "meta": self._meta,
        }
        path = self._session_dir / "manifest.json"
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(manifest, f, indent=2, default=str)
        except Exception as e:
            logger.warning("Failed to write manifest: %s", e)
