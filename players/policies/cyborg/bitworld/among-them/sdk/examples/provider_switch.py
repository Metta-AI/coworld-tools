"""Switch LLM provider per cognitive module.

The SDK defaults to AWS Bedrock (``claude-sonnet`` alias). This example
shows how to mix providers — a Bedrock voter alongside an Anthropic
direct-API chatter — and how each module independently degrades to its
scripted fallback when its provider isn't configured.

Provider strings follow ``among_them_sdk.cognition.llm`` routing:
  "claude-sonnet"                -> Bedrock (default alias)
  "claude-haiku"                 -> Bedrock (default alias)
  "bedrock/<inference-profile>"  -> Bedrock (explicit, full ID)
  "gpt-5.5"                      -> OpenAI direct API
  "openai/gpt-5.5"               -> OpenAI (explicit)
  "anthropic/claude-sonnet-4-5"  -> Anthropic direct API

Run:
  uv run python examples/provider_switch.py
"""

from __future__ import annotations

import logging
import os

from among_them_sdk import Agent, LLMChatter, LLMVoter

logging.getLogger("among_them_sdk").setLevel(logging.WARNING)


def _provider_status(env_var: str, label: str) -> str:
    return f"{label}: {'live' if os.environ.get(env_var) else 'no key (will degrade)'}"


def _bedrock_status() -> str:
    profile = os.environ.get("AWS_PROFILE")
    region = os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION") or "us-east-1"
    if profile or os.environ.get("AWS_ACCESS_KEY_ID"):
        return f"AWS_BEDROCK     : live (profile={profile or '<keys>'}, region={region})"
    return "AWS_BEDROCK     : no AWS creds (will degrade)"


def main() -> None:
    print(_bedrock_status())
    print(_provider_status("OPENAI_API_KEY", "OPENAI_API_KEY  "))
    print(_provider_status("ANTHROPIC_API_KEY", "ANTHROPIC_API_KEY"))
    print()

    voter = LLMVoter(model="claude-sonnet")  # Bedrock by default
    chatter = LLMChatter(model="claude-haiku", tone="suspicious")  # Bedrock by default

    voter_status = "LLM" if voter.llm is not None else "scripted-fallback"
    chatter_status = "LLM" if chatter.llm is not None else "scripted-fallback"

    print(f"voter   -> claude-sonnet (bedrock) [{voter_status}]")
    print(f"chatter -> claude-haiku  (bedrock) [{chatter_status}]")
    print()

    agent = Agent.create(
        voter=voter,
        chatter=chatter,
        use_llm_for_instructions=False,
        seed=42,
    )
    result = agent.run(rounds=1)
    print(result.summary)
    if result.chat_messages:
        print("first chat:", result.chat_messages[0])


if __name__ == "__main__":
    main()
