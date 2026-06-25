"""LLM client seam for meeting chat/vote decisions."""

from __future__ import annotations

import json
import os
import time
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict

from players.player_sdk import ModeParams
from players.crewrift.crewborg.strategy.meeting.prompts import build_system_prompt
from players.crewrift.crewborg.strategy.meeting.schema import (
    VOTE_SKIP,
    MeetingDecision,
)

DEFAULT_MEETING_MODEL = "claude-haiku-4-5-20251001"
# Bedrock addresses models by inference-profile ID rather than the bare model
# name used by the direct Anthropic API.
DEFAULT_BEDROCK_MODEL = "us.anthropic.claude-haiku-4-5-20251001-v1:0"


@dataclass(frozen=True)
class MeetingLLMConfig:
    model: str = DEFAULT_MEETING_MODEL
    max_tokens: int = 512
    temperature: float = 0.2
    timeout_seconds: float = 3.0
    trace_raw: bool = False
    use_bedrock: bool = False


class MeetingParams(ModeParams):
    """Strategy-supplied Attend Meeting parameters."""

    use_llm: bool = False
    use_bedrock: bool = False
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
        self._client = client

    def _anthropic_client(self) -> Any:
        if self._client is not None:
            return self._client
        if self.config.use_bedrock:
            # AnthropicBedrock authenticates through the standard AWS environment
            # (AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY / AWS_SESSION_TOKEN and
            # AWS_REGION), the same way the direct client reads ANTHROPIC_API_KEY.
            # It needs the optional boto3 dependency (the `bedrock` extra).
            from anthropic import AnthropicBedrock

            self._client = AnthropicBedrock(timeout=self.config.timeout_seconds)
        else:
            from anthropic import Anthropic

            self._client = Anthropic(timeout=self.config.timeout_seconds)
        return self._client

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
        system_prompt = build_system_prompt(_context_role(context))
        start = time.perf_counter()
        response = self._anthropic_client().messages.create(
            model=self.config.model,
            max_tokens=self.config.max_tokens,
            temperature=self.config.temperature,
            system=system_prompt,
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


def read_meeting_params_from_env(env: Mapping[str, str] | None = None) -> MeetingParams:
    """Read meeting LLM behavior flags once for the strategy layer."""

    env = os.environ if env is None else env
    use_bedrock = _bedrock_enabled(env)
    # The LLM needs a viable backend: Bedrock authenticates through the AWS
    # environment, while the direct Anthropic path needs ANTHROPIC_API_KEY.
    # Setting a Bedrock flag also implies meetings are on, so an upload that only
    # passes --use-bedrock still turns the feature on without a second flag.
    meetings_on = _truthy_value(env.get("CREWBORG_LLM_MEETINGS", "")) or use_bedrock
    has_backend = use_bedrock or bool(env.get("ANTHROPIC_API_KEY"))
    use_llm = meetings_on and has_backend
    trace_raw = _truthy_value(env.get("CREWBORG_LLM_TRACE_RAW", ""))
    trace_raw = trace_raw or env.get("CREWBORG_TRACE", "").strip().lower() == "debug"
    return MeetingParams(
        use_llm=use_llm,
        use_bedrock=use_bedrock,
        model=_resolve_model(env, use_bedrock),
        max_tokens=_env_int(env, "CREWBORG_LLM_MAX_TOKENS", 512),
        temperature=_env_float(env, "CREWBORG_LLM_TEMPERATURE", 0.2),
        timeout_seconds=_env_float(env, "CREWBORG_LLM_TIMEOUT_SECONDS", 3.0),
        trace_raw=trace_raw,
    )


def build_meeting_client(params: MeetingParams) -> MeetingLLMClient:
    if not params.use_llm:
        return DisabledMeetingClient("meeting LLM disabled by strategy params")
    config = MeetingLLMConfig(
        model=params.model,
        max_tokens=params.max_tokens,
        temperature=params.temperature,
        timeout_seconds=params.timeout_seconds,
        trace_raw=params.trace_raw,
        use_bedrock=params.use_bedrock,
    )
    return AnthropicMeetingClient(config)


def _bedrock_enabled(env: Mapping[str, str]) -> bool:
    return (
        _truthy_value(env.get("CREWBORG_USE_BEDROCK", ""))
        or _truthy_value(env.get("USE_BEDROCK", ""))
        or _truthy_value(env.get("CLAUDE_CODE_USE_BEDROCK", ""))
    )


def _resolve_model(env: Mapping[str, str], use_bedrock: bool) -> str:
    explicit = env.get("CREWBORG_LLM_MODEL")
    if explicit:
        return explicit
    return DEFAULT_BEDROCK_MODEL if use_bedrock else DEFAULT_MEETING_MODEL


def _context_role(context: dict[str, Any]) -> str | None:
    self_block = context.get("self")
    if isinstance(self_block, dict):
        role = self_block.get("role")
        if isinstance(role, str):
            return role
    return None


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


def _truthy_value(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(env: Mapping[str, str], name: str, default: int) -> int:
    try:
        return int(env.get(name, default))
    except (TypeError, ValueError):
        return default


def _env_float(env: Mapping[str, str], name: str, default: float) -> float:
    try:
        return float(env.get(name, default))
    except (TypeError, ValueError):
        return default
