from __future__ import annotations

from openai import OpenAI


def build_openai_client(*, api_key: str | None) -> OpenAI:
    if api_key is None:
        raise ValueError("OpenAI API key is required")

    return OpenAI(api_key=api_key)
