from __future__ import annotations

import re
from collections.abc import Sequence

from mettagrid_sdk.sdk import (
    BeliefMemoryRecord,
    EventMemoryRecord,
    MemoryQuery,
    MemoryRecord,
    PlanMemoryRecord,
    RetrievedMemoryRecord,
)

_TOKEN_RE = re.compile(r"[a-z0-9_]+")


def retrieve_records(
    records: Sequence[MemoryRecord],
    query: MemoryQuery,
    *,
    limit: int = 6,
) -> list[RetrievedMemoryRecord]:
    scored_records = [_score_record(record, query) for record in records]
    scored_records = [item for item in scored_records if item.relevance_score >= 0.2]
    scored_records.sort(
        key=lambda item: (
            -item.score,
            -(item.record.importance),
            -(item.record.step or -1),
            item.record.record_id,
        )
    )
    return scored_records[:limit]


def render_retrieved_context(records: Sequence[RetrievedMemoryRecord]) -> str:
    if not records:
        return ""

    lines = ["=== RETRIEVED SEMANTIC MEMORY ==="]
    for item in records:
        record = item.record
        tag_text = ", ".join(record.tags[:4]) or "none"
        location_text = "unknown"
        typed_label = _record_label(record)
        if record.location is not None:
            location_text = f"({record.location.x},{record.location.y})"
        lines.append(
            f"  - [{record.kind}:{typed_label}] step={record.step} score={item.score:.2f} role={record.role_context} "
            f"loc={location_text} tags[{tag_text}] {record.summary}"
        )
    return "\n".join(lines)


def _score_record(record: MemoryRecord, query: MemoryQuery) -> RetrievedMemoryRecord:
    relevance_score = _relevance_score(record, query)
    recency_score = _recency_score(record, query)
    importance_score = _importance_score(record)
    total_score = round(relevance_score * 0.6 + recency_score * 0.2 + importance_score * 0.2, 4)
    return RetrievedMemoryRecord(
        record=record,
        score=total_score,
        relevance_score=round(relevance_score, 4),
        recency_score=round(recency_score, 4),
        importance_score=round(importance_score, 4),
    )


def _relevance_score(record: MemoryRecord, query: MemoryQuery) -> float:
    score = 0.0
    if query.game is not None and record.game == query.game:
        score += 0.15
    if query.role_context is not None and record.role_context == query.role_context:
        score += 0.3

    record_tags = set(record.tags)
    query_tags = set(query.target_tags)
    if query_tags:
        score += 0.35 * (len(record_tags & query_tags) / len(query_tags))

    active_plan = query.active_plan
    if active_plan is not None:
        if active_plan in record.tags or active_plan == record.summary:
            score += 0.15
        if isinstance(record, PlanMemoryRecord) and record.plan_type == active_plan:
            score += 0.15

    query_tokens = set(_TOKEN_RE.findall(query.text.lower()))
    if query_tokens:
        record_tokens = set(_TOKEN_RE.findall(record.summary.lower())) | record_tags
        score += 0.2 * (len(query_tokens & record_tokens) / len(query_tokens))

    return min(score, 1.0)


def _recency_score(record: MemoryRecord, query: MemoryQuery) -> float:
    if record.step is None or query.step is None:
        return 0.0
    if record.step > query.step:
        return 0.0
    step_distance = query.step - record.step
    return 1.0 / (1.0 + (step_distance / 20.0))


def _importance_score(record: MemoryRecord) -> float:
    return max(0.0, min(record.importance, 1.0))


def _record_label(record: MemoryRecord) -> str:
    if isinstance(record, EventMemoryRecord):
        return record.event_type
    if isinstance(record, PlanMemoryRecord):
        return record.plan_type
    if isinstance(record, BeliefMemoryRecord):
        return record.belief_type
    return record.record_id
