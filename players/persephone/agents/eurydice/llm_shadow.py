"""Offline shadow evaluation helpers for Eurydice LLM decisions."""

from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass, field
import json
from pathlib import Path
from typing import Any, Iterable

from agents.eurydice.llm_context import SCHEMA_VERSION
from agents.eurydice.llm_prompts import build_prompt, infer_surface
from agents.eurydice.llm_provider import LLMProvider
from agents.eurydice.llm_validator import validate_llm_decision


@dataclass
class ShadowDecisionRecord:
    """One evaluated context and provider decision."""

    context_hash: str
    surface: str
    accepted: bool
    action: str | None
    fallback_action: str
    reasons: list[str] = field(default_factory=list)


@dataclass
class ShadowSummary:
    """Aggregate result for an offline shadow run."""

    contexts_total: int = 0
    accepted: int = 0
    rejected: int = 0
    actions: dict[str, int] = field(default_factory=dict)
    rejection_reasons: dict[str, int] = field(default_factory=dict)
    records: list[ShadowDecisionRecord] = field(default_factory=list)


def load_contexts(path: Path) -> list[dict[str, Any]]:
    """Load full LLM context packets from a JSON/JSONL file or directory."""

    contexts: list[dict[str, Any]] = []
    for file_path in _context_files(path):
        for entry in _entries(file_path):
            context = _context_from_entry(entry)
            if context is not None:
                contexts.append(context)
    return contexts


def evaluate_contexts(
    contexts: Iterable[dict[str, Any]],
    provider: LLMProvider,
) -> ShadowSummary:
    """Run a provider over contexts, validate outputs, and aggregate results."""

    actions: Counter[str] = Counter()
    reasons: Counter[str] = Counter()
    records: list[ShadowDecisionRecord] = []
    accepted = 0
    rejected = 0
    total = 0

    for context in contexts:
        total += 1
        surface = infer_surface(context)
        prompt = build_prompt(context, surface=surface)
        raw_decision = provider.decide(context, prompt)
        result = validate_llm_decision(raw_decision, context)
        action = (
            result.decision.get("action")
            if result.accepted
            else raw_decision.get("action")
            if isinstance(raw_decision, dict)
            else None
        )
        if result.accepted:
            accepted += 1
            actions[str(action)] += 1
        else:
            rejected += 1
            for reason in result.reasons:
                reasons[reason] += 1
        records.append(
            ShadowDecisionRecord(
                context_hash=result.context_hash,
                surface=surface,
                accepted=result.accepted,
                action=str(action) if action is not None else None,
                fallback_action=str(result.fallback_decision.get("action")),
                reasons=list(result.reasons),
            )
        )

    return ShadowSummary(
        contexts_total=total,
        accepted=accepted,
        rejected=rejected,
        actions=dict(sorted(actions.items())),
        rejection_reasons=dict(sorted(reasons.items())),
        records=records,
    )


def summary_json(summary: ShadowSummary) -> str:
    """Serialize a shadow summary as deterministic JSON."""

    return json.dumps(asdict(summary), sort_keys=True)


def _context_files(path: Path):
    if path.is_file():
        yield path
        return
    if not path.exists():
        return
    for file_path in sorted(path.rglob("*")):
        if file_path.suffix in {".json", ".jsonl", ".log", ".txt"}:
            yield file_path


def _entries(path: Path):
    with path.open("r", encoding="utf-8") as handle:
        text = handle.read()
    stripped = text.strip()
    if not stripped:
        return
    if path.suffix == ".json" and stripped.startswith("["):
        parsed = json.loads(stripped)
        if isinstance(parsed, list):
            for item in parsed:
                if isinstance(item, dict):
                    yield item
        return
    if path.suffix == ".json" and stripped.startswith("{"):
        parsed = json.loads(stripped)
        if isinstance(parsed, dict):
            yield parsed
        return
    for line in stripped.splitlines():
        start = line.find("{")
        if start < 0:
            continue
        try:
            parsed = json.loads(line[start:])
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            yield parsed


def _context_from_entry(entry: dict[str, Any]) -> dict[str, Any] | None:
    if entry.get("schema_version") == SCHEMA_VERSION:
        return entry
    context = entry.get("context")
    if isinstance(context, dict) and context.get("schema_version") == SCHEMA_VERSION:
        return context
    return None


__all__ = [
    "ShadowDecisionRecord",
    "ShadowSummary",
    "evaluate_contexts",
    "load_contexts",
    "summary_json",
]
