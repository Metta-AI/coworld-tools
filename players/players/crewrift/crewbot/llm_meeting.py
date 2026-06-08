from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

DEFAULT_DIRECT_MODEL = "claude-haiku-4-5-20251001"
DEFAULT_BEDROCK_MODEL = "us.anthropic.claude-haiku-4-5-20251001-v1:0"
DEFAULT_TIMEOUT_SECONDS = 5.0
DEFAULT_MAX_TOKENS = 160
DEFAULT_TEMPERATURE = 0.0
DEFAULT_MIN_SUBMIT_CONFIDENCE = 0.75
CHAT_MAX_CHARS = 160


def main() -> None:
    context = json.loads(sys.stdin.read())
    print(json.dumps(decide(context), separators=(",", ":")), flush=True)


def decide(context: dict[str, Any]) -> dict[str, Any]:
    if not _enabled():
        return _fallback("llm disabled")
    use_bedrock = _flag("USE_BEDROCK") or _flag("CLAUDE_CODE_USE_BEDROCK")
    if not use_bedrock and not os.environ.get("ANTHROPIC_API_KEY"):
        return _fallback("ANTHROPIC_API_KEY is not set")

    from anthropic import Anthropic, AnthropicBedrock

    timeout = float(os.environ.get("CREWBOT_LLM_TIMEOUT_SECONDS", str(DEFAULT_TIMEOUT_SECONDS)))
    if use_bedrock:
        client = AnthropicBedrock(
            aws_access_key=os.environ.get("AWS_ACCESS_KEY_ID"),
            aws_secret_key=os.environ.get("AWS_SECRET_ACCESS_KEY"),
            aws_session_token=os.environ.get("AWS_SESSION_TOKEN"),
            aws_region=os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION"),
            aws_profile=os.environ.get("AWS_PROFILE"),
            timeout=timeout,
        )
        model = os.environ.get("CREWBOT_LLM_MODEL") or os.environ.get(
            "BEDROCK_MODEL", DEFAULT_BEDROCK_MODEL
        )
    else:
        client = Anthropic(
            api_key=os.environ["ANTHROPIC_API_KEY"],
            timeout=timeout,
        )
        model = os.environ.get("CREWBOT_LLM_MODEL", DEFAULT_DIRECT_MODEL)

    response = client.messages.create(
        model=model,
        max_tokens=int(os.environ.get("CREWBOT_LLM_MAX_TOKENS", str(DEFAULT_MAX_TOKENS))),
        temperature=float(os.environ.get("CREWBOT_LLM_TEMPERATURE", str(DEFAULT_TEMPERATURE))),
        system=_system_prompt(),
        messages=[
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "context": context,
                        "response_schema": {
                            "schema_version": 1,
                            "action": "send_chat | set_tentative_vote | submit_vote | wait",
                            "chat_text": "string",
                            "vote_target": "legal player color, skip, or empty string",
                            "reason": "short rationale",
                            "confidence": "0.0 to 1.0",
                        },
                    },
                    sort_keys=True,
                    separators=(",", ":"),
                ),
            }
        ],
    )
    return _validate_decision(_extract_json(_response_text(response)), context)


def _enabled() -> bool:
    return (
        _flag("CREWBOT_LLM_MEETINGS")
        or _flag("USE_BEDROCK")
        or _flag("CLAUDE_CODE_USE_BEDROCK")
    )


def _flag(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def _system_prompt() -> str:
    path = os.environ.get("CREWBOT_LLM_SYSTEM_PROMPT_PATH")
    if path:
        return Path(path).read_text(encoding="utf-8")
    return (
        "You control one Crewbot Crewrift player during a meeting. "
        "Return exactly one JSON object. Use only legal vote targets. "
        "Prefer concrete observations over generic suspicion."
    )


def _response_text(response: Any) -> str:
    parts: list[str] = []
    for block in getattr(response, "content", []) or []:
        text = getattr(block, "text", None)
        if isinstance(text, str):
            parts.append(text)
        elif isinstance(block, dict) and isinstance(block.get("text"), str):
            parts.append(block["text"])
        elif isinstance(block, str):
            parts.append(block)
    return "".join(parts).strip()


def _extract_json(text: str) -> dict[str, Any]:
    first = text.find("{")
    last = text.rfind("}")
    if first < 0 or last < first:
        raise ValueError(f"response did not contain JSON object: {text!r}")
    value = json.loads(text[first : last + 1])
    if not isinstance(value, dict):
        raise ValueError("response JSON was not an object")
    return value


def _validate_decision(
    raw: dict[str, Any],
    context: dict[str, Any],
) -> dict[str, Any]:
    legal = {
        str(item).strip().lower()
        for item in context["constraints"]["valid_vote_targets"]
    }
    fallback_vote = str(context["state"]["fallback_vote"]).strip().lower()

    action = str(raw.get("action", "wait")).strip()
    if action not in {"send_chat", "set_tentative_vote", "submit_vote", "wait"}:
        action = "wait"

    chat_text = _sanitize_chat(raw.get("chat_text", ""))
    vote_target = str(raw.get("vote_target", "") or "").strip().lower()
    confidence = _confidence(raw.get("confidence"))
    if action == "submit_vote" and not vote_target:
        vote_target = fallback_vote
    if vote_target and vote_target not in legal:
        vote_target = ""
        if action in {"set_tentative_vote", "submit_vote"}:
            action = "wait"
    if action == "submit_vote" and (confidence is None or confidence < _min_submit_confidence()):
        action = "set_tentative_vote"
    if action == "send_chat" and not chat_text:
        action = "wait"
    if action == "set_tentative_vote" and not vote_target:
        action = "wait"

    return {
        "schema_version": 1,
        "action": action,
        "chat_text": chat_text,
        "vote_target": vote_target,
        "reason": _sanitize_chat(raw.get("reason", "")),
        "confidence": confidence,
    }


def _sanitize_chat(value: Any) -> str:
    text = "" if value is None else str(value)
    return "".join(ch for ch in text if " " <= ch <= "~").strip()[:CHAT_MAX_CHARS]


def _confidence(value: Any) -> float | None:
    if value is None:
        return None
    confidence = float(value)
    return max(0.0, min(1.0, confidence))


def _min_submit_confidence() -> float:
    return float(
        os.environ.get(
            "CREWBOT_LLM_MIN_SUBMIT_CONFIDENCE",
            str(DEFAULT_MIN_SUBMIT_CONFIDENCE),
        )
    )


def _fallback(reason: str) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "action": "wait",
        "chat_text": "",
        "vote_target": "",
        "reason": _sanitize_chat(reason),
        "confidence": 0.0,
    }


if __name__ == "__main__":
    main()
