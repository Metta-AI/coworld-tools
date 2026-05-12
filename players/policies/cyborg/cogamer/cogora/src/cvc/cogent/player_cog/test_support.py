from __future__ import annotations

from pathlib import Path
from typing import Any

from mettagrid_sdk.sdk import (
    ActionCatalog,
    ActionDescriptor,
    GridPosition,
    KnownWorldState,
    LogRecord,
    MemoryQuery,
    MemoryRecord,
    MettagridSDK,
    MettagridState,
    RetrievedMemoryRecord,
    ReviewRequest,
    SelfState,
    SemanticEntity,
    StateHelperCatalog,
    TeamSummary,
)

from cvc.cogent.player_cog.runtime import ArtifactStore
from cvc.cogent.player_cog.scratchpad import parse_scratchpad_value, render_scratchpad_value


class RecordingLogSink:
    def __init__(self) -> None:
        self.records: list[LogRecord] = []

    def write(self, record: LogRecord) -> None:
        self.records.append(record)


class ScratchpadMemoryStub:
    def __init__(
        self,
        *,
        records: list[MemoryRecord] | None = None,
        scratchpad: str = "Hold east.",
        prompt_context: str | None = None,
        retrieved_score: float = 1.0,
        relevance_score: float = 1.0,
        recency_score: float = 0.0,
        importance_score: float = 0.0,
    ) -> None:
        self._records = list(records or [MemoryRecord(record_id="evt-1", kind="event", summary="opening")])
        self._scratchpad = scratchpad
        self._prompt_context = prompt_context
        self._retrieved_score = retrieved_score
        self._relevance_score = relevance_score
        self._recency_score = recency_score
        self._importance_score = importance_score

    def recent_records(self, limit: int = 10) -> list[MemoryRecord]:
        return self._records[:limit]

    def retrieve(self, query: MemoryQuery, limit: int = 10) -> list[RetrievedMemoryRecord]:
        del query
        return [
            RetrievedMemoryRecord(
                record=record,
                score=self._retrieved_score,
                relevance_score=self._relevance_score,
                recency_score=self._recency_score,
                importance_score=self._importance_score,
            )
            for record in self._records[:limit]
        ]

    def render_prompt_context(self, query: MemoryQuery, limit: int = 6) -> str:
        del query, limit
        if self._prompt_context is not None:
            return self._prompt_context
        if not self._records:
            return ""
        record = self._records[0]
        prefix = f"step={record.step} " if record.step is not None else ""
        return f"=== RETRIEVED SEMANTIC MEMORY ===\n  - [{record.kind}] {prefix}{record.summary}".rstrip()

    def read_scratchpad(self) -> str:
        return self._scratchpad

    def replace_scratchpad(self, text: str) -> None:
        self._scratchpad = text

    def append_scratchpad(self, text: str) -> None:
        self._scratchpad += text

    def get(self, key: str, default: object = None) -> object:
        prefix = f"{key}: "
        for line in self._scratchpad.splitlines():
            if line.startswith(prefix):
                return parse_scratchpad_value(line[len(prefix) :])
        return default

    def __contains__(self, key: object) -> bool:
        return isinstance(key, str) and self.get(key, None) is not None

    def __getitem__(self, key: str) -> object:
        value = self.get(key, None)
        if value is None:
            raise KeyError(key)
        return value

    def __setitem__(self, key: str, value: object) -> None:
        prefix = f"{key}: "
        updated_lines: list[str] = []
        replaced = False
        for line in self._scratchpad.splitlines():
            if line.startswith(prefix):
                updated_lines.append(f"{key}: {render_scratchpad_value(value)}")
                replaced = True
            else:
                updated_lines.append(line)
        if not replaced:
            updated_lines.append(f"{key}: {render_scratchpad_value(value)}")
        self._scratchpad = "\n".join(updated_lines)


def build_artifact_store(root: Path) -> ArtifactStore:
    return ArtifactStore(
        main_file=root / "main.py",
        strategy_file=root / "plan.md",
        scratchpad_file=root / "memory.md",
        log_file=root / "transcript.log",
        experience_file=root / "experience.jsonl",
        decision_file=root / "decisions.jsonl",
        generation_file=root / "generation.jsonl",
        execution_file=root / "execution.jsonl",
    )


def build_sdk(
    *,
    state: MettagridState | None = None,
    actions: ActionCatalog | None = None,
    helpers: object | None = None,
    memory: object | None = None,
    log: RecordingLogSink | None = None,
) -> tuple[MettagridSDK, RecordingLogSink]:
    resolved_state = state or build_state(
        step=5,
        shared_inventory={"carbon": 4},
        shared_objectives=["missing_resource:oxygen"],
    )
    resolved_log = RecordingLogSink() if log is None else log
    return (
        MettagridSDK(
            state=resolved_state,
            actions=actions
            or ActionCatalog([ActionDescriptor(name="return_macro_directive", description="return a directive")]),
            helpers=StateHelperCatalog(resolved_state) if helpers is None else helpers,
            memory=ScratchpadMemoryStub() if memory is None else memory,
            log=resolved_log,
        ),
        resolved_log,
    )


def build_state(
    *,
    step: int,
    agent_id: int = 0,
    role: str | None = None,
    inventory: dict[str, int] | None = None,
    labels: list[str] | None = None,
    status: list[str] | None = None,
    attributes: dict[str, str | int | float | bool] | None = None,
    visible_entities: list[SemanticEntity] | None = None,
    known_world: KnownWorldState | None = None,
    shared_inventory: dict[str, int] | None = None,
    shared_objectives: list[str] | None = None,
    recent_events: list[Any] | None = None,
    team_id: str = "cogs",
) -> MettagridState:
    self_attributes: dict[str, str | int | float | bool] = {"agent_id": agent_id, "team": team_id}
    if attributes is not None:
        self_attributes.update(attributes)
    return MettagridState(
        game="cogsguard",
        step=step,
        self_state=SelfState(
            entity_id=f"agent-{agent_id}",
            entity_type="agent",
            position=GridPosition(x=0, y=0),
            role=role,
            inventory={} if inventory is None else inventory,
            labels=[] if labels is None else labels,
            status=[] if status is None else status,
            attributes=self_attributes,
        ),
        visible_entities=[] if visible_entities is None else visible_entities,
        known_world=KnownWorldState() if known_world is None else known_world,
        team_summary=TeamSummary(
            team_id=team_id,
            shared_inventory={} if shared_inventory is None else shared_inventory,
            shared_objectives=[] if shared_objectives is None else shared_objectives,
        ),
        recent_events=[] if recent_events is None else recent_events,
    )


def neutral_junction(
    *,
    entity_id: str = "junction@1,0",
    position: tuple[int, int] = (1, 0),
    owner: str = "neutral",
) -> SemanticEntity:
    return SemanticEntity(
        entity_id=entity_id,
        entity_type="junction",
        position=GridPosition(x=position[0], y=position[1]),
        labels=["neutral"],
        attributes={"owner": owner},
    )


def review_log(
    *,
    trigger_name: str,
    prompt: str,
    step: int,
    message: str,
) -> LogRecord:
    return LogRecord(
        level="info",
        message=message,
        step=step,
        review=ReviewRequest(trigger_name=trigger_name, prompt=prompt),
    )
