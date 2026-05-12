from __future__ import annotations

import ast
import inspect
import signal
import threading
import time
from collections import Counter
from dataclasses import replace
from types import MappingProxyType
from typing import Any, cast

from mettagrid_sdk.games.cogsguard import CogsguardPromptAdapter
from mettagrid_sdk.sdk import LogRecord, MemoryQuery, MettagridSDK, ReviewRequest
from pydantic import BaseModel, Field

_DEADLINE_CHECK_NAME = "policy_check_deadline"
_COGSGUARD_PROMPT_ADAPTER = CogsguardPromptAdapter()
_SAFE_BUILTINS = MappingProxyType(
    {
        "abs": abs,
        "all": all,
        "any": any,
        "bool": bool,
        "dict": dict,
        "enumerate": enumerate,
        "Exception": Exception,
        "float": float,
        "getattr": getattr,
        "hasattr": hasattr,
        "int": int,
        "isinstance": isinstance,
        "len": len,
        "list": list,
        "max": max,
        "min": min,
        "next": next,
        "range": range,
        "reversed": reversed,
        "set": set,
        "sorted": sorted,
        "str": str,
        "sum": sum,
        "tuple": tuple,
        "zip": zip,
    }
)
DEFAULT_POLICY_TIMEOUT_SECONDS = 0.25


class PolicyUpdate(BaseModel):
    source: str


class PolicyExecutionResult(BaseModel):
    success: bool
    return_value: Any = None
    return_repr: str = ""
    logs: list[LogRecord] = Field(default_factory=list)
    error_type: str | None = None
    error_message: str | None = None


class PolicyExecutionRecord(BaseModel):
    step: int
    agent_id: int
    policy_source: str
    result: PolicyExecutionResult


class BoundedPolicyError(ValueError):
    pass


class PolicyExecutionTimeoutError(TimeoutError):
    pass


class CompiledPolicy:
    def __init__(self, *, source: str, step_fn: Any, namespace: dict[str, Any]) -> None:
        self.source = source
        self.step_fn = step_fn
        self.namespace = namespace


class BufferedLogSink:
    def __init__(self, downstream: Any) -> None:
        self._downstream = downstream
        self.records: list[LogRecord] = []

    def write(self, record: LogRecord) -> None:
        self.records.append(record)
        self._downstream.write(record)


def compile_policy(policy_update: PolicyUpdate) -> CompiledPolicy:
    module = ast.parse(policy_update.source, mode="exec")
    _validate_policy_ast(module)
    instrumented_module = _inject_deadline_checks(module)
    ast.fix_missing_locations(instrumented_module)

    namespace: dict[str, Any] = {
        "__builtins__": _SAFE_BUILTINS,
        "LogRecord": LogRecord,
        "ReviewRequest": ReviewRequest,
        _DEADLINE_CHECK_NAME: _noop_deadline_check,
    }
    exec(compile(instrumented_module, "<mettagrid-sdk-policy>", "exec"), namespace, namespace)
    if "step" not in namespace or not callable(namespace["step"]):
        raise BoundedPolicyError("policy must define callable step(sdk)")
    step_fn = namespace["step"]
    _validate_step_signature(step_fn)
    return CompiledPolicy(source=policy_update.source, step_fn=step_fn, namespace=namespace)


def execute_compiled_policy(
    compiled_policy: CompiledPolicy,
    sdk: MettagridSDK,
    *,
    timeout_seconds: float = DEFAULT_POLICY_TIMEOUT_SECONDS,
) -> PolicyExecutionResult:
    buffered_log = BufferedLogSink(sdk.log)
    sandbox_sdk = replace(sdk, log=buffered_log)
    try:
        return_value = _run_step_with_timeout(compiled_policy, sandbox_sdk, timeout_seconds=timeout_seconds)
    except Exception as exc:
        return PolicyExecutionResult(
            success=False,
            return_repr="",
            logs=buffered_log.records,
            error_type=type(exc).__name__,
            error_message=str(exc),
        )

    return PolicyExecutionResult(
        success=True,
        return_value=return_value,
        return_repr=_format_return_value(return_value),
        logs=buffered_log.records,
    )


