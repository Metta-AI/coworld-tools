"""Attend Meeting mode: conversational chat plus deadline-safe voting."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from players.crewrift.richardborg.strategy.meeting import (
    CHAT_MAX_CHARS,
    VOTE_SKIP,
    MeetingDecision,
    MeetingDecisionValidationError,
    MeetingLLMClient,
    build_meeting_llm_client_from_env,
    valid_vote_targets,
    validate_meeting_decision,
)
from players.crewrift.richardborg.strategy.meeting.context import (
    CHAT_COOLDOWN_TICKS,
    VOTE_TIMER_TICKS,
)
from players.crewrift.richardborg.memory.context import (
    serialize_richard_meeting_context,
)
from players.crewrift.richardborg.strategy.suspicion import top_suspect
from players.crewrift.richardborg.types import ActionState, Belief, ChatEvent, Intent
from players.player_sdk import EmptyModeParams, Mode

# Deterministic fallback: preserve the pre-LLM behavior unless explicitly enabled.
MEETING_CHAT = "no read, skipping"

LLM_MIN_CALL_INTERVAL_TICKS = 12
DEADLINE_LLM_REMAINING_TICKS = 96
AUTO_SUBMIT_REMAINING_TICKS = 48


class AttendMeetingMode(Mode[Belief, ActionState, Intent]):
    name = "attend_meeting"
    params_type = EmptyModeParams

    def __init__(
        self,
        params=None,
        *,
        llm_client: MeetingLLMClient | None = None,
        context_serializer: Callable[
            ..., dict[str, Any]
        ] = serialize_richard_meeting_context,
    ) -> None:
        super().__init__(params)
        self._llm_client = (
            llm_client
            if llm_client is not None
            else build_meeting_llm_client_from_env()
        )
        self._context_serializer = context_serializer
        self._meeting_id: int | None = None
        self._deterministic_chatted = False
        self._disabled_traced = False
        self._sent_chat_texts: set[str] = set()
        self._pending_chat_text: str | None = None
        self._last_chat_tick: int | None = None
        self._last_llm_call_tick: int | None = None
        self._last_external_chat_signature: tuple[tuple[int, str | None, str], ...] = ()
        self._last_cooldown_prompt_chat_tick: int | None = None
        self._deadline_prompted = False
        self._tentative_vote: str | None = None
        self._tentative_vote_ready_to_submit = False
        self._vote_submitted = False
        self._vote_submission_target: str | None = None

    def is_legal(self, belief: Belief) -> bool:
        return belief.phase == "Voting"

    def decide(self, belief: Belief, action_state: ActionState) -> Intent:
        self._reset_for_meeting_if_needed(belief)
        if action_state.vote_confirmed:
            self._vote_submitted = True
            self._vote_submission_target = None
            return Intent(kind="idle", reason="vote already confirmed")
        if self._vote_submission_target is not None:
            return self._vote_intent(
                self._vote_submission_target, reason="continuing vote submission"
            )

        if not self._llm_client.enabled:
            return self._decide_deterministic(belief, trace_disabled=True)

        if self._should_auto_submit(belief):
            return self._submit_vote_intent(
                belief, reason="meeting deadline: auto-submit tentative vote"
            )
        if self._should_submit_tentative_vote():
            return self._submit_vote_intent(belief, reason="auto-submit tentative vote")

        if self._pending_chat_text is not None and self._chat_cooldown_ready(belief):
            return self._send_chat_intent(
                belief, self._pending_chat_text, reason="sending pending LLM chat"
            )

        trigger = self._next_llm_trigger(belief)
        if trigger is None:
            return Intent(kind="idle", reason="waiting during meeting")

        context = self._context_serializer(
            belief,
            trigger=trigger,
            tentative_vote=self._tentative_vote,
            sent_chat_texts=self._sent_chat_texts,
            last_chat_tick=self._last_chat_tick,
        )
        self.emit.event(
            "meeting_context_serialized", {"trigger": trigger, "context": context}
        )
        result = self._call_llm(context, trigger=trigger)
        if result is None:
            return self._decide_after_llm_failure(belief, trigger)
        decision = self._validate_decision(belief, result.decision)
        if decision is None:
            return self._decide_after_llm_failure(belief, trigger)
        self._trace_decision(trigger, decision, result)
        return self._apply_decision(belief, decision)

    # --- deterministic fallback ------------------------------------------

    def _decide_deterministic(self, belief: Belief, *, trace_disabled: bool) -> Intent:
        if trace_disabled and not self._disabled_traced:
            self._disabled_traced = True
            self.emit.event(
                "meeting_llm_fallback",
                {"reason": "llm_disabled", "detail": self._llm_client.disabled_reason},
            )
        if not self._deterministic_chatted:
            self._deterministic_chatted = True
            return self._send_chat_intent(belief, MEETING_CHAT, reason="meeting opener")
        return self._submit_vote_intent(belief, reason="deterministic meeting vote")

    # --- LLM call cadence -------------------------------------------------

    def _next_llm_trigger(self, belief: Belief) -> str | None:
        tick = belief.last_tick
        if (
            self._last_llm_call_tick is not None
            and tick - self._last_llm_call_tick < LLM_MIN_CALL_INTERVAL_TICKS
        ):
            return None
        if self._last_llm_call_tick is None:
            return "meeting_start"

        signature = self._external_chat_signature(belief)
        if signature != self._last_external_chat_signature:
            return "new_chat"

        if (
            self._last_chat_tick is not None
            and self._chat_cooldown_ready(belief)
            and self._last_cooldown_prompt_chat_tick != self._last_chat_tick
        ):
            return "chat_cooldown_ready"

        if (
            self._remaining_ticks(belief) <= DEADLINE_LLM_REMAINING_TICKS
            and not self._deadline_prompted
        ):
            return "deadline"
        return None

    def _call_llm(self, context: dict[str, Any], *, trigger: str) -> Any | None:
        self._last_llm_call_tick = int(context["meeting"]["tick"])
        self._last_external_chat_signature = tuple(
            (event["tick"], event["speaker_color"], event["text"])
            for event in context["chat"]["messages"]
            if not event["self"]
        )
        if trigger == "deadline":
            self._deadline_prompted = True
        if trigger == "chat_cooldown_ready":
            self._last_cooldown_prompt_chat_tick = self._last_chat_tick
        try:
            result = self._llm_client.decide(context, trigger=trigger)
        except Exception as exc:
            self.emit.event(
                "meeting_llm_fallback",
                {"reason": "llm_call_failed", "trigger": trigger, "error": repr(exc)},
            )
            return None
        self.emit.histogram(
            "meeting_llm.latency_ms",
            result.latency_ms,
            tags={"model": result.model, "trigger": trigger},
        )
        return result

    def _validate_decision(
        self, belief: Belief, decision: MeetingDecision
    ) -> MeetingDecision | None:
        try:
            return validate_meeting_decision(
                decision,
                alive_vote_targets=valid_vote_targets(belief),
                current_tentative=self._tentative_vote,
                fallback_vote=self._fallback_vote_target(belief),
            )
        except MeetingDecisionValidationError as exc:
            self.emit.event(
                "meeting_llm_fallback",
                {
                    "reason": "invalid_meeting_decision",
                    "error": str(exc),
                    "decision": decision.model_dump(mode="json"),
                },
            )
            return None

    def _trace_decision(
        self, trigger: str, decision: MeetingDecision, result: Any
    ) -> None:
        self.emit.event(
            "meeting_llm_decision",
            {
                "trigger": trigger,
                "model": result.model,
                "latency_ms": round(result.latency_ms, 2),
                "usage": result.usage,
                "decision": decision.model_dump(mode="json"),
            },
        )
        if result.raw_request is not None or result.raw_response is not None:
            self.emit.event(
                "meeting_llm_debug",
                {"request": result.raw_request, "response": result.raw_response},
            )

    # --- decision application --------------------------------------------

    def _apply_decision(self, belief: Belief, decision: MeetingDecision) -> Intent:
        if decision.vote_target is not None:
            self._tentative_vote = decision.vote_target
            self._tentative_vote_ready_to_submit = (
                decision.action == "set_tentative_vote"
            )
            self.emit.event(
                "meeting_tentative_vote",
                {
                    "target": self._tentative_vote,
                    "reason": decision.reason,
                    "confidence": decision.confidence,
                },
            )

        if decision.action == "send_chat":
            assert decision.chat_text is not None
            if decision.chat_text in self._sent_chat_texts:
                self.emit.event(
                    "meeting_llm_fallback",
                    {"reason": "duplicate_chat_suppressed", "text": decision.chat_text},
                )
                return Intent(kind="idle", reason="duplicate LLM chat suppressed")
            if self._chat_cooldown_ready(belief):
                return self._send_chat_intent(
                    belief,
                    decision.chat_text,
                    reason=decision.reason or "LLM meeting chat",
                )
            self._pending_chat_text = decision.chat_text[:CHAT_MAX_CHARS]
            self.emit.event(
                "meeting_llm_fallback",
                {"reason": "chat_cooldown_pending", "text": self._pending_chat_text},
            )
            return Intent(kind="idle", reason="waiting for chat cooldown")

        if decision.action == "submit_vote":
            return self._submit_vote_intent(
                belief, reason=decision.reason or "LLM submitted vote"
            )

        if decision.action == "set_tentative_vote":
            return Intent(
                kind="idle", reason=decision.reason or "LLM set tentative vote"
            )

        return Intent(kind="idle", reason=decision.reason or "LLM waits")

    def _send_chat_intent(self, belief: Belief, text: str, *, reason: str) -> Intent:
        self._pending_chat_text = None
        self._sent_chat_texts.add(text)
        self._last_chat_tick = belief.last_tick
        self.emit.event("meeting_chat_selected", {"text": text, "reason": reason})
        return Intent(kind="chat", text=text, reason=reason)

    def _submit_vote_intent(self, belief: Belief, *, reason: str) -> Intent:
        vote_target = self._resolved_vote_target(belief)
        self._vote_submission_target = vote_target
        self._tentative_vote_ready_to_submit = False
        self.emit.event(
            "meeting_vote_selected", {"target": vote_target, "reason": reason}
        )
        return self._vote_intent(vote_target, reason=reason)

    def _vote_intent(self, vote_target: str, *, reason: str) -> Intent:
        if vote_target == VOTE_SKIP:
            return Intent(kind="vote", reason=reason)
        return Intent(kind="vote", target_color=vote_target, reason=reason)

    def _decide_after_llm_failure(self, belief: Belief, trigger: str) -> Intent:
        if trigger == "deadline":
            return self._submit_vote_intent(
                belief, reason=f"LLM fallback after {trigger}"
            )
        if trigger == "meeting_start":
            return self._decide_deterministic(belief, trace_disabled=False)
        return Intent(kind="idle", reason=f"LLM fallback after {trigger}")

    # --- state helpers ----------------------------------------------------

    def _reset_for_meeting_if_needed(self, belief: Belief) -> None:
        meeting_id = belief.phase_start_tick
        if meeting_id == self._meeting_id:
            return
        self._meeting_id = meeting_id
        self._deterministic_chatted = False
        self._disabled_traced = False
        self._sent_chat_texts.clear()
        self._pending_chat_text = None
        self._last_chat_tick = None
        self._last_llm_call_tick = None
        self._last_external_chat_signature = self._external_chat_signature(belief)
        self._last_cooldown_prompt_chat_tick = None
        self._deadline_prompted = False
        self._tentative_vote = None
        self._tentative_vote_ready_to_submit = False
        self._vote_submitted = False
        self._vote_submission_target = None

    def _external_chat_signature(
        self, belief: Belief
    ) -> tuple[tuple[int, str | None, str], ...]:
        self_color = belief.voting.self_marker_color
        return tuple(
            (event.tick, event.speaker_color, event.text)
            for event in belief.chat_log
            if self._is_external_chat(event, self_color)
        )

    def _is_external_chat(self, event: ChatEvent, self_color: str | None) -> bool:
        if event.speaker_color is not None and event.speaker_color == self_color:
            return False
        return event.text not in self._sent_chat_texts

    def _chat_cooldown_ready(self, belief: Belief) -> bool:
        return (
            self._last_chat_tick is None
            or belief.last_tick - self._last_chat_tick >= CHAT_COOLDOWN_TICKS
        )

    def _remaining_ticks(self, belief: Belief) -> int:
        return max(
            0, VOTE_TIMER_TICKS - max(0, belief.last_tick - belief.phase_start_tick)
        )

    def _should_auto_submit(self, belief: Belief) -> bool:
        return (
            not self._vote_submitted
            and self._vote_submission_target is None
            and self._remaining_ticks(belief) <= AUTO_SUBMIT_REMAINING_TICKS
        )

    def _should_submit_tentative_vote(self) -> bool:
        return (
            not self._vote_submitted
            and self._vote_submission_target is None
            and self._tentative_vote is not None
            and self._tentative_vote_ready_to_submit
        )

    def _resolved_vote_target(self, belief: Belief) -> str:
        tentative = self._tentative_vote
        if (
            tentative is not None
            and tentative != VOTE_SKIP
            and tentative in valid_vote_targets(belief)
        ):
            return tentative
        return self._fallback_vote_target(belief)

    def _fallback_vote_target(self, belief: Belief) -> str:
        suspect = top_suspect(belief)
        if suspect is not None:
            return suspect
        for candidate in belief.voting.candidates:
            if candidate.alive and candidate.color != belief.voting.self_marker_color:
                return candidate.color
        legal_targets = sorted(valid_vote_targets(belief))
        return legal_targets[0] if legal_targets else VOTE_SKIP
