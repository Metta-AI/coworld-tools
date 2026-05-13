from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class ActionValidation:
    action_id: str
    valid: bool
    fallback_action_id: str
    reason: str

    def as_dict(self) -> dict[str, object]:
        return {
            "action_id": self.action_id,
            "valid": self.valid,
            "fallback_action_id": self.fallback_action_id,
            "reason": self.reason,
        }


def validate_recommended_action(
    response: dict[str, Any],
    *,
    allowed_actions: Sequence[str],
    fallback_action_id: str | None = None,
) -> ActionValidation:
    fallback = _fallback_action(allowed_actions, fallback_action_id)
    recommended = response.get("recommended_action")
    if not isinstance(recommended, dict):
        return ActionValidation(
            action_id=fallback,
            valid=False,
            fallback_action_id=fallback,
            reason="recommended_action missing or invalid",
        )

    action_id = recommended.get("action_id")
    if not isinstance(action_id, str) or not action_id:
        return ActionValidation(
            action_id=fallback,
            valid=False,
            fallback_action_id=fallback,
            reason="recommended action id missing",
        )
    if action_id not in allowed_actions:
        return ActionValidation(
            action_id=fallback,
            valid=False,
            fallback_action_id=fallback,
            reason=f"recommended action not allowed: {action_id}",
        )
    return ActionValidation(
        action_id=action_id,
        valid=True,
        fallback_action_id=fallback,
        reason="recommended action allowed",
    )


def _fallback_action(allowed_actions: Sequence[str], explicit: str | None) -> str:
    if explicit in allowed_actions:
        return str(explicit)
    for candidate in ("noop", "stay", "wait"):
        if candidate in allowed_actions:
            return candidate
    return allowed_actions[0] if allowed_actions else "unknown"