def render_sdk_reference(sdk: MettagridSDK, *, memory_limit: int = 5) -> str:
    state = sdk.state
    visible_counts = Counter(entity.entity_type for entity in state.visible_entities)
    visible_text = ", ".join(f"{name}={visible_counts[name]}" for name in sorted(visible_counts)) or "none"
    action_lines = [f"- {action.name}: {action.description}" for action in sdk.actions.list_actions()] or ["- none"]
    helper_lines = [f"- {helper.name}: {helper.description}" for helper in sdk.helpers.list_capabilities()] or [
        "- none"
    ]
    memory_query = MemoryQuery.from_state(state)
    retrieved_records = sdk.memory.retrieve(memory_query, limit=memory_limit)
    memory_lines = [f"- {item.record.kind}:{item.record.record_id} {item.record.summary}" for item in retrieved_records]
    if not memory_lines:
        memory_lines = [
            f"- {record.kind}:{record.record_id} {record.summary}"
            for record in sdk.memory.recent_records(limit=memory_limit)
        ]
    if not memory_lines:
        memory_lines = ["- none"]
    scratchpad_text = sdk.memory.read_scratchpad().strip()
    progress_lines = ["- none"] if sdk.progress is None else sdk.progress.render(max_metrics=None).splitlines()
    cogsguard_notes = []
    if state.game == "cogsguard":
        objective = "" if sdk.progress is None else sdk.progress.objective
        cogsguard_notes = _COGSGUARD_PROMPT_ADAPTER.render_reference_notes(
            objective=objective,
            progress=sdk.progress,
        ).splitlines()
    return "\n".join(
        [
            "METTAGRID SDK",
            f"game: {state.game}",
            f"step: {state.step}",
            f"self: {state.self_state.entity_id} role={state.self_state.role} "
            f"pos=({state.self_state.position.x}, {state.self_state.position.y})",
            f"visible_entities: {visible_text}",
            "ACTIONS",
            *action_lines,
            "HELPERS",
            *helper_lines,
            "CONTROL PRIMITIVES",
            "- role/objective: choose the semantic baseline behavior family and current phase",
            "- target_entity_id: exact focus lock for one visible extractor, junction, or other known entity",
            "- target_region: broader lane or region steering when one exact entity should not be pinned yet",
            "- resource_bias: resource-type preference only; not a hard lock on one extractor",
            "PROGRESS",
            *progress_lines,
            "COGSGUARD NOTES",
            *(cogsguard_notes or ["- none"]),
            "MEMORY",
            *memory_lines,
            "SCRATCHPAD",
            scratchpad_text or "- none",
        ]
    )


def _validate_policy_ast(module: ast.Module) -> None:
    for node in ast.walk(module):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            raise BoundedPolicyError("imports are not allowed in sdk policy code")
        if isinstance(node, (ast.Global, ast.Nonlocal)):
            raise BoundedPolicyError("global and nonlocal declarations are not allowed in sdk policy code")
        if isinstance(node, ast.Name) and node.id.startswith("__"):
            raise BoundedPolicyError("dunder names are not allowed in sdk policy code")
        if isinstance(node, ast.Attribute) and node.attr.startswith("__"):
            raise BoundedPolicyError("dunder attributes are not allowed in sdk policy code")

    for node in module.body:
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
            continue
        if isinstance(node, ast.FunctionDef):
            continue
        raise BoundedPolicyError("policy may only contain top-level function definitions")


def _validate_step_signature(step_fn: Any) -> None:
    signature = inspect.signature(step_fn)
    parameters = list(signature.parameters.values())
    if len(parameters) != 1:
        raise BoundedPolicyError("policy step must have signature step(sdk)")
    parameter = parameters[0]
    if parameter.kind not in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD):
        raise BoundedPolicyError("policy step must have signature step(sdk)")
    if parameter.name != "sdk":
        raise BoundedPolicyError("policy step must have signature step(sdk)")


