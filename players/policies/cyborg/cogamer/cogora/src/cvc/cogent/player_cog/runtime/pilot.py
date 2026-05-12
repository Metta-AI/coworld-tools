from __future__ import annotations

import json
import threading
from collections.abc import Callable
from typing import Any

from mettagrid_sdk.sdk import LogRecord, MettagridSDK, ReviewRequest

from cvc.cogent.player_cog.providers.models import (
    CodeReviewRequest,
    CodeReviewResponse,
)
from cvc.cogent.player_cog.runtime.artifacts import ArtifactStore
from cvc.cogent.player_cog.runtime.execution import (
    DEFAULT_POLICY_TIMEOUT_SECONDS,
    PolicyExecutionRecord,
    PolicyExecutionResult,
    PolicyUpdate,
    compile_policy,
    execute_compiled_policy,
    render_sdk_reference,
)
from cvc.cogent.player_cog.runtime.models import (
    ExperienceTraceRecord,
    PolicyGenerationRecord,
    ReviewDecisionRecord,
)
from cvc.cogent.player_cog.scratchpad import SCRATCHPAD_LINE_RE, scratchpad_key_lines, scratchpad_line_value

_MAX_RAW_RESPONSE_CHARS = 4000
_MAX_MONOLOGUE_TRANSCRIPT_CHARS = 200_000


def _append_policy_update_retry_feedback(prompt: str, error: str) -> str:
    return "\n\n".join(
        [
            prompt,
            f"Previous output failed validation: {error}",
            "Return only the compact JSON object matching the requested schema.",
            "Ensure set_policy is valid executable Python with correct indentation and a callable step(sdk).",
        ]
    )


def _merge_typed_scratchpad_lines(current_text: str, updated_text: str) -> str:
    current_values = scratchpad_key_lines(current_text.splitlines())
    updated_values = scratchpad_key_lines(updated_text.splitlines())
    preserved_by_key: dict[str, str] = {}
    for key, current_line in current_values.items():
        updated_line = updated_values.get(key)
        if updated_line is None:
            continue
        if _should_preserve_typed_scratchpad_line(current_line, updated_line):
            preserved_by_key[key] = current_line
    if not preserved_by_key:
        return updated_text
    if not updated_text:
        return "\n".join(preserved_by_key[key] for key in sorted(preserved_by_key))

    merged_lines: list[str] = []
    restored_keys: set[str] = set()
    for line in updated_text.splitlines():
        match = SCRATCHPAD_LINE_RE.match(line)
        if match is None:
            merged_lines.append(line)
            continue
        key = match.group("key")
        restored_line = preserved_by_key.get(key)
        if restored_line is None:
            merged_lines.append(line)
            continue
        merged_lines.append(restored_line)
        restored_keys.add(key)
    for key in sorted(preserved_by_key):
        if key not in restored_keys:
            merged_lines.append(preserved_by_key[key])
    return "\n".join(merged_lines)


def _should_preserve_typed_scratchpad_line(current_line: str, updated_line: str) -> bool:
    current_value = scratchpad_line_value(current_line)
    updated_value = scratchpad_line_value(updated_line)
    return not isinstance(current_value, str) and isinstance(updated_value, str)


def _merge_review_metadata(
    metadata: dict[str, str | int | float | bool] | None,
    extra: dict[str, str | int | float | bool] | None = None,
) -> dict[str, str | int | float | bool]:
    merged = {} if metadata is None else dict(metadata)
    if extra is not None:
        merged.update(extra)
    return merged


def _metadata_from_return_value(
    return_value: Any,
) -> dict[str, str | int | float | bool]:
    if not isinstance(return_value, dict):
        return {}
    return {
        key: value
        for key in (
            "objective",
            "role",
            "target_entity_id",
            "target_region",
            "resource_bias",
        )
        if isinstance((value := return_value.get(key)), (str, int, float, bool))
    }


def _should_retry_policy_update_error(exc: Exception) -> bool:
    return isinstance(exc, SyntaxError)


def _merge_policy_retry_metadata(
    response: CodeReviewResponse,
    *,
    error: str,
) -> CodeReviewResponse:
    metadata = dict(response.metadata)
    metadata["validation_retry_count"] = int(metadata.get("validation_retry_count", 0) or 0) + 1
    metadata["policy_retry_validation_error"] = error
    return response.model_copy(update={"metadata": metadata})


