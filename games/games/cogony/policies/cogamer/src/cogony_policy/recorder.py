"""Structured event recorder for CvC policy diagnostics.

Single producer of per-tick events. Events fan out to configured sinks
(stderr, events.json, mettagrid policyInfos). Replaces the stderr-only
LogConfig.
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable


def _fmt_value(v: Any) -> str:
    s = str(v)
    if any(c.isspace() for c in s):
        return f"'{s}'"
    return s


def _fmt_payload_default(payload: dict[str, Any]) -> str:
    return " ".join(f"{k}={_fmt_value(v)}" for k, v in payload.items())


def _fmt_payload_action(payload: dict[str, Any]) -> str:
    return payload.get("summary", "")


def _fmt_payload_target(payload: dict[str, Any]) -> str:
    return f"{payload.get('kind', '?')}@{payload.get('pos', '?')}"


def _fmt_payload_patch_applied(payload: dict[str, Any]) -> str:
    applied = payload.get("applied") or {}
    parts = [f"{k}={_fmt_value(v)}" for k, v in applied.items()]
    rationale = payload.get("rationale")
    if rationale:
        parts.append(f"rationale={_fmt_value(rationale)}")
    return " ".join(parts)


def _fmt_payload_llm_turn(payload: dict[str, Any]) -> str:
    prompt = (payload.get("prompt") or "").strip()
    text = (payload.get("text") or "").strip()
    tools = payload.get("tool_calls") or []
    latency = payload.get("latency_ms", 0)
    parts = []
    if prompt:
        parts.append(f"--- prompt ---\n{prompt}")
    if text:
        parts.append(f"--- response ---\n{text}")
    if tools:
        tool_strs = [f"{tc.get('tool', '?')}({json.dumps(tc.get('input', {}))})" for tc in tools]
        parts.append("--- tool calls ---\n" + "\n".join(tool_strs))
    parts.append(f"({latency:.0f}ms)")
    return "\n".join(parts)


_PAYLOAD_RENDERERS: dict[str, Any] = {
    "action": _fmt_payload_action,
    "target": _fmt_payload_target,
    "patch_applied": _fmt_payload_patch_applied,
    "llm_turn": _fmt_payload_llm_turn,
}


def fmt(event: dict[str, Any]) -> str:
    """Render an event as a single-line stderr string."""
    stream = event["stream"]
    step = event["step"]
    agent = event.get("agent")
    etype = event["type"]
    payload = event.get("payload") or {}
    renderer = _PAYLOAD_RENDERERS.get(etype, _fmt_payload_default)
    body = renderer(payload)
    prefix = f"[{stream}]"
    agent_part = f" a{agent}" if agent is not None else ""
    head = f"{prefix}{agent_part} step={step} {etype}"
    if body:
        return f"{head} {body}"
    return head


def payload_text(event: dict[str, Any]) -> str:
    """Render just the payload portion of an event — without the
    `[stream]`, `a<N>`, `step=N`, or `type` prefix produced by `fmt`.

    Used by the HTML viewer, where stream/agent/type are rendered as
    separate styled spans rather than literal prefix text.
    """
    etype = event["type"]
    payload = event.get("payload") or {}
    renderer = _PAYLOAD_RENDERERS.get(etype, _fmt_payload_default)
    return renderer(payload)


class EventRecorder:
    def __init__(
        self,
        *,
        stderr_streams: Iterable[str] | None = None,
        record_dir: str | None = None,
    ) -> None:
        self._step = 0
        self.events: list[dict[str, Any]] = []
        self._events_by_step: dict[int, list[dict[str, Any]]] = defaultdict(list)
        self._stderr_streams: frozenset[str] = frozenset(stderr_streams or ())
        self._record_dir = record_dir

    def set_step(self, step: int) -> None:
        self._step = step

    def emit(
        self,
        *,
        type: str,
        agent: int | None,
        stream: str,
        payload: dict[str, Any],
    ) -> None:
        ev = {
            "step": self._step,
            "agent": agent,
            "stream": stream,
            "type": type,
            "payload": dict(payload),
        }
        self.events.append(ev)
        self._events_by_step[self._step].append(ev)
        if stream in self._stderr_streams:
            print(fmt(ev), file=sys.stderr, flush=True)

    def events_for_step(
        self, step: int, *, agent: int | None = None
    ) -> list[dict[str, Any]]:
        out = list(self._events_by_step.get(step, ()))
        if agent is not None:
            out = [e for e in out if e["agent"] == agent]
        return out

    def flush_json(self, path: str | Path) -> None:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(self.events, default=str))
