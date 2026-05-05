"""LLM interface for the Orpheus agent's slow decision loop.

Provides a configurable abstraction over LLM providers. The slow loop
calls decide() with a belief snapshot; the LLM returns a task
selection.

Supported providers:
  - "anthropic" -- Claude via the Anthropic API (requires ANTHROPIC_API_KEY)
  - "openai" -- GPT via the OpenAI API (requires OPENAI_API_KEY)
  - "bedrock" -- Claude via AWS Bedrock (requires AWS credentials)
  - "stub" -- Deterministic stub for testing (no network calls)

The provider and model are configurable via constructor args or
environment variables (ORPHEUS_LLM_PROVIDER, ORPHEUS_LLM_MODEL).
"""

from __future__ import annotations

import json
import logging
import os
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass

from belief import BeliefSnapshot
from tasks import TaskParams, TaskType

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# LLM response parsing
# ---------------------------------------------------------------------------


@dataclass
class LLMDecision:
    """Parsed output from an LLM decision call."""

    task: TaskParams
    reasoning: str = ""
    raw_response: str = ""
    latency_ms: float = 0.0


def parse_llm_response(raw: str) -> TaskParams:
    """Parse the LLM's JSON response into task params.

    Expected format:
    {
        "task": "explore",
        "target_x": 50,         // optional
        "target_y": 50,         // optional
        "target_color": 3,      // optional
        "message": "hello",     // optional
        "reasoning": "..."      // optional, for logging
    }

    Falls back to IDLE if parsing fails.
    """
    try:
        # Try to extract JSON from the response (may be wrapped in markdown)
        json_str = raw.strip()
        if "```json" in json_str:
            json_str = json_str.split("```json")[1].split("```")[0].strip()
        elif "```" in json_str:
            json_str = json_str.split("```")[1].split("```")[0].strip()

        data = json.loads(json_str)
    except (json.JSONDecodeError, IndexError):
        logger.warning("Failed to parse LLM response as JSON: %s", raw[:200])
        return TaskParams(type=TaskType.IDLE)

    # Map string to enum
    action_str = data.get("task", "idle").lower()
    try:
        action_type = TaskType(action_str)
    except ValueError:
        logger.warning("Unknown task type from LLM: %s", action_str)
        action_type = TaskType.IDLE

    return TaskParams(
        type=action_type,
        target_x=data.get("target_x"),
        target_y=data.get("target_y"),
        target_color=data.get("target_color"),
        message=data.get("message"),
    )


# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """\
You are a strategic agent playing Persephone's Escape, a social deduction game.

Your team wins by completing a mutual role exchange (R.OFFER + R.ACCPT) between \
your team's key role pair inside a chatroom. Hades + Cerberus are the Shades key \
pair; Persephone + Demeter are the Nymphs key pair.

You must choose a high-level task based on the current game state. \
Respond with a JSON object specifying your chosen task and any parameters.

Available tasks:
- "idle" -- Do nothing (wait)
- "explore" -- Wander the room to find other players
- "move_to" -- Move to coordinates {"target_x": N, "target_y": N}
- "pursue_player" -- Follow a player {"target_color": N}
- "open_chatroom" -- Approach a player and create/request chatroom {"target_color": N}
- "offer_role_exchange" -- Offer role exchange (must be in chatroom)
- "accept_role_exchange" -- Accept a pending role exchange offer (must be in chatroom)
- "chat_and_observe" -- Stay in chatroom and observe/send message {"message": "text"}
- "exit_chatroom" -- Leave the current chatroom
- "shout" -- Send a global message {"message": "text"}
- "check_info" -- Open info screen to see known players

Respond ONLY with a JSON object:
{
    "task": "<task_name>",
    "target_x": <optional int>,
    "target_y": <optional int>,
    "target_color": <optional int>,
    "message": "<optional string>",
    "reasoning": "<brief explanation of your strategic thinking>"
}
"""


# ---------------------------------------------------------------------------
# Provider base class
# ---------------------------------------------------------------------------


class LLMProvider(ABC):
    """Base class for LLM provider implementations."""

    @abstractmethod
    def complete(self, system: str, user: str) -> str:
        """Send a completion request and return the response text.

        Args:
            system: System prompt.
            user: User message (the belief state context + instruction).

        Returns:
            Raw response text from the LLM.

        Raises:
            LLMError: If the request fails.
        """

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Human-readable provider name for logging."""


class LLMError(Exception):
    """Raised when an LLM call fails."""


# ---------------------------------------------------------------------------
# Provider implementations
# ---------------------------------------------------------------------------


