from __future__ import annotations

import time
from typing import Any

from cvc.cogent.player_cog.provider_utils import get_default_openai_model
from cvc.cogent.player_cog.providers.openai import build_openai_client
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
    "OpenAIPilotSession",
]


class _OpenAICodeModeBackend(CodeModeBackend):
    def _request_review(self, prompt: str) -> tuple[str, str | None, int | None, int | None, float]:
        start = time.perf_counter()
        response = self._client.chat.completions.create(
            model=self._model,
            max_completion_tokens=self._max_tokens,
            temperature=self._temperature,
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
        )
        latency_ms = (time.perf_counter() - start) * 1000
        raw_text = response.choices[0].message.content or ""
        finish_reason = response.choices[0].finish_reason
        usage = response.usage
        input_tokens = getattr(usage, "prompt_tokens", None) if usage is not None else None
        output_tokens = getattr(usage, "completion_tokens", None) if usage is not None else None
        return raw_text, finish_reason, input_tokens, output_tokens, latency_ms


class OpenAIPilotSession(PilotSession):
    def __init__(
        self,
        *,
        model: str | None = None,
        api_key: str | None = None,
        api_key_file: str | None = None,
        openai_api_key: str | None = None,
        openai_api_key_file: str | None = None,
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
            direct_value=openai_api_key or api_key,
            file_path=openai_api_key_file or api_key_file,
            env_var="OPENAI_API_KEY",
        )
        resolved_client = client if client is not None else build_openai_client(api_key=resolved_api_key)
        backend = _OpenAICodeModeBackend(
            client=resolved_client,
            model=model or get_default_openai_model(),
            max_tokens=max_tokens,
            temperature=temperature,
        )
        super().__init__(
            backend=backend,
            goal=goal,
            artifact_store=artifact_store,
            timeout_seconds=timeout_seconds,
            record_step_traces=record_step_traces,
            background_reviews=background_reviews,
            shared_context=shared_context,
        )
