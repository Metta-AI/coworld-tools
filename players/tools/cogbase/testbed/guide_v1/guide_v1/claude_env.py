from __future__ import annotations

import os
from collections.abc import Mapping


_PRESERVE_KEYS = (
    "CLAUDE_CODE_USE_BEDROCK",
    "ANTHROPIC_MODEL",
    "ANTHROPIC_SMALL_FAST_MODEL",
)


def bedrock_subprocess_env(
    base_env: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Return a subprocess env that forces the Claude CLI to use AWS Bedrock.

    Sets ``CLAUDE_CODE_USE_BEDROCK=1`` unconditionally and removes inherited
    provider/auth variables that could let the subprocess fall back to the
    public Anthropic API or Vertex AI. Callers should still ensure AWS
    credentials (and a region) are available through the normal AWS
    credential chain.

    Also sets ``CMUX_PRESERVE_CLAUDE_AUTH_SELECTION_ENV=1`` and a matching
    allow-list so the cmux ``claude`` wrapper (which would otherwise strip
    provider-selection vars from its child env) preserves the Bedrock signal.
    Outside cmux those variables are inert.
    """

    env: dict[str, str] = dict(base_env if base_env is not None else os.environ)

    env["CLAUDE_CODE_USE_BEDROCK"] = "1"
    env["CMUX_PRESERVE_CLAUDE_AUTH_SELECTION_ENV"] = "1"
    env["CMUX_PRESERVE_CLAUDE_AUTH_SELECTION_ENV_KEYS"] = ",".join(_PRESERVE_KEYS)

    for key in (
        "ANTHROPIC_API_KEY",
        "ANTHROPIC_AUTH_TOKEN",
        "CLAUDE_CODE_USE_VERTEX",
    ):
        env.pop(key, None)

    return env