def _format_return_value(value: Any) -> str:
    if isinstance(value, str):
        return value
    return repr(value)


def _noop_deadline_check() -> None:
    return None


def _supports_signal_timeout() -> bool:
    return (
        getattr(signal, "SIGALRM", None) is not None
        and getattr(signal, "ITIMER_REAL", None) is not None
        and callable(getattr(signal, "setitimer", None))
    )


def _inject_deadline_checks(module: ast.Module) -> ast.Module:
    return _DeadlineCheckInjector().visit(module)


def _is_docstring_statement(node: ast.stmt) -> bool:
    return isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str)


class _DeadlineCheckInjector(ast.NodeTransformer):
    def _check_statement(self, template_node: ast.AST) -> ast.Expr:
        return ast.copy_location(
            ast.Expr(
                value=ast.Call(
                    func=ast.Name(id=_DEADLINE_CHECK_NAME, ctx=ast.Load()),
                    args=[],
                    keywords=[],
                )
            ),
            template_node,
        )

    def _prepend_check(self, body: list[ast.stmt], template_node: ast.AST) -> list[ast.stmt]:
        insert_at = 1 if body and _is_docstring_statement(body[0]) else 0
        return [*body[:insert_at], self._check_statement(template_node), *body[insert_at:]]

    def visit_FunctionDef(self, node: ast.FunctionDef) -> ast.AST:  # noqa: N802
        node = cast(ast.FunctionDef, self.generic_visit(node))
        node.body = self._prepend_check(node.body, node)
        return node

    def visit_For(self, node: ast.For) -> ast.AST:  # noqa: N802
        node = cast(ast.For, self.generic_visit(node))
        node.body = self._prepend_check(node.body, node)
        return node

    def visit_While(self, node: ast.While) -> ast.AST:  # noqa: N802
        node = cast(ast.While, self.generic_visit(node))
        node.body = self._prepend_check(node.body, node)
        return node


def _run_step_with_timeout(compiled_policy: CompiledPolicy, sdk: Any, *, timeout_seconds: float) -> Any:
    previous_deadline_check = compiled_policy.namespace.get(_DEADLINE_CHECK_NAME, _noop_deadline_check)
    if timeout_seconds <= 0:
        compiled_policy.namespace[_DEADLINE_CHECK_NAME] = _noop_deadline_check
        try:
            return compiled_policy.step_fn(sdk)
        finally:
            compiled_policy.namespace[_DEADLINE_CHECK_NAME] = previous_deadline_check

    deadline = time.perf_counter() + timeout_seconds

    def _cooperative_deadline_check() -> None:
        if time.perf_counter() >= deadline:
            raise PolicyExecutionTimeoutError(f"policy step exceeded {timeout_seconds:.2f}s timeout")

    compiled_policy.namespace[_DEADLINE_CHECK_NAME] = _cooperative_deadline_check

    if not _supports_signal_timeout() or threading.current_thread() is not threading.main_thread():
        try:
            return compiled_policy.step_fn(sdk)
        finally:
            compiled_policy.namespace[_DEADLINE_CHECK_NAME] = previous_deadline_check

    previous_handler = signal.getsignal(signal.SIGALRM)

    def _handle_timeout(_signum, _frame) -> None:
        raise PolicyExecutionTimeoutError(f"policy step exceeded {timeout_seconds:.2f}s timeout")

    signal.signal(signal.SIGALRM, _handle_timeout)
    signal.setitimer(signal.ITIMER_REAL, timeout_seconds)
    try:
        return compiled_policy.step_fn(sdk)
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous_handler)
        compiled_policy.namespace[_DEADLINE_CHECK_NAME] = previous_deadline_check
