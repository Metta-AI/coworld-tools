"""Unified LLM provider.

Light wrapper around the ``openai`` and ``anthropic`` Python SDKs that exposes
a single :class:`LLM` class with AI-Gateway-style model strings. We do not
hard-import any SDK at module load time so the SDK stays usable when none
of them are installed.

Provider routing rules:

  * ``"<short>"`` (no slash) — defaults to **AWS Bedrock**, using the alias
    table in :data:`BEDROCK_ALIASES` (e.g. ``"claude-sonnet"`` →
    ``us.anthropic.claude-sonnet-4-5-...``). Passing a full Bedrock model
    ID (with a ``:`` or starting with ``anthropic.`` / ``us.anthropic.``)
    also routes to Bedrock.
  * ``"gpt-..."`` / ``"o1-..."`` / ``"o3-..."`` (no slash) — OpenAI
    (back-compat).
  * ``"openai/<model>"`` — OpenAI direct API
  * ``"anthropic/<model>"`` — Anthropic direct API
  * ``"bedrock/<model>"`` — AWS Bedrock (alias-aware)
  * ``"gateway/<provider>/<model>"`` — Vercel AI Gateway routing (uses
    ``AI_GATEWAY_API_KEY`` and ``AI_GATEWAY_BASE_URL``)

If the matching credentials aren't set, :class:`LLM` raises
:class:`LLMUnavailableError` on construction. Callers should catch this and
either fall back to scripted behavior or surface a helpful message.

Bedrock auth uses the standard boto3 credential chain — set
``AWS_PROFILE`` (recommended for SSO) or ``AWS_ACCESS_KEY_ID`` /
``AWS_SECRET_ACCESS_KEY``, plus ``AWS_REGION`` (default: ``us-east-1``).
SSO users must run ``aws sso login --profile <name>`` before the first call.

This is intentionally minimal — just ``complete()``. The Vercel-style "tool
loop" lives in :mod:`among_them_sdk.cognition.tools`.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from typing import Any, Literal, Protocol

logger = logging.getLogger("among_them_sdk.cognition.llm")


class LLMUnavailableError(RuntimeError):
    """Raised when the requested provider lacks credentials or is unsupported."""


@dataclass
class LLMResponse:
    text: str
    model: str
    raw: dict[str, Any] | None = None
    tool_calls: list[dict[str, Any]] | None = None


class LLMProvider(Protocol):
    def complete(
        self,
        system: str,
        user: str,
        *,
        response_format: Literal["text", "json"] = "text",
        max_tokens: int = 1024,
        temperature: float = 0.7,
    ) -> LLMResponse: ...


# --- Bedrock model aliases -------------------------------------------------
#
# Friendly names that map to AWS Bedrock inference profile IDs. Edit this
# table when newer Claude models become generally available; consumers stay
# pinned via the alias.
BEDROCK_ALIASES: dict[str, str] = {
    "claude-sonnet": "us.anthropic.claude-sonnet-4-5-20250929-v1:0",
    "claude-haiku": "us.anthropic.claude-haiku-4-5-20251001-v1:0",
}

# The SDK-wide default. Switch this knob to globally retarget every module
# that defaults to ``model="claude-sonnet"`` (LLMChatter, LLMVoter, Agent
# instructions parser, opponent analyzer, etc.).
DEFAULT_MODEL = "claude-sonnet"

# Heuristic: bare model strings starting with one of these prefixes are
# OpenAI-style and route there for back-compat with older code.
_OPENAI_PREFIXES = ("gpt-", "o1-", "o3-", "o4-")


def _split_model(model: str) -> tuple[str, str]:
    if "/" not in model:
        # Back-compat: gpt-/o-style names still route to OpenAI directly.
        if model.startswith(_OPENAI_PREFIXES):
            return ("openai", model)
        # Everything else (aliases like "claude-sonnet", or full Bedrock IDs
        # like "us.anthropic.claude-..." / "anthropic.claude-...:0") goes to
        # Bedrock by default.
        return ("bedrock", model)
    head, tail = model.split("/", 1)
    head = head.lower()
    if head in {"openai", "anthropic", "bedrock"}:
        return (head, tail)
    if head == "gateway":
        return ("gateway", tail)
    return ("openai", model)


class _OpenAIBackend:
    def __init__(self, model: str, api_key: str, base_url: str | None = None):
        try:
            from openai import OpenAI  # type: ignore[import-not-found]
        except ImportError as exc:
            raise LLMUnavailableError(
                "OpenAI provider requires `pip install openai`"
            ) from exc
        kwargs: dict[str, Any] = {"api_key": api_key}
        if base_url:
            kwargs["base_url"] = base_url
        self._client = OpenAI(**kwargs)
        self.model = model

    def complete(
        self,
        system: str,
        user: str,
        *,
        response_format: Literal["text", "json"] = "text",
        max_tokens: int = 1024,
        temperature: float = 0.7,
    ) -> LLMResponse:
        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        if response_format == "json":
            kwargs["response_format"] = {"type": "json_object"}
        try:
            resp = self._client.chat.completions.create(**kwargs)
        except Exception as exc:
            raise LLMUnavailableError(f"OpenAI completion failed: {exc}") from exc
        text = resp.choices[0].message.content or ""
        return LLMResponse(text=text, model=self.model, raw=resp.model_dump() if hasattr(resp, "model_dump") else None)


class _AnthropicBackend:
    def __init__(self, model: str, api_key: str):
        try:
            from anthropic import Anthropic  # type: ignore[import-not-found]
        except ImportError as exc:
            raise LLMUnavailableError(
                "Anthropic provider requires `pip install anthropic`"
            ) from exc
        self._client = Anthropic(api_key=api_key)
        self.model = model

    def complete(
        self,
        system: str,
        user: str,
        *,
        response_format: Literal["text", "json"] = "text",
        max_tokens: int = 1024,
        temperature: float = 0.7,
    ) -> LLMResponse:
        if response_format == "json":
            user = user + "\n\nRespond with valid JSON only, no surrounding prose."
        try:
            resp = self._client.messages.create(
                model=self.model,
                system=system,
                messages=[{"role": "user", "content": user}],
                max_tokens=max_tokens,
                temperature=temperature,
            )
        except Exception as exc:
            raise LLMUnavailableError(f"Anthropic completion failed: {exc}") from exc
        text = "".join(block.text for block in resp.content if hasattr(block, "text"))
        return LLMResponse(text=text, model=self.model)


class _BedrockBackend:
    """AWS Bedrock backend — Anthropic Claude via boto3 + AnthropicBedrock.

    Auth comes from the boto3 credential chain (``AWS_PROFILE``,
    ``AWS_ACCESS_KEY_ID``/``AWS_SECRET_ACCESS_KEY``, instance profiles).
    Region defaults to ``AWS_REGION`` / ``AWS_DEFAULT_REGION`` and falls
    back to ``us-east-1``.
    """

    def __init__(self, model: str):
        try:
            from anthropic import AnthropicBedrock  # type: ignore[import-not-found]
        except ImportError as exc:
            raise LLMUnavailableError(
                "Bedrock provider requires `pip install 'anthropic[bedrock]'` "
                "(or `uv add 'anthropic[bedrock]' boto3`)."
            ) from exc

        # Resolve aliases (e.g. "claude-sonnet") to a Bedrock inference
        # profile ID. Pass-through anything that already looks like a real
        # model ID.
        resolved = BEDROCK_ALIASES.get(model, model)
        self.model = resolved
        self.alias = model if model in BEDROCK_ALIASES else None

        kwargs: dict[str, Any] = {}
        profile = os.environ.get("AWS_PROFILE")
        region = (
            os.environ.get("AWS_REGION")
            or os.environ.get("AWS_DEFAULT_REGION")
            or "us-east-1"
        )
        if profile:
            kwargs["aws_profile"] = profile
        kwargs["aws_region"] = region

        try:
            self._client = AnthropicBedrock(**kwargs)
        except Exception as exc:
            raise LLMUnavailableError(
                "Could not initialize AnthropicBedrock client. "
                "Check AWS credentials (set AWS_PROFILE for SSO, or "
                "AWS_ACCESS_KEY_ID/AWS_SECRET_ACCESS_KEY) and AWS_REGION. "
                f"Original error: {exc}"
            ) from exc

    def complete(
        self,
        system: str,
        user: str,
        *,
        response_format: Literal["text", "json"] = "text",
        max_tokens: int = 1024,
        temperature: float = 0.7,
    ) -> LLMResponse:
        if response_format == "json":
            user = user + "\n\nRespond with valid JSON only, no surrounding prose."
        try:
            resp = self._client.messages.create(
                model=self.model,
                system=system,
                messages=[{"role": "user", "content": user}],
                max_tokens=max_tokens,
                temperature=temperature,
            )
        except Exception as exc:
            # SSO tokens expire — surface a hint so users know how to recover.
            msg = str(exc)
            hint = ""
            if "Token has expired" in msg or "ExpiredToken" in msg or "SSO" in msg:
                profile = os.environ.get("AWS_PROFILE", "<your-profile>")
                hint = (
                    f"\nHint: AWS SSO token may have expired. "
                    f"Run `aws sso login --profile {profile}`."
                )
            raise LLMUnavailableError(f"Bedrock completion failed: {exc}{hint}") from exc
        text = "".join(block.text for block in resp.content if hasattr(block, "text"))
        return LLMResponse(text=text, model=self.model)


class LLM:
    """Unified entry point: ``LLM("claude-sonnet")`` (Bedrock by default),
    ``LLM("gpt-5.5")`` (OpenAI), ``LLM("anthropic/claude-...")``, etc."""

    def __init__(self, model: str = DEFAULT_MODEL):
        provider_kind, real_model = _split_model(model)
        self.model_string = model
        self.provider_kind = provider_kind

        if provider_kind == "bedrock":
            self._backend: LLMProvider = _BedrockBackend(real_model)
        elif provider_kind == "openai":
            api_key = os.environ.get("OPENAI_API_KEY")
            if not api_key:
                raise LLMUnavailableError("OPENAI_API_KEY is not set")
            self._backend = _OpenAIBackend(real_model, api_key)
        elif provider_kind == "anthropic":
            api_key = os.environ.get("ANTHROPIC_API_KEY")
            if not api_key:
                raise LLMUnavailableError("ANTHROPIC_API_KEY is not set")
            self._backend = _AnthropicBackend(real_model, api_key)
        elif provider_kind == "gateway":
            api_key = os.environ.get("AI_GATEWAY_API_KEY")
            base_url = os.environ.get("AI_GATEWAY_BASE_URL", "https://ai-gateway.vercel.sh/v1")
            if not api_key:
                raise LLMUnavailableError("AI_GATEWAY_API_KEY is not set")
            self._backend = _OpenAIBackend(real_model, api_key, base_url=base_url)
        else:
            raise LLMUnavailableError(f"Unsupported provider kind: {provider_kind}")

    def complete(
        self,
        system: str,
        user: str,
        *,
        response_format: Literal["text", "json"] = "text",
        max_tokens: int = 1024,
        temperature: float = 0.7,
    ) -> LLMResponse:
        return self._backend.complete(
            system=system,
            user=user,
            response_format=response_format,
            max_tokens=max_tokens,
            temperature=temperature,
        )


def safe_llm(model: str = DEFAULT_MODEL) -> LLM | None:
    """Return an :class:`LLM` if one can be constructed, else ``None``."""
    try:
        return LLM(model=model)
    except LLMUnavailableError:
        return None


def extract_json(text: str) -> Any:
    """Parse a JSON object out of an LLM response, tolerating noise.

    LLMs (Claude in particular) often wrap structured output in markdown
    code fences (``` ```json ... ``` ```) or surround it with prose. We
    look for the first ``{ ... }`` block, fall through to a plain
    ``json.loads`` for the trivial case, and raise ``ValueError`` if
    nothing parses.
    """
    import re

    if not text or not text.strip():
        raise ValueError("empty LLM response")
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match is None:
        raise ValueError(f"no JSON object found in LLM response: {text[:200]!r}")
    return json.loads(match.group(0))


__all__ = [
    "LLM",
    "LLMResponse",
    "LLMProvider",
    "LLMUnavailableError",
    "DEFAULT_MODEL",
    "BEDROCK_ALIASES",
    "safe_llm",
    "extract_json",
    "json",  # re-exported for convenience
]
