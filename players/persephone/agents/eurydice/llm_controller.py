"""Runtime orchestration for optional Eurydice LLM control."""

from __future__ import annotations

from typing import Any

from orpheus.belief_state import BeliefState
from orpheus.logging import LogLevel
from orpheus.mode import ModeDirective

from agents.eurydice.llm_context import build_llm_context
from agents.eurydice.llm_executor import directive_for_decision
from agents.eurydice.llm_prompts import build_prompt, infer_surface
from agents.eurydice.llm_provider import make_provider
from agents.eurydice.llm_validator import (
    hash_llm_context,
    validate_and_trace_llm_decision,
)
from agents.eurydice.log import logger
from agents.eurydice.strategic_state import StrategicState


LLM_CONTROL_MODES = {"off", "shadow", "targets", "whispers", "all"}
LLM_PROVIDER_STATE_KEY = "_eurydice_llm_provider_state"


def maybe_override_directive(
    belief_state: BeliefState,
    strategic_state: StrategicState,
    fallback: ModeDirective,
    *,
    control_mode: str = "off",
    provider_name: str = "hold",
) -> ModeDirective:
    """Return a model-selected directive when explicitly enabled and safe."""

    control_mode = (control_mode or "off").strip().lower()
    if control_mode not in LLM_CONTROL_MODES or control_mode == "off":
        return fallback

    context = build_llm_context(belief_state, strategic_state)
    provider = make_provider(provider_name)
    context_hash = hash_llm_context(context)
    if _provider_cooldown_active(
        belief_state,
        provider=provider,
        control_mode=control_mode,
        context=context,
    ):
        _trace_directive_ignored(
            fallback,
            {"action": "hold"},
            "provider_cooldown",
            context_hash,
            reasons=[f"cooldown_ticks={_provider_cooldown_ticks(provider)}"],
        )
        return fallback

    prompt = build_prompt(context)
    raw_decision = provider.decide(context, prompt)
    _record_provider_call(
        belief_state,
        provider=provider,
        control_mode=control_mode,
        context=context,
        context_hash=context_hash,
    )
    result = validate_and_trace_llm_decision(
        belief_state,
        raw_decision,
        context=context,
        fallback_action="hold",
        source=f"runtime:{control_mode}:{provider.name}",
    )

    if control_mode == "shadow":
        _trace_directive_ignored(
            fallback,
            raw_decision,
            "shadow_mode",
            result.context_hash,
        )
        return fallback

    if not result.accepted:
        _trace_directive_ignored(
            fallback,
            raw_decision,
            "validation_rejected",
            result.context_hash,
            reasons=result.reasons,
        )
        return fallback

    if result.decision.get("action") == "hold":
        _trace_directive_ignored(
            fallback,
            raw_decision,
            "hold_uses_fallback",
            result.context_hash,
        )
        return fallback

    directive = directive_for_decision(result.decision)
    if directive is None:
        _trace_directive_ignored(
            fallback,
            raw_decision,
            "no_executor_mapping",
            result.context_hash,
        )
        return fallback

    if not _control_mode_allows(control_mode, fallback, directive):
        _trace_directive_ignored(
            fallback,
            raw_decision,
            "control_surface_not_enabled",
            result.context_hash,
        )
        return fallback

    _trace_directive_selected(fallback, directive, result.context_hash)
    return directive


def _control_mode_allows(
    control_mode: str,
    fallback: ModeDirective,
    directive: ModeDirective,
) -> bool:
    if control_mode == "targets":
        return fallback.mode == "probe_systematic" and directive.mode == "probe_target"
    if control_mode == "all":
        return True
    return False


def _provider_cooldown_active(
    belief_state: BeliefState,
    *,
    provider: Any,
    control_mode: str,
    context: dict[str, Any],
) -> bool:
    cooldown_ticks = _provider_cooldown_ticks(provider)
    if cooldown_ticks <= 0:
        return False
    tick = int(getattr(belief_state, "tick", 0) or 0)
    state = getattr(belief_state, "inferences", {}).get(LLM_PROVIDER_STATE_KEY)
    if not isinstance(state, dict):
        return False
    if state.get("provider") != getattr(provider, "name", None):
        return False
    if state.get("control_mode") != control_mode:
        return False
    if state.get("surface") != infer_surface(context):
        return False
    last_tick = state.get("tick")
    if not isinstance(last_tick, int):
        return False
    return tick >= last_tick and tick - last_tick < cooldown_ticks


def _record_provider_call(
    belief_state: BeliefState,
    *,
    provider: Any,
    control_mode: str,
    context: dict[str, Any],
    context_hash: str,
) -> None:
    state = {
        "tick": int(getattr(belief_state, "tick", 0) or 0),
        "provider": getattr(provider, "name", None),
        "control_mode": control_mode,
        "surface": infer_surface(context),
        "context_hash": context_hash,
    }
    belief_state.inferences[LLM_PROVIDER_STATE_KEY] = state
    belief_state.extra[LLM_PROVIDER_STATE_KEY] = state


def _provider_cooldown_ticks(provider: Any) -> int:
    try:
        return max(0, int(getattr(provider, "decision_cooldown_ticks", 0) or 0))
    except (TypeError, ValueError):
        return 0


def _trace_directive_selected(
    fallback: ModeDirective,
    directive: ModeDirective,
    context_hash: str,
) -> None:
    if not logger:
        return
    logger.event(
        "llm_directive_selected",
        {
            "context_hash": context_hash,
            "fallback_mode": fallback.mode,
            "selected_mode": directive.mode,
            "selected_params": repr(directive.params),
        },
        LogLevel.DECISIONS,
    )


def _trace_directive_ignored(
    fallback: ModeDirective,
    raw_decision: Any,
    reason: str,
    context_hash: str,
    *,
    reasons: list[str] | None = None,
) -> None:
    if not logger:
        return
    action = raw_decision.get("action") if isinstance(raw_decision, dict) else None
    logger.event(
        "llm_directive_ignored",
        {
            "context_hash": context_hash,
            "fallback_mode": fallback.mode,
            "action": action,
            "reason": reason,
            "validator_reasons": reasons or [],
        },
        LogLevel.DECISIONS,
    )


__all__ = ["LLM_CONTROL_MODES", "maybe_override_directive"]
