from __future__ import annotations

import json
import re
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError

_FENCED_BLOCK_RE = re.compile(r"^```(?:json)?\n(?P<body>.*)\n```$", re.DOTALL)


class CodeReviewRequest(BaseModel):
    agent_id: int
    step: int
    goal: str = ""
    trigger_name: str = ""
    prompt: str
    current_main_source: str = ""
    current_plan: str = ""
    current_scratchpad: str = ""
    experience_tail: str = ""
    decision_log_tail: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


class CodeReviewResponse(BaseModel):
    action: Literal["none", "memory", "policy", "memory_and_policy"] = "none"
    set_policy: str | None = None
    replace_scratchpad: str | None = None
    replace_plan: str | None = None
    review_summary: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


def coerce_code_review_response(raw_response: str | dict[str, Any] | CodeReviewResponse) -> CodeReviewResponse:
    if isinstance(raw_response, CodeReviewResponse):
        return raw_response
    if isinstance(raw_response, dict):
        return CodeReviewResponse.model_validate(_normalize_code_review_payload(raw_response))

    text = _strip_fenced_block(raw_response.strip())
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        parsed = _parse_wrapped_json_object(text)
    if not isinstance(parsed, dict):
        raise ValueError("Code review response did not contain a JSON object")
    try:
        return CodeReviewResponse.model_validate(_normalize_code_review_payload(parsed))
    except ValidationError as err:
        raise ValueError("Code review response did not match expected schema") from err


def _strip_fenced_block(text: str) -> str:
    match = _FENCED_BLOCK_RE.match(text)
    if match is None:
        return text
    return match.group("body").strip()


def _parse_wrapped_json_object(text: str) -> dict[str, Any] | None:
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end <= start:
        return None
    try:
        parsed = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return None
    if isinstance(parsed, dict):
        return parsed
    return None


def _normalize_code_review_payload(payload: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(payload)
    policy_source = _extract_text_payload(normalized.get("set_policy"))
    normalized["set_policy"] = policy_source

    plan_text = _extract_text_payload(normalized.get("replace_plan"))
    normalized["replace_plan"] = plan_text

    scratchpad_text = _extract_text_payload(normalized.get("replace_scratchpad"))
    normalized["replace_scratchpad"] = scratchpad_text

    normalized["action"] = _normalize_action(
        has_policy=policy_source is not None,
        has_memory=scratchpad_text is not None or plan_text is not None,
    )
    if not isinstance(normalized.get("review_summary"), str):
        normalized["review_summary"] = ""
    if not isinstance(normalized.get("metadata"), dict):
        normalized["metadata"] = {}
    return normalized


def _extract_text_payload(value: Any) -> str | None:
    if isinstance(value, str):
        text = value.strip()
        return text or None
    return None


def _normalize_action(*, has_policy: bool, has_memory: bool) -> str:
    if has_policy and has_memory:
        return "memory_and_policy"
    if has_policy:
        return "policy"
    if has_memory:
        return "memory"
    return "none"
