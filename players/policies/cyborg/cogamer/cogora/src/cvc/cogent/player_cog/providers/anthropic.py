from __future__ import annotations

import os

from anthropic import Anthropic, AnthropicBedrock

from cvc.cogent.player_cog.provider_utils import should_use_anthropic_bedrock


def build_anthropic_client(*, api_key: str | None) -> Anthropic | AnthropicBedrock:
    if should_use_anthropic_bedrock(api_key):
        return AnthropicBedrock(
            aws_profile=os.getenv("AWS_PROFILE"),
            aws_region=os.getenv("AWS_REGION", os.getenv("AWS_DEFAULT_REGION")),
        )

    if api_key is None:
        raise ValueError("Anthropic API key is required when Bedrock is disabled")

    return Anthropic(api_key=api_key)
