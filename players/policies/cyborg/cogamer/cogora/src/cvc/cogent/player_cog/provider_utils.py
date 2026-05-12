from __future__ import annotations

import os

DEFAULT_ANTHROPIC_MODEL = "claude-sonnet-4-5"
DEFAULT_BEDROCK_MODEL = "global.anthropic.claude-sonnet-4-5-20250929-v1:0"
DEFAULT_OPENAI_MODEL = "gpt-4.1"


def _env_flag_enabled(name: str) -> bool:
    return os.getenv(name, "").lower() in {"1", "true", "yes", "on"}


def should_use_anthropic_bedrock(api_key: str | None) -> bool:
    return _env_flag_enabled("CLAUDE_CODE_USE_BEDROCK") or not api_key


def get_default_openai_model() -> str:
    model = os.getenv("OPENAI_MODEL")
    if model:
        stripped = model.strip()
        if stripped:
            return stripped
    return DEFAULT_OPENAI_MODEL


def get_default_anthropic_model(*, api_key: str | None) -> str:
    if should_use_anthropic_bedrock(api_key):
        model = os.getenv("ANTHROPIC_MODEL")
        if model:
            stripped = model.strip()
            if stripped:
                return stripped
        return DEFAULT_BEDROCK_MODEL

    return DEFAULT_ANTHROPIC_MODEL
