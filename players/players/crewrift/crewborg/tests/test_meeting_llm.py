"""Meeting LLM provider selection tests."""

from __future__ import annotations

import sys
from types import SimpleNamespace

from players.crewrift.crewborg.strategy.meeting.llm import (
    AnthropicMeetingClient,
    DEFAULT_BEDROCK_MEETING_MODEL,
    DEFAULT_MEETING_MODEL,
    build_meeting_llm_client_from_env,
)


def test_use_bedrock_enables_meeting_llm_without_anthropic_api_key(monkeypatch) -> None:
    calls: list[dict[str, object]] = []

    class FakeAnthropicBedrock:
        def __init__(self, **kwargs: object) -> None:
            calls.append(kwargs)

    monkeypatch.setitem(
        sys.modules, "anthropic", SimpleNamespace(AnthropicBedrock=FakeAnthropicBedrock)
    )

    client = build_meeting_llm_client_from_env(
        {
            "USE_BEDROCK": "true",
            "AWS_REGION": "us-east-1",
        }
    )

    assert client.enabled
    assert isinstance(client, AnthropicMeetingClient)
    assert client.config.model == DEFAULT_BEDROCK_MEETING_MODEL
    assert calls[0]["aws_region"] == "us-east-1"


def test_claude_code_bedrock_alone_does_not_enable_meeting_llm() -> None:
    client = build_meeting_llm_client_from_env(
        {"CLAUDE_CODE_USE_BEDROCK": "1", "AWS_REGION": "us-east-1"}
    )

    assert not client.enabled
    assert (
        client.disabled_reason == "CREWBORG_LLM_MEETINGS or USE_BEDROCK is not enabled"
    )


def test_crewborg_llm_meetings_can_force_bedrock(monkeypatch) -> None:
    calls: list[dict[str, object]] = []

    class FakeAnthropicBedrock:
        def __init__(self, **kwargs: object) -> None:
            calls.append(kwargs)

    monkeypatch.setitem(
        sys.modules, "anthropic", SimpleNamespace(AnthropicBedrock=FakeAnthropicBedrock)
    )

    client = build_meeting_llm_client_from_env(
        {
            "CREWBORG_LLM_MEETINGS": "1",
            "CLAUDE_CODE_USE_BEDROCK": "1",
            "AWS_DEFAULT_REGION": "us-west-2",
            "BEDROCK_MODEL": "us.anthropic.test-model-v1:0",
        }
    )

    assert client.enabled
    assert isinstance(client, AnthropicMeetingClient)
    assert client.config.model == "us.anthropic.test-model-v1:0"
    assert calls[0]["aws_region"] == "us-west-2"


def test_crewborg_llm_meetings_uses_direct_anthropic_when_api_key_is_set(
    monkeypatch,
) -> None:
    calls: list[dict[str, object]] = []

    class FakeAnthropic:
        def __init__(self, **kwargs: object) -> None:
            calls.append(kwargs)

    monkeypatch.setitem(
        sys.modules, "anthropic", SimpleNamespace(Anthropic=FakeAnthropic)
    )

    client = build_meeting_llm_client_from_env(
        {
            "CREWBORG_LLM_MEETINGS": "true",
            "ANTHROPIC_API_KEY": "test-key",
        }
    )

    assert client.enabled
    assert isinstance(client, AnthropicMeetingClient)
    assert client.config.model == DEFAULT_MEETING_MODEL
    assert calls[0]["api_key"] == "test-key"


def test_crewborg_llm_system_prompt_can_be_loaded_from_file(
    monkeypatch, tmp_path
) -> None:
    calls: list[dict[str, object]] = []

    class FakeAnthropic:
        def __init__(self, **kwargs: object) -> None:
            calls.append(kwargs)

    system_path = tmp_path / "system.md"
    system_path.write_text("custom meeting system", encoding="utf-8")
    monkeypatch.setitem(
        sys.modules, "anthropic", SimpleNamespace(Anthropic=FakeAnthropic)
    )

    client = build_meeting_llm_client_from_env(
        {
            "CREWBORG_LLM_MEETINGS": "true",
            "ANTHROPIC_API_KEY": "test-key",
            "CREWBORG_LLM_SYSTEM_PROMPT_PATH": str(system_path),
        }
    )

    assert client.enabled
    assert isinstance(client, AnthropicMeetingClient)
    assert client.config.system_prompt == "custom meeting system"
