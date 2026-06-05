"""LLM client seam for meeting chat/vote decisions."""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict

from players.crewrift.crewborg.strategy.meeting.schema import (
    CHAT_MAX_CHARS,
    VOTE_SKIP,
    MeetingDecision,
)

DEFAULT_MEETING_MODEL = "claude-haiku-4-5-20251001"

SYSTEM_PROMPT = f"""You are controlling one Crewrift player during an active meeting.
Choose exactly one JSON object matching the schema. Do not include markdown.

Actions:
- send_chat: send one concise printable-ASCII chat message now.
- set_tentative_vote: update the vote target but do not submit yet.
- submit_vote: submit the vote immediately.
- wait: do nothing this tick.

Rules:
- Use only vote_target values from constraints.valid_vote_targets or "{VOTE_SKIP}".
- Keep chat_text printable ASCII and at most {CHAT_MAX_CHARS} characters.
- A submitted vote is final; tentative votes are auto-submitted near the deadline.
- Prefer useful, game-grounded meeting speech over filler.
"""


@dataclass(frozen=True)
class MeetingLLMConfig:
    model: str = DEFAULT_MEETING_MODEL
    max_tokens: int = 512
    temperature: float = 0.2
    timeout_seconds: float = 3.0
    trace_raw: bool = False


class MeetingLLMResult(BaseModel):
    """A parsed LLM decision plus call metadata for tracing."""

    model_config = ConfigDict(extra="forbid")

    decision: MeetingDecision
    model: str
    latency_ms: float
    usage: dict[str, Any] | None = None
    raw_request: dict[str, Any] | None = None
    raw_response: str | None = None


class MeetingLLMClient(Protocol):
    enabled: bool
    disabled_reason: str | None

    def decide(self, context: dict[str, Any], *, trigger: str) -> MeetingLLMResult: ...


@dataclass(frozen=True)
class DisabledMeetingClient:
    disabled_reason: str = "disabled"
    enabled: bool = False

    def decide(self, context: dict[str, Any], *, trigger: str) -> MeetingLLMResult:
        del context, trigger
        raise RuntimeError(self.disabled_reason)


class AnthropicMeetingClient:
    """Anthropic Messages API adapter, kept behind the meeting-client protocol."""

    enabled = True
    disabled_reason = None

    def __init__(self, config: MeetingLLMConfig, *, client: Any | None = None) -> None:
        self.config = config
        if client is not None:
            self._client = client
            return
        from anthropic import Anthropic

        self._client = Anthropic(timeout=config.timeout_seconds)

    def decide(self, context: dict[str, Any], *, trigger: str) -> MeetingLLMResult:
        request = {
            "trigger": trigger,
            "context": context,
            "response_schema": {
                "schema_version": 1,
                "action": "send_chat | set_tentative_vote | submit_vote | wait",
                "chat_text": "string or null",
                "vote_target": f"player color, {VOTE_SKIP}, or null",
                "reason": "short rationale",
                "confidence": "0.0 to 1.0 or null",
            },
        }
        user_content = json.dumps(request, sort_keys=True, separators=(",", ":"))
        start = time.perf_counter()
        response = self._client.messages.create(
            model=self.config.model,
            max_tokens=self.config.max_tokens,
            temperature=self.config.temperature,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_content}],
        )
        latency_ms = (time.perf_counter() - start) * 1000.0
        raw_text = _response_text(response)
        decision = MeetingDecision.model_validate_json(_extract_json_object(raw_text))
        return MeetingLLMResult(
            decision=decision,
            model=self.config.model,
            latency_ms=latency_ms,
            usage=_usage_dict(response),
            raw_request=request if self.config.trace_raw else None,
            raw_response=raw_text if self.config.trace_raw else None,
        )


def build_meeting_llm_client_from_env(env: dict[str, str] | None = None) -> MeetingLLMClient:
    env = env or os.environ
    if env.get("CREWBORG_LLM_MEETINGS", "").strip().lower() not in {"1", "true", "yes", "on"}:
        return DisabledMeetingClient("CREWBORG_LLM_MEETINGS is not enabled")
    if not env.get("ANTHROPIC_API_KEY"):
        return DisabledMeetingClient("ANTHROPIC_API_KEY is not set")
    trace_raw = env.get("CREWBORG_LLM_TRACE_RAW", "").strip().lower() in {"1", "true", "yes", "on"}
    trace_raw = trace_raw or env.get("CREWBORG_TRACE", "").strip().lower() == "debug"
    config = MeetingLLMConfig(
        model=env.get("CREWBORG_LLM_MODEL", DEFAULT_MEETING_MODEL),
        max_tokens=_env_int(env, "CREWBORG_LLM_MAX_TOKENS", 512),
        temperature=_env_float(env, "CREWBORG_LLM_TEMPERATURE", 0.2),
        timeout_seconds=_env_float(env, "CREWBORG_LLM_TIMEOUT_SECONDS", 3.0),
        trace_raw=trace_raw,
    )
    return AnthropicMeetingClient(config)


def _response_text(response: Any) -> str:
    parts: list[str] = []
    for block in getattr(response, "content", []) or []:
        if isinstance(block, str):
            parts.append(block)
        elif isinstance(block, dict):
            text = block.get("text")
            if isinstance(text, str):
                parts.append(text)
        else:
            text = getattr(block, "text", None)
            if isinstance(text, str):
                parts.append(text)
    return "".join(parts).strip()


def _extract_json_object(text: str) -> str:
    first = text.find("{")
    last = text.rfind("}")
    if first < 0 or last < first:
        raise ValueError(f"LLM response did not contain a JSON object: {text!r}")
    return text[first : last + 1]


def _usage_dict(response: Any) -> dict[str, Any] | None:
    usage = getattr(response, "usage", None)
    if usage is None:
        return None
    if isinstance(usage, dict):
        return dict(usage)
    if hasattr(usage, "model_dump"):
        return usage.model_dump(mode="json")
    return {
        key: getattr(usage, key)
        for key in ("input_tokens", "output_tokens", "cache_creation_input_tokens", "cache_read_input_tokens")
        if hasattr(usage, key)
    }


def _env_int(env: dict[str, str], name: str, default: int) -> int:
    try:
        return int(env.get(name, default))
    except (TypeError, ValueError):
        return default


def _env_float(env: dict[str, str], name: str, default: float) -> float:
    try:
        return float(env.get(name, default))
    except (TypeError, ValueError):
        return default
