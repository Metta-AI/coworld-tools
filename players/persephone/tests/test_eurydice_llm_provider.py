"""Tests for Eurydice LLM provider adapters and prompts."""

from __future__ import annotations

from agents.eurydice.llm_context import DECISION_SCHEMA_VERSION
from agents.eurydice.llm_prompts import build_prompt_parts, infer_surface
from agents.eurydice.llm_provider import BedrockHaikuProvider, make_provider


def _global_context() -> dict:
    return {
        "view": "global_chat",
        "phase": "playing",
        "legal_actions": ["hold", "send_global"],
        "runtime": {"cooldowns": {"chat": 0}},
        "players": [],
        "self": {"role": "hades", "team": "shades"},
        "strategy": {"objective": "find_partner"},
    }


def test_bedrock_provider_parses_fenced_json_decision() -> None:
    def invoke(provider, system_prompt, user_prompt):
        assert provider.model == "test.model"
        assert "Hades and Cerberus" in system_prompt
        assert "Legal actions now" in user_prompt
        return (
            "```json\n"
            "{"
            f'"schema_version":"{DECISION_SCHEMA_VERSION}",'
            '"action":"send_global",'
            '"surface":"global",'
            '"message":"HADES WHERE?",'
            '"confidence":0.82,'
            '"rationale":"ask for enemy key location"'
            "}\n"
            "```"
        )

    provider = BedrockHaikuProvider(
        model="test.model",
        max_tokens=128,
        temperature=0.0,
        timeout_seconds=1.0,
        decision_cooldown_ticks=7,
        _invoke=invoke,
    )

    decision = provider.decide(_global_context(), "unused")

    assert decision["action"] == "send_global"
    assert decision["message"] == "HADES WHERE?"
    assert decision["confidence"] == 0.82
    assert provider.decision_cooldown_ticks == 7


def test_bedrock_provider_returns_hold_on_non_json_response() -> None:
    provider = BedrockHaikuProvider(
        model="test.model",
        max_tokens=128,
        timeout_seconds=1.0,
        _invoke=lambda provider, system, user: "I would talk first.",
    )

    decision = provider.decide(_global_context(), "unused")

    assert decision["action"] == "hold"
    assert decision["confidence"] == 0.0
    assert "non-json" in decision["rationale"]


def test_bedrock_provider_clips_overlong_model_rationale() -> None:
    long_rationale = "x" * 260
    provider = BedrockHaikuProvider(
        model="test.model",
        max_tokens=128,
        timeout_seconds=1.0,
        _invoke=lambda provider, system, user: (
            "{"
            f'"schema_version":"{DECISION_SCHEMA_VERSION}",'
            '"action":"hold",'
            '"confidence":0.5,'
            f'"rationale":"{long_rationale}"'
            "}"
        ),
    )

    decision = provider.decide(_global_context(), "unused")

    assert decision["action"] == "hold"
    assert len(decision["rationale"]) == 240
    assert decision["rationale"].endswith("...")


def test_make_provider_accepts_haiku_alias() -> None:
    assert isinstance(make_provider("haiku"), BedrockHaikuProvider)
    assert isinstance(make_provider("bedrock"), BedrockHaikuProvider)


def test_prompt_surface_uses_view_legality_before_previous_mode() -> None:
    context = {
        "view": "hostage_exchange",
        "legal_actions": ["hold"],
        "runtime": {"current_mode": "probe_systematic"},
    }

    assert infer_surface(context) == "strategic"


def test_prompt_parts_include_strategy_and_context() -> None:
    system_prompt, user_prompt = build_prompt_parts(_global_context())

    assert "Other agents may use unknown policies" in system_prompt
    assert "Return exactly one JSON object" in user_prompt
    assert '"send_global"' in user_prompt
