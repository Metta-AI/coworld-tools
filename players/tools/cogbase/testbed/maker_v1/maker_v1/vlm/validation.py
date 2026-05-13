from __future__ import annotations

from collections.abc import Sequence
from typing import Any


class VlmValidationError(ValueError):
    pass


def validate_vlm_request(payload: dict[str, Any]) -> dict[str, Any]:
    _require_object(payload, "request")
    _require_const(payload, "schema_version", "maker.vlm_request.v1")
    for key in (
        "request_id",
        "guide_bundle_hash",
        "play_card_hash",
        "frame_id",
        "frame_hash",
        "run_id",
        "objective",
    ):
        _require_string(payload, key)
    for key in ("allowed_views", "allowed_actions", "retrieved_context_ids"):
        _require_string_list(payload, key)
    _require_list(payload, "recent_history")
    for index, item in enumerate(payload["recent_history"]):
        _require_object(item, f"recent_history[{index}]")
        for key in ("view", "action_id", "outcome"):
            _require_string(item, key, prefix=f"recent_history[{index}]")
    _require_object(payload.get("parser_summary"), "parser_summary")
    return payload


def validate_vlm_frame_response(
    payload: dict[str, Any],
    *,
    allowed_actions: Sequence[str] = (),
) -> dict[str, Any]:
    _require_object(payload, "response")
    _require_const(payload, "schema_version", "maker.vlm_frame.v1")
    _require_string(payload, "request_id")
    _require_string(payload, "frame_id")
    _require_classification(payload, "view")
    _require_classification(payload, "phase")
    for key in (
        "visible_text",
        "ui_elements",
        "entities",
        "state_observations",
        "available_actions",
        "parser_targets",
        "memory_updates",
        "uncertainty",
    ):
        _require_list(payload, key)
    recommended = payload.get("recommended_action")
    _require_object(recommended, "recommended_action")
    action_id = _require_string(recommended, "action_id", prefix="recommended_action")
    _require_object(recommended.get("parameters"), "recommended_action.parameters")
    _require_confidence(recommended.get("confidence"), "recommended_action.confidence")
    _require_string(recommended, "rationale", prefix="recommended_action")
    _require_string(recommended, "fallback_action_id", prefix="recommended_action")
    if allowed_actions and action_id not in allowed_actions and action_id != "unknown":
        raise VlmValidationError(f"recommended action is not allowed: {action_id}")
    novelty = payload.get("novelty")
    _require_object(novelty, "novelty")
    status = _require_string(novelty, "status", prefix="novelty")
    if status not in {"known", "variant", "new", "uncertain"}:
        raise VlmValidationError(f"invalid novelty status: {status}")
    if not isinstance(novelty.get("save_frame"), bool):
        raise VlmValidationError("novelty.save_frame must be boolean")
    _require_string(novelty, "reason", prefix="novelty")
    return payload


def build_mock_vlm_frame_response(request: dict[str, Any]) -> dict[str, Any]:
    validate_vlm_request(request)
    allowed_actions = request.get("allowed_actions", [])
    fallback = _fallback_action(allowed_actions)
    return {
        "schema_version": "maker.vlm_frame.v1",
        "request_id": request["request_id"],
        "frame_id": request["frame_id"],
        "view": {"id": "unknown", "confidence": 0.0, "evidence": ["mock adapter"]},
        "phase": {"id": "unknown", "confidence": 0.0, "evidence": ["mock adapter"]},
        "visible_text": [],
        "ui_elements": [],
        "entities": [],
        "state_observations": [],
        "available_actions": [
            {"action_id": action_id, "confidence": 0.0, "evidence": ["guide action registry"]}
            for action_id in allowed_actions
        ],
        "recommended_action": {
            "action_id": fallback,
            "parameters": {},
            "confidence": 0.0,
            "rationale": "Mock VLM adapter returns the safest guide-derived fallback.",
            "fallback_action_id": fallback,
        },
        "novelty": {
            "status": "uncertain",
            "save_frame": True,
            "reason": "Mock adapter cannot inspect pixels.",
        },
        "parser_targets": [
            {
                "target": "view_classifier",
                "why": "Visual frame was not parsed by a deterministic classifier.",
                "suggested_test": "Add this frame as a fixture before parser promotion.",
            }
        ],
        "memory_updates": [],
        "uncertainty": [
            {
                "field": "view",
                "reason": "Mock adapter does not perform visual inference.",
                "needed_next": "Run a real VLM adapter or add a deterministic fixture label.",
            }
        ],
    }


def _fallback_action(actions: Sequence[str]) -> str:
    for candidate in ("noop", "stay", "wait"):
        if candidate in actions:
            return candidate
    return actions[0] if actions else "unknown"


def _require_object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise VlmValidationError(f"{label} must be an object")
    return value


def _require_const(payload: dict[str, Any], key: str, expected: str) -> None:
    actual = payload.get(key)
    if actual != expected:
        raise VlmValidationError(f"{key} must be {expected!r}, got {actual!r}")


def _require_string(payload: dict[str, Any], key: str, *, prefix: str | None = None) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value:
        label = f"{prefix}.{key}" if prefix else key
        raise VlmValidationError(f"{label} must be a non-empty string")
    return value


def _require_string_list(payload: dict[str, Any], key: str) -> list[str]:
    value = _require_list(payload, key)
    if not all(isinstance(item, str) for item in value):
        raise VlmValidationError(f"{key} must contain only strings")
    return value


def _require_list(payload: dict[str, Any], key: str) -> list[Any]:
    value = payload.get(key)
    if not isinstance(value, list):
        raise VlmValidationError(f"{key} must be a list")
    return value


def _require_classification(payload: dict[str, Any], key: str) -> None:
    value = payload.get(key)
    _require_object(value, key)
    _require_string(value, "id", prefix=key)
    _require_confidence(value.get("confidence"), f"{key}.confidence")
    evidence = value.get("evidence")
    if not isinstance(evidence, list) or not all(isinstance(item, str) for item in evidence):
        raise VlmValidationError(f"{key}.evidence must be a string list")


def _require_confidence(value: Any, label: str) -> None:
    if not isinstance(value, int | float) or value < 0.0 or value > 1.0:
        raise VlmValidationError(f"{label} must be between 0.0 and 1.0")