def _build_repeated_policy_validation_exception(*, initial_error: str, retry_error: str) -> SyntaxError:
    return SyntaxError(
        "Generated invalid policy twice. "
        f"First validation failed: {initial_error}. "
        f"Retry validation failed: {retry_error}."
    )


class LivePolicyBundleSession:
    def __init__(
        self,
        *,
        backend: Callable[[CodeReviewRequest], CodeReviewResponse],
        artifact_store: ArtifactStore | None = None,
        timeout_seconds: float = DEFAULT_POLICY_TIMEOUT_SECONDS,
        record_step_traces: bool = True,
        should_process_review_request: Callable[[ReviewRequest, int], bool] | None = None,
    ) -> None:
        self._backend = backend
        self._artifact_store = artifact_store
        self._timeout_seconds = timeout_seconds
        self._record_step_traces = record_step_traces
        self._should_process_review_request = should_process_review_request
        self._compiled_policy = None
        self._policy_source = ""
        self._monologue_lock = threading.Lock()
        self._monologue_transcript_tail = ""

    def set_timeout_seconds(self, timeout_seconds: float) -> None:
        self._timeout_seconds = timeout_seconds

    @property
    def timeout_seconds(self) -> float:
        return self._timeout_seconds

    @property
    def policy_source(self) -> str:
        return self._policy_source

    def monologue_transcript_tail(self) -> str:
        with self._monologue_lock:
            return self._monologue_transcript_tail

    def reset(self) -> None:
        self._compiled_policy = None
        self._policy_source = ""
        with self._monologue_lock:
            self._monologue_transcript_tail = ""

    def execute(
        self,
        *,
        sdk: MettagridSDK,
        prompt: str,
        step: int,
        agent_id: int,
        goal: str = "",
        metadata: dict[str, str | int | float | bool] | None = None,
        on_review_request: Callable[[LogRecord, str], None] | None = None,
    ) -> PolicyExecutionResult:
        self._ensure_policy(
            sdk=sdk,
            prompt=prompt,
            step=step,
            agent_id=agent_id,
            goal=goal,
            metadata=metadata,
        )
        compiled_policy = self._compiled_policy
        assert compiled_policy is not None

        result = execute_compiled_policy(compiled_policy, sdk, timeout_seconds=self._timeout_seconds)
        execution_metadata = _merge_review_metadata(metadata, _metadata_from_return_value(result.return_value))
        current_source = self._policy_source
        if self._artifact_store is not None and self._record_step_traces:
            self._artifact_store.append_execution_record(
                PolicyExecutionRecord(
                    step=step,
                    agent_id=agent_id,
                    policy_source=current_source,
                    result=result,
                )
            )
            self._artifact_store.append_experience_record(
                ExperienceTraceRecord(
                    step=step,
                    agent_id=agent_id,
                    summary=render_sdk_reference(sdk),
                    policy_source=current_source,
                    return_repr=result.return_repr,
                    logs=[f"{record.level}:{record.message}" for record in result.logs],
                    metadata=execution_metadata,
                )
            )
        review_request, triggering_log = self._select_review_request(result)
        if (
            review_request is not None
            and self._should_process_review_request is not None
            and not self._should_process_review_request(review_request, step)
        ):
            review_request = None
            triggering_log = None
        if review_request is not None and triggering_log is not None:
            if on_review_request is not None:
                on_review_request(triggering_log, "sdk.log.write(review=...)")
            else:
                self.process_log_review(
                    record=triggering_log,
                    prompt=prompt,
                    step=step,
                    agent_id=agent_id,
                    goal=goal,
                    metadata=execution_metadata,
                    request_source="sdk.log.write(review=...)",
                    append_request_transcript=True,
                )
        return result

    def process_log_review(
        self,
        *,
        record: LogRecord,
        prompt: str,
        step: int,
        agent_id: int,
        goal: str = "",
        metadata: dict[str, str | int | float | bool] | None = None,
        request_source: str = "sdk.log.write(review=...)",
        extra_context: str = "",
        append_request_transcript: bool = False,
    ) -> CodeReviewResponse:
        review_request = _review_request_from_log_record(record)
        if review_request is None:
            raise ValueError("Log record did not include a review request")
        review_prompt_parts = [prompt, "Logged review event:", _render_log_line(record)]
        if extra_context:
            review_prompt_parts.append(extra_context)
        review_prompt = "\n\n".join(review_prompt_parts)
        if append_request_transcript:
            self._append_logged_review_request_transcript(
                step=step,
                agent_id=agent_id,
                record=record,
                request_source=request_source,
            )
        request = self._build_review_request(
            prompt=review_prompt,
            step=step,
            agent_id=agent_id,
            trigger_name=review_request.trigger_name,
            goal=goal,
            metadata=metadata,
        )
        return self._perform_review(
            request=request,
            step=step,
            agent_id=agent_id,
            trigger_name=review_request.trigger_name,
            metadata=metadata,
            request_source=request_source,
            request_summary=review_request.prompt or review_request.trigger_name,
            triggering_log=record,
        )

    def _perform_review(
        self,
        *,
        request: CodeReviewRequest,
        step: int,
        agent_id: int,
        trigger_name: str,
        metadata: dict[str, str | int | float | bool] | None,
        request_source: str,
        request_summary: str | None,
        triggering_log,
    ) -> CodeReviewResponse:
        response, review_error = self._run_backend_review(request)
        policy_updated = False
        scratchpad_updated = False
        plan_updated = False
        policy_update_error: str | None = None
        policy_update_exception: Exception | None = None
        next_scratchpad = self._next_scratchpad(response)
        current_request = request
        policy_retry_error: str | None = None
        while response.set_policy:
            try:
                self._set_policy_source(
                    response.set_policy,
                    step=step,
                    agent_id=agent_id,
                    prompt=current_request.prompt,
                    raw_response=_raw_response_text(response),
                    metadata=_merge_record_metadata(metadata, response.metadata),
                )
                policy_updated = True
                break
            except Exception as exc:
                current_error = f"{type(exc).__name__}: {exc}"
                if not _should_retry_policy_update_error(exc) or policy_retry_error is not None:
                    policy_update_exception = (
                        _build_repeated_policy_validation_exception(
                            initial_error=policy_retry_error,
                            retry_error=current_error,
                        )
                        if policy_retry_error is not None and _should_retry_policy_update_error(exc)
                        else exc
                    )
                    self._append_failed_generation_record(
                        step=step,
                        agent_id=agent_id,
                        prompt=current_request.prompt,
                        raw_response=_raw_response_text(response),
                        policy_source=response.set_policy,
                        error_message=f"{type(policy_update_exception).__name__}: {policy_update_exception}",
                        metadata=_merge_record_metadata(metadata, response.metadata),
                    )
                    break
                policy_retry_error = current_error
                current_request = request.model_copy(
                    update={"prompt": _append_policy_update_retry_feedback(request.prompt, policy_retry_error)}
                )
                response, retry_review_error = self._run_backend_review(
                    current_request,
                    policy_retry_error=policy_retry_error,
                )
                if retry_review_error is not None:
                    review_error = retry_review_error
                next_scratchpad = self._next_scratchpad(response)
        if policy_update_exception is None and self._artifact_store is not None:
            if next_scratchpad is not None:
                self._artifact_store.replace_scratchpad(next_scratchpad)
                scratchpad_updated = True
            if response.replace_plan is not None:
                self._artifact_store.replace_plan(response.replace_plan)
                plan_updated = True
        if self._artifact_store is not None:
            policy_update_error = (
                None
                if policy_update_exception is None
                else f"{type(policy_update_exception).__name__}: {policy_update_exception}"
            )
            self._artifact_store.append_decision_record(
                ReviewDecisionRecord(
                    step=step,
                    agent_id=agent_id,
                    trigger_name=trigger_name,
                    action=response.action,
                    request_summary=request_summary or trigger_name,
                    summary=response.review_summary,
                    policy_updated=policy_updated,
                    scratchpad_updated=scratchpad_updated,
                    plan_updated=plan_updated,
                    metadata=_merge_record_metadata(
                        metadata,
                        response.metadata,
                        (None if review_error is None else {"review_error": review_error}),
                        (None if policy_update_error is None else {"policy_update_error": policy_update_error}),
                    ),
                )
            )
        self._append_review_transcript(
            step=step,
            agent_id=agent_id,
            trigger_name=trigger_name,
            request_source=request_source,
            request_summary=request_summary or trigger_name,
            triggering_log=triggering_log,
            response=response,
            policy_updated=policy_updated,
            policy_update_error=policy_update_error,
            review_error=review_error,
            scratchpad_updated=scratchpad_updated,
            plan_updated=plan_updated,
        )
        if policy_update_exception is not None:
            raise policy_update_exception
        return response

    def _run_backend_review(
        self,
        request: CodeReviewRequest,
        *,
        policy_retry_error: str | None = None,
    ) -> tuple[CodeReviewResponse, str | None]:
        review_error: str | None = None
        try:
            response = self._backend(request)
        except Exception as exc:
            review_error = f"{type(exc).__name__}: {exc}"
            response = CodeReviewResponse(
                action="none",
                review_summary=f"Review failed: {review_error}",
                metadata={"review_error": review_error},
            )
        if policy_retry_error is not None:
            response = _merge_policy_retry_metadata(response, error=policy_retry_error)
        return response, review_error

    def _next_scratchpad(self, response: CodeReviewResponse) -> str | None:
        if response.replace_scratchpad is None or self._artifact_store is None:
            return None
        return _merge_typed_scratchpad_lines(
            self._artifact_store.read_scratchpad(),
            response.replace_scratchpad,
        )

    def _ensure_policy(
        self,
        *,
        sdk: MettagridSDK,
        prompt: str,
        step: int,
        agent_id: int,
        goal: str,
        metadata: dict[str, str | int | float | bool] | None,
    ) -> None:
        if self._compiled_policy is not None:
            return
        response = self.process_log_review(
            record=LogRecord(
                level="info",
                message="No live policy yet. Generate the initial main.py for this cog.",
                step=step,
                review=ReviewRequest(
                    trigger_name="initial_generation",
                    prompt="Generate the initial policy.",
                ),
                data={"policy_missing": True},
            ),
            prompt=prompt,
            step=step,
            agent_id=agent_id,
            goal=goal,
            metadata=metadata,
            request_source="initial_generation",
            extra_context="Pre-step runtime log before any main.py exists.",
            append_request_transcript=True,
        )
        if not response.set_policy:
            raise ValueError("Live policy backend did not return set_policy for initial generation")

    def _set_policy_source(
        self,
        policy_source: str,
        *,
        step: int,
        agent_id: int,
        prompt: str,
        raw_response: str,
        metadata: dict[str, str | int | float | bool] | None,
    ) -> None:
        compiled = compile_policy(PolicyUpdate(source=policy_source))
        if self._artifact_store is not None:
            main_file = self._artifact_store.main_file
            previous_main_source = (
                None if main_file is None or not main_file.exists() else main_file.read_text(encoding="utf-8")
            )
            try:
                self._artifact_store.write_main_source(policy_source)
                self._artifact_store.append_generation_record(
                    PolicyGenerationRecord(
                        step=step,
                        agent_id=agent_id,
                        prompt=prompt,
                        raw_response=raw_response,
                        policy_source=policy_source,
                        success=True,
                        metadata={} if metadata is None else metadata,
                    )
                )
            except Exception:
                if main_file is not None:
                    if previous_main_source is None:
                        main_file.unlink(missing_ok=True)
                    else:
                        main_file.write_text(previous_main_source, encoding="utf-8")
                raise
        self._compiled_policy = compiled
        self._policy_source = policy_source

    def _append_failed_generation_record(
        self,
        *,
        step: int,
        agent_id: int,
        prompt: str,
        raw_response: str,
        policy_source: str | None,
        error_message: str,
        metadata: dict[str, str | int | float | bool] | None,
    ) -> None:
        if self._artifact_store is None:
            return
        self._artifact_store.append_generation_record(
            PolicyGenerationRecord(
                step=step,
                agent_id=agent_id,
                prompt=prompt,
                raw_response=raw_response,
                policy_source=policy_source,
                success=False,
                error_message=error_message,
                metadata={} if metadata is None else metadata,
            )
        )

    def _build_review_request(
        self,
        *,
        prompt: str,
        step: int,
        agent_id: int,
        trigger_name: str,
        goal: str,
        metadata: dict[str, str | int | float | bool] | None,
    ) -> CodeReviewRequest:
        return CodeReviewRequest(
            agent_id=agent_id,
            step=step,
            goal=goal,
            trigger_name=trigger_name,
            prompt=prompt,
            current_main_source=self._policy_source,
            current_plan=("" if self._artifact_store is None else self._artifact_store.read_plan()),
            current_scratchpad=("" if self._artifact_store is None else self._artifact_store.read_scratchpad()),
            experience_tail=(
                ""
                if self._artifact_store is None
                else self._artifact_store.build_prompt_context(
                    include_main_source=False,
                    include_plan=False,
                    include_scratchpad=False,
                )
            ),
            decision_log_tail=("" if self._artifact_store is None else self._decision_log_tail()),
            metadata={} if metadata is None else dict(metadata),
        )

    def _decision_log_tail(self, max_entries: int = 6) -> str:
        if self._artifact_store is None:
            return ""
        records = self._artifact_store.read_recent_decision_records(max_entries=max_entries)
        if not records:
            return ""
        return "\n".join(
            f"- step {record.step}: trigger={record.trigger_name or 'none'} action={record.action} "
            f"request={record.request_summary or 'none'} {record.summary or 'none'}"
            for record in records
        )

    def _select_review_request(self, result: PolicyExecutionResult):
        for record in result.logs:
            review_request = _review_request_from_log_record(record)
            if review_request is not None:
                return review_request, record
        return None, None

    def _append_logged_review_request_transcript(
        self,
        *,
        step: int,
        agent_id: int,
        record: LogRecord,
        request_source: str,
    ) -> None:
        assert record.review is not None
        lines = [f"## Step {step} Agent {agent_id} runtime -> llm"]
        lines.append("sdk.log:")
        lines.append(f"- {_render_log_line(record)}")
        lines.append("review_request:")
        lines.append(f"- source: {request_source}")
        lines.append(f"- details: {_render_review_request_line(record.review)}")
        self._append_transcript_lines(lines)

    def _append_review_transcript(
        self,
        *,
        step: int,
        agent_id: int,
        trigger_name: str,
        request_source: str,
        request_summary: str,
        triggering_log,
        response: CodeReviewResponse,
        policy_updated: bool,
        policy_update_error: str | None,
        review_error: str | None,
        scratchpad_updated: bool,
        plan_updated: bool,
    ) -> None:
        lines = [f"## Step {step} Agent {agent_id} llm -> runtime"]
        lines.append("review_request:")
        lines.append(f"- source: {request_source}")
        lines.append(f"- trigger: {trigger_name}")
        lines.append(f"- request: {request_summary}")
        if triggering_log is not None:
            lines.append(f"- triggering_log: {_render_log_line(triggering_log)}")
        outcome_bits = [f"action={response.action}"]
        if policy_updated:
            outcome_bits.append("policy_updated=yes")
        if scratchpad_updated:
            outcome_bits.append("scratchpad_updated=yes")
        if plan_updated:
            outcome_bits.append("plan_updated=yes")
        lines.append(f"review_outcome: {', '.join(outcome_bits)}")
        if policy_update_error:
            lines.append(f"policy_update_error: {policy_update_error}")
        if review_error:
            lines.append(f"review_error: {review_error}")
        if response.review_summary:
            lines.append(f"summary: {response.review_summary}")
        api_line = _format_api_metadata(response.metadata if isinstance(response.metadata, dict) else {})
        if api_line:
            lines.append(f"api: {api_line}")
        raw_response = _raw_response_text(response)
        if raw_response:
            lines.append("llm_response:")
            lines.extend(_render_text_block(_pretty_json_or_text(raw_response), indent="  "))
        self._append_transcript_lines(lines)

    def _append_transcript_lines(self, lines: list[str]) -> None:
        appended = "\n".join([*lines, ""]) + "\n"
        with self._monologue_lock:
            self._monologue_transcript_tail = (self._monologue_transcript_tail + appended)[
                -_MAX_MONOLOGUE_TRANSCRIPT_CHARS:
            ]
        if self._artifact_store is not None:
            self._artifact_store.append_log_text(appended)


