from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

from mettagrid_sdk.sdk import (
    BeliefMemoryRecord,
    EventMemoryRecord,
    GridPosition,
    MemoryQuery,
    MemoryRecord,
    PlanMemoryRecord,
    RetrievedMemoryRecord,
    SemanticEvent,
)

from cvc.cogent.player_cog.memory.retrieval import render_retrieved_context, retrieve_records
from cvc.cogent.player_cog.scratchpad import SCRATCHPAD_LINE_RE, parse_scratchpad_value, render_scratchpad_value

_MISSING = object()


class MemoryStore:
    _scratchpad_locks: dict[Path, threading.Lock] = {}
    _scratchpad_locks_guard = threading.Lock()

    def __init__(
        self,
        records: list[MemoryRecord] | None = None,
        *,
        backing_file: Path | None = None,
        scratchpad_file: Path | None = None,
    ) -> None:
        self._records = [] if records is None else list(records)
        self._backing_file = backing_file
        self._scratchpad_file = scratchpad_file
        if self._backing_file is not None:
            self._backing_file.parent.mkdir(parents=True, exist_ok=True)
        if self._scratchpad_file is not None:
            self._scratchpad_file.parent.mkdir(parents=True, exist_ok=True)

    @classmethod
    def from_file(cls, backing_file: Path, *, scratchpad_file: Path | None = None) -> "MemoryStore":
        if not backing_file.exists():
            return cls(backing_file=backing_file, scratchpad_file=scratchpad_file)
        records = []
        for line in backing_file.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            records.append(_parse_record(json.loads(line)))
        return cls(records, backing_file=backing_file, scratchpad_file=scratchpad_file)

    def append_record(self, record: MemoryRecord) -> None:
        self._records.append(record)
        if self._backing_file is not None:
            with self._backing_file.open("a", encoding="utf-8") as handle:
                handle.write(record.model_dump_json() + "\n")

    def append_event(
        self,
        *,
        record_id: str,
        event_type: str,
        summary: str,
        game: str,
        step: int | None,
        role_context: str | None,
        tags: list[str] | None = None,
        importance: float = 0.0,
        source: str = "",
        evidence_ids: list[str] | None = None,
        location: GridPosition | None = None,
        region_id: str | None = None,
    ) -> EventMemoryRecord:
        record = EventMemoryRecord(
            record_id=record_id,
            event_type=event_type,
            summary=summary,
            game=game,
            step=step,
            role_context=role_context,
            tags=[] if tags is None else tags,
            importance=importance,
            source=source,
            evidence_ids=[] if evidence_ids is None else evidence_ids,
            location=location,
            region_id=region_id,
        )
        self.append_record(record)
        return record

    def append_plan(
        self,
        *,
        record_id: str,
        plan_type: str,
        summary: str,
        game: str,
        step: int | None,
        role_context: str | None,
        tags: list[str] | None = None,
        importance: float = 0.0,
        source: str = "",
        evidence_ids: list[str] | None = None,
        location: GridPosition | None = None,
        region_id: str | None = None,
        status: str = "active",
    ) -> PlanMemoryRecord:
        record = PlanMemoryRecord(
            record_id=record_id,
            plan_type=plan_type,
            summary=summary,
            game=game,
            step=step,
            role_context=role_context,
            tags=[] if tags is None else tags,
            importance=importance,
            source=source,
            evidence_ids=[] if evidence_ids is None else evidence_ids,
            location=location,
            region_id=region_id,
            status=status,
        )
        self.append_record(record)
        return record

    def append_belief(
        self,
        *,
        record_id: str,
        belief_type: str,
        summary: str,
        game: str,
        step: int | None,
        role_context: str | None,
        tags: list[str] | None = None,
        importance: float = 0.0,
        confidence: float = 0.0,
        source: str = "",
        evidence_ids: list[str] | None = None,
        location: GridPosition | None = None,
        region_id: str | None = None,
    ) -> BeliefMemoryRecord:
        record = BeliefMemoryRecord(
            record_id=record_id,
            belief_type=belief_type,
            summary=summary,
            game=game,
            step=step,
            role_context=role_context,
            tags=[] if tags is None else tags,
            importance=importance,
            confidence=confidence,
            source=source,
            evidence_ids=[] if evidence_ids is None else evidence_ids,
            location=location,
            region_id=region_id,
        )
        self.append_record(record)
        return record

    def append_semantic_events(
        self,
        events: list[SemanticEvent],
        *,
        game: str,
        role_context: str | None,
        tags: list[str] | None = None,
        source: str = "semantic_event",
    ) -> list[EventMemoryRecord]:
        created_records = []
        for event in events:
            event_tags = set([] if tags is None else tags)
            event_tags.add(event.event_type)
            created_records.append(
                self.append_event(
                    record_id=event.event_id,
                    event_type=event.event_type,
                    summary=event.summary,
                    game=game,
                    step=event.step,
                    role_context=role_context,
                    tags=sorted(event_tags),
                    importance=event.importance,
                    source=source,
                    evidence_ids=event.evidence,
                    location=event.location,
                )
            )
        return created_records

    def recent_records(self, limit: int = 10) -> list[MemoryRecord]:
        return self._records[-limit:]

    def retrieve(self, query: MemoryQuery, limit: int = 10) -> list[RetrievedMemoryRecord]:
        return retrieve_records(self._records, query, limit=limit)

    def render_prompt_context(self, query: MemoryQuery, limit: int = 6) -> str:
        sections: list[str] = []
        scratchpad = self.read_scratchpad().strip()
        if scratchpad:
            sections.append(f"=== PRIVATE SCRATCHPAD ===\n{scratchpad}")
        retrieved = render_retrieved_context(self.retrieve(query, limit=limit))
        if retrieved:
            sections.append(retrieved)
        return "\n\n".join(sections)

    def read_scratchpad(self) -> str:
        if self._scratchpad_file is None or not self._scratchpad_file.exists():
            return ""
        return self._scratchpad_file.read_text(encoding="utf-8")

    def replace_scratchpad(self, text: str) -> None:
        if self._scratchpad_file is None:
            return
        self._write_scratchpad(text)

    def append_scratchpad(self, text: str) -> None:
        if self._scratchpad_file is None:
            return
        with self._scratchpad_lock():
            self._write_scratchpad_locked(self.read_scratchpad() + text)

    def get(self, key: str, default: Any = None) -> Any:
        value = self._scratchpad_value(key)
        return default if value is _MISSING else value

    def __contains__(self, key: object) -> bool:
        return isinstance(key, str) and self._scratchpad_value(key) is not _MISSING

    def __getitem__(self, key: str) -> Any:
        value = self._scratchpad_value(key)
        if value is _MISSING:
            raise KeyError(key)
        return value

    def __setitem__(self, key: str, value: Any) -> None:
        if self._scratchpad_file is None:
            return
        rendered_value = render_scratchpad_value(value)
        with self._scratchpad_lock():
            lines = self.read_scratchpad().splitlines()
            updated_lines: list[str] = []
            replaced = False
            for line in lines:
                match = SCRATCHPAD_LINE_RE.match(line)
                if match is None or match.group("key") != key:
                    updated_lines.append(line)
                    continue
                if not replaced:
                    updated_lines.append(f"{match.group('prefix')}{key}: {rendered_value}")
                    replaced = True
            if not replaced:
                updated_lines.append(f"- {key}: {rendered_value}" if updated_lines else f"{key}: {rendered_value}")
            self._write_scratchpad_locked("\n".join(updated_lines))

    def _scratchpad_value(self, key: str) -> Any:
        for line in reversed(self.read_scratchpad().splitlines()):
            match = SCRATCHPAD_LINE_RE.match(line)
            if match is None or match.group("key") != key:
                continue
            return parse_scratchpad_value(match.group("value"))
        return _MISSING

    def _write_scratchpad(self, text: str) -> None:
        with self._scratchpad_lock():
            self._write_scratchpad_locked(text)

    def _write_scratchpad_locked(self, text: str) -> None:
        assert self._scratchpad_file is not None
        tmp_path = self._scratchpad_file.with_suffix(f"{self._scratchpad_file.suffix}.tmp")
        tmp_path.write_text(text, encoding="utf-8")
        tmp_path.replace(self._scratchpad_file)

    def _scratchpad_lock(self) -> threading.Lock:
        assert self._scratchpad_file is not None
        resolved = self._scratchpad_file.resolve()
        with self._scratchpad_locks_guard:
            if resolved not in self._scratchpad_locks:
                self._scratchpad_locks[resolved] = threading.Lock()
            return self._scratchpad_locks[resolved]


def _parse_record(payload: dict[str, Any]) -> MemoryRecord:
    kind = payload["kind"]
    if kind == "event":
        return EventMemoryRecord.model_validate(payload)
    if kind == "plan":
        return PlanMemoryRecord.model_validate(payload)
    if kind == "belief":
        return BeliefMemoryRecord.model_validate(payload)
    return MemoryRecord.model_validate(payload)