class AnthropicProvider(LLMProvider):
    """Claude via the Anthropic API."""

    def __init__(self, model: str = "claude-sonnet-4-20250514") -> None:
        self.model = model
        self._api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not self._api_key:
            raise LLMError(
                "ANTHROPIC_API_KEY not set. Required for Anthropic provider."
            )

    @property
    def provider_name(self) -> str:
        return f"anthropic/{self.model}"

    def complete(self, system: str, user: str) -> str:
        try:
            import anthropic
        except ImportError as e:
            raise LLMError("anthropic package not installed: pip install anthropic") from e

        client = anthropic.Anthropic(api_key=self._api_key)
        response = client.messages.create(
            model=self.model,
            max_tokens=512,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        return response.content[0].text


class OpenAIProvider(LLMProvider):
    """GPT via the OpenAI API."""

    def __init__(self, model: str = "gpt-4o-mini") -> None:
        self.model = model
        self._api_key = os.environ.get("OPENAI_API_KEY")
        if not self._api_key:
            raise LLMError("OPENAI_API_KEY not set. Required for OpenAI provider.")

    @property
    def provider_name(self) -> str:
        return f"openai/{self.model}"

    def complete(self, system: str, user: str) -> str:
        try:
            import openai
        except ImportError as e:
            raise LLMError("openai package not installed: pip install openai") from e

        client = openai.OpenAI(api_key=self._api_key)
        response = client.chat.completions.create(
            model=self.model,
            max_tokens=512,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )
        return response.choices[0].message.content or ""


class BedrockProvider(LLMProvider):
    """Claude via AWS Bedrock."""

    def __init__(self, model: str = "anthropic.claude-3-haiku-20240307-v1:0") -> None:
        self.model = model

    @property
    def provider_name(self) -> str:
        return f"bedrock/{self.model}"

    def complete(self, system: str, user: str) -> str:
        try:
            import boto3
        except ImportError as e:
            raise LLMError("boto3 package not installed: pip install boto3") from e

        client = boto3.client("bedrock-runtime")
        body = json.dumps({
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": 512,
            "system": system,
            "messages": [{"role": "user", "content": user}],
        })

        response = client.invoke_model(
            modelId=self.model,
            contentType="application/json",
            accept="application/json",
            body=body,
        )
        result = json.loads(response["body"].read())
        return result["content"][0]["text"]


class StubProvider(LLMProvider):
    """Deterministic stub for testing without network calls.

    Always returns EXPLORE. Useful for integration testing the
    dual-loop architecture without LLM latency or API keys.
    """

    def __init__(self, model: str = "stub") -> None:
        self.model = model
        self._call_count = 0

    @property
    def provider_name(self) -> str:
        return "stub"

    def complete(self, system: str, user: str) -> str:
        self._call_count += 1
        # Cycle through a simple strategy for testing
        actions = ["explore", "explore", "check_info", "explore"]
        action = actions[self._call_count % len(actions)]
        return json.dumps({
            "task": action,
            "reasoning": f"stub decision #{self._call_count}",
        })


# ---------------------------------------------------------------------------
# Provider factory
# ---------------------------------------------------------------------------

_PROVIDERS: dict[str, type[LLMProvider]] = {
    "anthropic": AnthropicProvider,
    "openai": OpenAIProvider,
    "bedrock": BedrockProvider,
    "stub": StubProvider,
}


def create_provider(provider: str, model: str | None = None) -> LLMProvider:
    """Create an LLM provider instance.

    Args:
        provider: Provider name ("anthropic", "openai", "bedrock", "stub").
        model: Model identifier. Uses provider-specific default if None.

    Returns:
        Configured LLMProvider instance.

    Raises:
        LLMError: If the provider is unknown or misconfigured.
    """
    provider = provider.lower()
    if provider not in _PROVIDERS:
        available = ", ".join(sorted(_PROVIDERS))
        raise LLMError(f"Unknown LLM provider '{provider}'. Available: {available}")

    cls = _PROVIDERS[provider]
    if model:
        return cls(model=model)
    return cls()


# ---------------------------------------------------------------------------
# Decision function (called by the slow loop)
# ---------------------------------------------------------------------------


def make_decision(
    provider: LLMProvider,
    snapshot: BeliefSnapshot,
) -> LLMDecision:
    """Query the LLM for a task decision.

    Serializes the belief snapshot into a prompt, calls the LLM, and
    parses the response into a TaskParams.

    Args:
        provider: The configured LLM provider to use.
        snapshot: Current belief state snapshot.

    Returns:
        LLMDecision with the parsed task and metadata.
    """
    user_message = (
        "Current game state:\n"
        f"{snapshot.to_prompt_context()}\n\n"
        f"Current task will be replaced by your choice. "
        f"What should I do next? Respond with JSON only."
    )

    start = time.monotonic()
    try:
        raw = provider.complete(SYSTEM_PROMPT, user_message)
    except Exception as e:
        logger.error("LLM call failed: %s", e)
        return LLMDecision(
            task=TaskParams(type=TaskType.IDLE),
            reasoning=f"LLM error: {e}",
            raw_response="",
            latency_ms=0.0,
        )
    latency_ms = (time.monotonic() - start) * 1000

    params = parse_llm_response(raw)

    # Extract reasoning if present
    reasoning = ""
    try:
        data = json.loads(raw.strip())
        reasoning = data.get("reasoning", "")
    except (json.JSONDecodeError, AttributeError):
        pass

    return LLMDecision(
        task=params,
        reasoning=reasoning,
        raw_response=raw,
        latency_ms=latency_ms,
    )