def _review_request_from_log_record(record: LogRecord) -> ReviewRequest | None:
    return record.review


def _merge_record_metadata(
    *sources: dict[str, str | int | float | bool] | dict[str, Any] | None,
) -> dict[str, str | int | float | bool]:
    merged: dict[str, str | int | float | bool] = {}
    for source in sources:
        if not isinstance(source, dict):
            continue
        for key, value in source.items():
            if key == "raw_response_text":
                continue
            if isinstance(value, (str, int, float, bool)):
                merged[key] = value
    return merged


def _serialize_log_record(record: Any) -> dict[str, Any]:
    payload = {
        "level": _string_or_none(getattr(record, "level", None)) or "info",
        "message": _string_or_none(getattr(record, "message", None)) or "",
        "step": _int_or_none(getattr(record, "step", None)),
    }
    review = getattr(record, "review", None)
    if review is not None:
        payload["review"] = _serialize_review_request(review)
    data = getattr(record, "data", None)
    if isinstance(data, dict) and data:
        payload["data"] = dict(data)
    return payload


def _serialize_review_request(request: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {"trigger_name": _string_or_none(getattr(request, "trigger_name", None)) or ""}
    prompt = _string_or_none(getattr(request, "prompt", None))
    if prompt:
        payload["prompt"] = prompt
    target = _string_or_none(getattr(request, "target", None))
    if target:
        payload["target"] = target
    step = _int_or_none(getattr(request, "step", None))
    if step is not None:
        payload["step"] = step
    metadata = getattr(request, "metadata", None)
    if isinstance(metadata, dict) and metadata:
        payload["metadata"] = dict(metadata)
    return payload


def _raw_response_text(response: CodeReviewResponse) -> str:
    if isinstance(response.metadata, dict):
        raw_response = response.metadata.get("raw_response_text")
        if isinstance(raw_response, str) and raw_response:
            return raw_response
    return response.model_dump_json()


def _render_review_request_line(request: Any) -> str:
    serialized = _serialize_review_request(request)
    bits = []
    trigger_name = serialized.get("trigger_name")
    if isinstance(trigger_name, str) and trigger_name:
        bits.append(f"trigger={trigger_name}")
    target = serialized.get("target")
    if isinstance(target, str) and target:
        bits.append(f"target={target}")
    prompt = serialized.get("prompt")
    if isinstance(prompt, str) and prompt:
        bits.append(f"prompt={prompt}")
    return ", ".join(bits) or _compact_json(serialized)


def _render_log_line(record: Any) -> str:
    serialized = _serialize_log_record(record)
    level = serialized.get("level") or "info"
    message = serialized.get("message") or ""
    step = serialized.get("step")
    line = f"[{level}] {message}".rstrip()
    if isinstance(step, int):
        line = f"{line} (step {step})"
    review = serialized.get("review")
    if isinstance(review, dict) and review:
        line = f"{line} review={_compact_json(review)}"
    data = serialized.get("data")
    if isinstance(data, dict) and data:
        line = f"{line} data={_compact_json(data)}"
    return line


def _format_api_metadata(metadata: dict[str, Any]) -> str:
    parts = []
    latency = _float_or_none(metadata.get("api_latency_ms"))
    if latency is not None:
        parts.append(f"latency={latency}ms")
    stop_reason = _string_or_none(metadata.get("stop_reason"))
    if stop_reason:
        parts.append(f"stop_reason={stop_reason}")
    input_tokens = _int_or_none(metadata.get("input_tokens"))
    if input_tokens is not None:
        parts.append(f"input_tokens={input_tokens}")
    output_tokens = _int_or_none(metadata.get("output_tokens"))
    if output_tokens is not None:
        parts.append(f"output_tokens={output_tokens}")
    return ", ".join(parts)


def _pretty_json_or_text(text: str) -> str:
    candidate = text.strip()
    if len(candidate) > _MAX_RAW_RESPONSE_CHARS:
        candidate = f"{candidate[:_MAX_RAW_RESPONSE_CHARS].rstrip()}\n... [truncated]"
    try:
        parsed = json.loads(candidate)
    except json.JSONDecodeError:
        return candidate
    return json.dumps(parsed, indent=2, sort_keys=True)


def _render_text_block(text: str, *, indent: str) -> list[str]:
    return [f"{indent}{line}" for line in text.splitlines() or [""]]


def _compact_json(value: Any) -> str:
    try:
        return json.dumps(value, sort_keys=True)
    except TypeError:
        return repr(value)


def _string_or_none(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def _int_or_none(value: Any) -> int | None:
    return value if isinstance(value, int) else None


def _float_or_none(value: Any) -> float | None:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None
