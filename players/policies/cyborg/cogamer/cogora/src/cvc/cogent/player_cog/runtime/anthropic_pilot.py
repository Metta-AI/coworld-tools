from __future__ import annotations

import time
from typing import Any

from cvc.cogent.player_cog.provider_utils import get_default_anthropic_model
from cvc.cogent.player_cog.providers.anthropic import build_anthropic_client
from cvc.cogent.player_cog.runtime.artifacts import ArtifactStore
from cvc.cogent.player_cog.runtime.pilot_runtime_common import (
    DEFAULT_GOAL,
    DEFAULT_MAX_TOKENS,
    DEFAULT_PILOT_TIMEOUT_SECONDS,
    DEFAULT_TEMPERATURE,
    CodeModeBackend,
    PilotSession,
    SharedPilotContext,
)
from cvc.cogent.player_cog.secret_utils import resolve_api_key

__all__ = [
    "AnthropicPilotSession",
]


class _AnthropicCodeModeBackend(CodeModeBackend):
    def _request_review(self, prompt: str) -> tuple[str, str | None, int | None, int | None, float]:
        start = time.perf_counter()
        response = self._client.messages.create(
            model=self._model,
            max_tokens=self._max_tokens,
            temperature=self._temperature,
            messages=[{"role": "user", "content": prompt}],
        )
        latency_ms = (time.perf_counter() - start) * 1000
        raw_text = _response_text(response)
        stop_reason = getattr(response, "stop_reason", None)
        usage = getattr(response, "usage", None)
        input_tokens = getattr(usage, "input_tokens", None)
        output_tokens = getattr(usage, "output_tokens", None)
        return raw_text, stop_reason, input_tokens, output_tokens, latency_ms


class AnthropicPilotSession(PilotSession):
    def __init__(
        self,
        *,
        model: str | None = None,
        api_key: str | None = None,
        api_key_file: str | None = None,
        anthropic_api_key: str | None = None,
        anthropic_api_key_file: str | None = None,
        client: Any | None = None,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        temperature: float = DEFAULT_TEMPERATURE,
        goal: str = DEFAULT_GOAL,
        timeout_seconds: float = DEFAULT_PILOT_TIMEOUT_SECONDS,
        record_step_traces: bool = True,
        background_reviews: bool = False,
        shared_context: SharedPilotContext | None = None,
        artifact_store: ArtifactStore | None = None,
    ) -> None:
        resolved_api_key = resolve_api_key(
            direct_value=anthropic_api_key or api_key,
            file_path=anthropic_api_key_file or api_key_file,
            env_var="COGORA_ANTHROPIC_KEY",
        )
        resolved_client = client if client is not None else build_anthropic_client(api_key=resolved_api_key)
        backend = _AnthropicCodeModeBackend(
            client=resolved_client,
            model=model or get_default_anthropic_model(api_key=resolved_api_key),
            max_tokens=max_tokens,
            temperature=temperature,
        )
        super().__init__(
            backend=backend,
            goal=goal,
            timeout_seconds=timeout_seconds,
            record_step_traces=record_step_traces,
            background_reviews=background_reviews,
            shared_context=shared_context,
            artifact_store=artifact_store,
        )


def _response_text(response: Any) -> str:
    for block in getattr(response, "content", []):
        text = getattr(block, "text", None)
        if isinstance(text, str):
            return text
    raise ValueError("Anthropic response did not include a text block")
