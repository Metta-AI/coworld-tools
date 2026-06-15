"""Small Anthropic client helpers for LLM-driven players."""

from __future__ import annotations

import os
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

DEFAULT_DIRECT_MODEL = "claude-haiku-4-5-20251001"
# Bedrock uses inference-profile model IDs, not the bare direct Anthropic model name.
DEFAULT_BEDROCK_MODEL = "us.anthropic.claude-haiku-4-5-20251001-v1:0"

_BEDROCK_ENV_NAMES = ("USE_BEDROCK", "CLAUDE_CODE_USE_BEDROCK")
_TOKEN_KEYS = (
    "input_tokens",
    "output_tokens",
    "cache_creation_input_tokens",
    "cache_read_input_tokens",
)


@dataclass(frozen=True)
class LLMCall:
    """Raw text response plus call metadata from an Anthropic Messages request."""

    text: str
    usage: dict[str, Any] | None
    latency_ms: float
    model: str


def bedrock_enabled(
    env: Mapping[str, str] | None = None,
    extra_names: Sequence[str] = (),
) -> bool:
    """Return whether any supported Bedrock flag is set to a truthy value."""

    source = os.environ if env is None else env
    return any(_truthy_value(source.get(name, "")) for name in (*extra_names, *_BEDROCK_ENV_NAMES))


def resolve_model(
    *,
    use_bedrock: bool,
    direct_model: str,
    bedrock_model: str,
    explicit: str | None = None,
) -> str:
    """Resolve the model ID for direct Anthropic API or Bedrock-backed calls."""

    if explicit is not None:
        return explicit
    return bedrock_model if use_bedrock else direct_model


def select_client(*, use_bedrock: bool, timeout: float) -> Any:
    """Construct the direct Anthropic client or the Bedrock-backed client."""

    if use_bedrock:
        try:
            # Keep the optional boto3-backed Bedrock client out of the SDK import path.
            from anthropic import AnthropicBedrock

            return AnthropicBedrock(timeout=timeout)
        except ImportError as exc:
            raise RuntimeError("Bedrock client requires the 'bedrock' extra (boto3); install players[bedrock]") from exc

    from anthropic import Anthropic

    return Anthropic(timeout=timeout)


def extract_json_object(text: str) -> str:
    """Return the first JSON-object-shaped slice from an LLM response."""

    first = text.find("{")
    last = text.rfind("}")
    if first < 0 or last < first:
        raise ValueError(f"LLM response did not contain a JSON object: {text!r}")
    return text[first : last + 1]


def response_text(response: Any) -> str:
    """Defensively collect text content from Anthropic-style response blocks."""

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


def usage_dict(response: Any) -> dict[str, Any] | None:
    """Defensively convert Anthropic usage metadata to a plain dictionary."""

    usage = getattr(response, "usage", None)
    if usage is None:
        return None
    if isinstance(usage, dict):
        return dict(usage)
    if hasattr(usage, "model_dump"):
        return usage.model_dump(mode="json")
    return {key: getattr(usage, key) for key in _TOKEN_KEYS if hasattr(usage, key)}


def call_json(
    client: Any,
    *,
    model: str,
    system: str,
    user: str,
    max_tokens: int,
    temperature: float = 0.0,
    **create_kwargs: Any,
) -> LLMCall:
    """Call Anthropic Messages and return text intended for caller-side JSON parsing."""

    start = time.perf_counter()
    response = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        temperature=temperature,
        system=system,
        messages=[{"role": "user", "content": user}],
        **create_kwargs,
    )
    latency_ms = (time.perf_counter() - start) * 1000.0
    return LLMCall(
        text=response_text(response),
        usage=usage_dict(response),
        latency_ms=latency_ms,
        model=model,
    )


def _truthy_value(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "on"}
