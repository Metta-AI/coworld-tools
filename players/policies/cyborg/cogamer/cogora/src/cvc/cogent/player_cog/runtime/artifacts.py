from __future__ import annotations

import os
import tempfile
import threading
import weakref
from pathlib import Path

from mettagrid_sdk.sdk import MemoryQuery, MemoryRecord

from cvc.cogent.player_cog.memory.store import MemoryStore
from cvc.cogent.player_cog.runtime.execution import PolicyExecutionRecord
from cvc.cogent.player_cog.runtime.models import ExperienceTraceRecord, PolicyGenerationRecord, ReviewDecisionRecord

_PYTHON_SHEBANG = "#!/usr/bin/env python3\n"
CODE_MODE_MAIN_FILE = "main.py"
CODE_MODE_PLAN_FILE = "plan.md"
CODE_MODE_MEMORY_FILE = "memory.md"
CODE_MODE_EXPERIENCE_FILE = "experience_trace.jsonl"
CODE_MODE_DECISION_FILE = "decision_log.jsonl"
CODE_MODE_TRANSCRIPT_FILE = "review_transcript.log"
DEBUG_ARTIFACT_DIR_ENV = "COG_CYBORG_DEBUG_ARTIFACT_DIR"
_DEBUG_ARTIFACT_PREFIX = "cog-cyborg-debug-"
_DEBUG_ERROR_PREFIXES = ("error:", "policy_update_error:", "review_error:")


def prepare_debug_artifact_root(root: Path | None) -> Path:
    if root is None:
        return Path(tempfile.mkdtemp(prefix=_DEBUG_ARTIFACT_PREFIX))
    resolved_root = root.expanduser().resolve()
    resolved_root.mkdir(parents=True, exist_ok=True)
    return resolved_root


def resolve_debug_artifact_root(root: str | Path | None) -> Path | None:
    if root is not None:
        return prepare_debug_artifact_root(Path(root))
    env_root = os.environ.get(DEBUG_ARTIFACT_DIR_ENV)
    if env_root is None:
        return None
    return prepare_debug_artifact_root(Path(env_root))


def render_debug_artifact_summary(artifact_root: Path, *, tail_lines: int) -> str:
    lines = ["Policy Debug Artifacts", str(artifact_root)]
    agent_roots = sorted(path for path in artifact_root.glob("agent-*") if path.is_dir())
    if not agent_roots:
        lines.append("No policy debug artifacts were written. The active policy may not support artifact_dir.")
        return "\n".join(lines)

    found_error = False
    found_transcript = False
    for agent_root in agent_roots:
        transcript_path = agent_root / CODE_MODE_TRANSCRIPT_FILE
        if not transcript_path.exists():
            continue
        found_transcript = True
        transcript_lines = transcript_path.read_text(encoding="utf-8", errors="ignore").splitlines()
        error_lines = [line for line in transcript_lines if line.startswith(_DEBUG_ERROR_PREFIXES)]
        if not error_lines:
            continue
        found_error = True
        lines.extend(["", f"{agent_root.name} errors", str(transcript_path), *error_lines[-tail_lines:]])
    if found_error:
        return "\n".join(lines)

    for agent_root in agent_roots:
        transcript_path = agent_root / CODE_MODE_TRANSCRIPT_FILE
        if not transcript_path.exists():
            continue
        transcript_lines = transcript_path.read_text(encoding="utf-8", errors="ignore").splitlines()
        tail = transcript_lines[-tail_lines:]
        if not tail:
            continue
        lines.extend(["", f"{agent_root.name} transcript tail", str(transcript_path), *tail])

    if not found_transcript:
        lines.append("No review transcripts were written yet.")
    return "\n".join(lines)


class ArtifactStore:
    """Persistent artifact store for a live code-mode bundle and its logs."""

    class _PathAppendLock:
        __slots__ = ("lock", "__weakref__")

        def __init__(self) -> None:
            self.lock = threading.Lock()

    _append_locks: weakref.WeakValueDictionary[Path, _PathAppendLock] = weakref.WeakValueDictionary()
    _append_locks_guard = threading.Lock()

    @classmethod
    def for_code_mode_bundle(
        cls,
        root: Path,
        *,
        log_file_name: str = CODE_MODE_TRANSCRIPT_FILE,
        prefix: str = "pilot",
    ) -> "ArtifactStore":
        return cls(
            main_file=root / CODE_MODE_MAIN_FILE,
            strategy_file=root / CODE_MODE_PLAN_FILE,
            scratchpad_file=root / CODE_MODE_MEMORY_FILE,
            log_file=root / log_file_name,
            experience_file=root / CODE_MODE_EXPERIENCE_FILE,
            decision_file=root / CODE_MODE_DECISION_FILE,
            execution_file=root / f"{prefix}_execution.jsonl",
            generation_file=root / f"{prefix}_generation.jsonl",
            semantic_memory_file=root / f"{prefix}_semantic_memory.jsonl",
        )

    def __init__(
        self,
        strategy_file: Path | None = None,
        log_file: Path | None = None,
        execution_file: Path | None = None,
        generation_file: Path | None = None,
        semantic_memory_file: Path | None = None,
        main_file: Path | None = None,
        scratchpad_file: Path | None = None,
        experience_file: Path | None = None,
        decision_file: Path | None = None,
    ) -> None:
        self.strategy_file = strategy_file
        self.log_file = log_file
        self.execution_file = execution_file
        self.generation_file = generation_file
        self.semantic_memory_file = semantic_memory_file
        self.main_file = main_file
        self.scratchpad_file = scratchpad_file
        self.experience_file = experience_file
        self.decision_file = decision_file

        for path in (
            strategy_file,
            log_file,
            execution_file,
            generation_file,
            semantic_memory_file,
            main_file,
            scratchpad_file,
            experience_file,
            decision_file,
        ):
            if path is not None:
                path.parent.mkdir(parents=True, exist_ok=True)

    def replace_plan(self, text: str) -> None:
        if self.strategy_file is None:
            return
        self.strategy_file.write_text(text, encoding="utf-8")

    def append_plan(self, text: str) -> None:
        if self.strategy_file is None:
            return
        self._append_text_atomic(self.strategy_file, text)

    def append_execution_record(self, record: PolicyExecutionRecord) -> None:
        if self.execution_file is None:
            return
        self._append_text_atomic(self.execution_file, record.model_dump_json() + "\n")

    def append_generation_record(self, record: PolicyGenerationRecord) -> None:
        if self.generation_file is None:
            return
        self._append_text_atomic(self.generation_file, record.model_dump_json() + "\n")

    def append_semantic_record(self, record: MemoryRecord) -> None:
        if self.semantic_memory_file is None:
            return
        self._append_text_atomic(self.semantic_memory_file, record.model_dump_json() + "\n")

    def append_log_text(self, text: str) -> None:
        if self.log_file is None:
            return
        if not text:
            return
        self._append_text_atomic(self.log_file, text)

    def write_main_source(self, source: str) -> None:
        if self.main_file is None:
            return
        text = source if source.startswith(_PYTHON_SHEBANG) else f"{_PYTHON_SHEBANG}{source.lstrip()}"
        self.main_file.write_text(text, encoding="utf-8")
        try:
            self.main_file.chmod(self.main_file.stat().st_mode | 0o755)
        except FileNotFoundError:
            return

    def read_main_source(self, max_chars: int = 6000) -> str:
        if self.main_file is None or not self.main_file.exists():
            return ""
        return _strip_python_shebang(self.main_file.read_text(encoding="utf-8"))[-max_chars:]

    def replace_scratchpad(self, text: str) -> None:
        if self.scratchpad_file is None:
            return
        self.scratchpad_file.write_text(text, encoding="utf-8")

    def append_scratchpad(self, text: str) -> None:
        if self.scratchpad_file is None:
            return
        self._append_text_atomic(self.scratchpad_file, text)

    def read_scratchpad(self, max_chars: int | None = None) -> str:
        if self.scratchpad_file is None or not self.scratchpad_file.exists():
            return ""
        text = self.scratchpad_file.read_text(encoding="utf-8")
        if max_chars is None:
            return text
        return text[-max_chars:]

    def append_experience_record(self, record: ExperienceTraceRecord) -> None:
        if self.experience_file is None:
            return
        self._append_text_atomic(self.experience_file, record.model_dump_json() + "\n")

    def append_decision_record(self, record: ReviewDecisionRecord) -> None:
        if self.decision_file is None:
            return
        self._append_text_atomic(self.decision_file, record.model_dump_json() + "\n")

    def read_strategy(self, max_chars: int = 4000) -> str:
        if self.strategy_file is None or not self.strategy_file.exists():
            return ""
        return self._read_tail_text(self.strategy_file, max_chars=max_chars).strip()

    def read_plan(self, max_chars: int = 4000) -> str:
        return self.read_strategy(max_chars=max_chars)

    def read_log_tail(self, max_chars: int = 3000) -> str:
        if self.log_file is None or not self.log_file.exists():
            return ""
        return self._read_tail_text(self.log_file, max_chars=max_chars).strip()

    def read_recent_execution_records(self, max_entries: int = 8) -> list[PolicyExecutionRecord]:
        if self.execution_file is None or not self.execution_file.exists():
            return []
        selected = self._read_tail_lines(self.execution_file, max_lines=max_entries)
        return [PolicyExecutionRecord.model_validate_json(line) for line in selected if line.strip()]

    def read_recent_generation_records(self, max_entries: int = 8) -> list[PolicyGenerationRecord]:
        if self.generation_file is None or not self.generation_file.exists():
            return []
        selected = self._read_tail_lines(self.generation_file, max_lines=max_entries)
        return [PolicyGenerationRecord.model_validate_json(line) for line in selected if line.strip()]

    def read_recent_semantic_records(self, max_entries: int = 8) -> list[MemoryRecord]:
        if self.semantic_memory_file is None or not self.semantic_memory_file.exists():
            return []
        store = MemoryStore.from_file(self.semantic_memory_file)
        return store.recent_records(limit=max_entries)

    def read_recent_experience_records(self, max_entries: int = 8) -> list[ExperienceTraceRecord]:
        if self.experience_file is None or not self.experience_file.exists():
            return []
        selected = self._read_tail_lines(self.experience_file, max_lines=max_entries)
        return [ExperienceTraceRecord.model_validate_json(line) for line in selected if line.strip()]

    def read_recent_decision_records(self, max_entries: int = 8) -> list[ReviewDecisionRecord]:
        if self.decision_file is None or not self.decision_file.exists():
            return []
        selected = self._read_tail_lines(self.decision_file, max_lines=max_entries)
        return [ReviewDecisionRecord.model_validate_json(line) for line in selected if line.strip()]

    def build_prompt_context(
        self,
        *,
        max_memory_entries: int = 8,
        max_strategy_chars: int = 4000,
        max_policy_chars: int = 6000,
        max_log_chars: int = 3000,
        include_main_source: bool = True,
        include_plan: bool = True,
        include_scratchpad: bool = True,
        max_semantic_records: int = 6,
        memory_query: MemoryQuery | None = None,
    ) -> str:
        sections: list[str] = []
        semantic_context = ""

        main_text = self.read_main_source(max_chars=max_policy_chars) if include_main_source else ""
        if main_text:
            sections.append(f"=== LIVE MAIN.PY ===\n{main_text}")

        strategy_text = self.read_strategy(max_chars=max_strategy_chars) if include_plan else ""
        if strategy_text:
            sections.append(f"=== LIVE PLAN.MD ===\n{strategy_text}")

        scratchpad_text = self.read_scratchpad(max_chars=max_strategy_chars) if include_scratchpad else ""
        if scratchpad_text:
            sections.append(f"=== PRIVATE SCRATCHPAD ===\n{scratchpad_text}")
        if self.semantic_memory_file is not None and self.semantic_memory_file.exists() and memory_query is not None:
            semantic_store = MemoryStore.from_file(self.semantic_memory_file)
            semantic_context = semantic_store.render_prompt_context(memory_query, limit=max_semantic_records)
            if semantic_context:
                sections.append(semantic_context)
        if self.semantic_memory_file is not None and self.semantic_memory_file.exists() and memory_query is None:
            semantic_records = self.read_recent_semantic_records(max_entries=max_semantic_records)
            if semantic_records:
                lines = ["=== SEMANTIC MEMORY RECORDS ==="]
                for record in semantic_records:
                    lines.append(f"  - [{record.kind}] step={record.step} {record.summary}")
                sections.append("\n".join(lines))
        log_tail = self.read_log_tail(max_chars=max_log_chars)
        if log_tail:
            sections.append(f"=== REVIEW TRANSCRIPT LOG ===\n{log_tail}")

        recent_execution = self.read_recent_execution_records(max_entries=max_memory_entries)
        if recent_execution:
            lines = ["=== SDK EXECUTION RECORDS ==="]
            for item in recent_execution:
                log_text = ", ".join(f"{record.level}:{record.message}" for record in item.result.logs[-3:]) or "none"
                outcome = item.result.return_repr or item.result.error_message or "none"
                lines.append(f"  - step {item.step}: success={item.result.success}, return={outcome}, logs[{log_text}]")
            sections.append("\n".join(lines))

        recent_generation = self.read_recent_generation_records(max_entries=max_memory_entries)
        if recent_generation:
            lines = ["=== SDK GENERATION RECORDS ==="]
            for item in recent_generation:
                policy_updated = "yes" if item.success and item.policy_source else "no"
                error_message = item.error_message or "none"
                lines.append(
                    f"  - step {item.step}: success={item.success}, "
                    f"policy_updated={policy_updated}, error={error_message}"
                )
            sections.append("\n".join(lines))

        recent_experience = self.read_recent_experience_records(max_entries=max_memory_entries)
        if recent_experience:
            lines = ["=== EXPERIENCE TRACE ==="]
            for item in recent_experience:
                log_text = ", ".join(item.logs[-3:]) or "none"
                return_text = item.return_repr or "none"
                lines.append(f"  - step {item.step}: return={return_text}, logs[{log_text}], obs={item.summary}")
            sections.append("\n".join(lines))

        recent_decisions = self.read_recent_decision_records(max_entries=max_memory_entries)
        if recent_decisions:
            lines = ["=== REVIEW DECISIONS ==="]
            for item in recent_decisions:
                lines.append(
                    f"  - step {item.step}: action={item.action}, trigger={item.trigger_name or 'none'}, "
                    f"request={item.request_summary or 'none'}, policy_updated={item.policy_updated}, "
                    f"scratchpad_updated={item.scratchpad_updated}, plan_updated={item.plan_updated}"
                )
            sections.append("\n".join(lines))

        return "\n\n".join(sections)

    @staticmethod
    def _read_tail_text(path: Path, max_chars: int) -> str:
        if max_chars <= 0:
            return ""

        target_bytes = max(4096, max_chars * 4)
        with path.open("rb") as handle:
            handle.seek(0, 2)
            size = handle.tell()
            read_size = min(size, target_bytes)
            handle.seek(size - read_size)
            data = handle.read(read_size)
        return data.decode("utf-8", errors="ignore")[-max_chars:]

    @staticmethod
    def _read_tail_lines(path: Path, max_lines: int) -> list[str]:
        if max_lines <= 0:
            return []

        block_size = 4096
        with path.open("rb") as handle:
            handle.seek(0, 2)
            file_size = handle.tell()
            if file_size == 0:
                return []

            data = b""
            offset = file_size
            while offset > 0 and data.count(b"\n") <= max_lines:
                read_size = min(block_size, offset)
                offset -= read_size
                handle.seek(offset)
                data = handle.read(read_size) + data

        return data.decode("utf-8", errors="ignore").splitlines()[-max_lines:]

    @classmethod
    def _append_text_atomic(cls, path: Path, text: str) -> None:
        path_lock = cls._lock_for_path(path)
        with path_lock.lock:
            with path.open("a", encoding="utf-8") as handle:
                handle.write(text)

    @classmethod
    def _lock_for_path(cls, path: Path) -> _PathAppendLock:
        resolved = path.resolve()
        with cls._append_locks_guard:
            path_lock = cls._append_locks.get(resolved)
            if path_lock is None:
                path_lock = cls._PathAppendLock()
                cls._append_locks[resolved] = path_lock
            return path_lock


def _strip_python_shebang(text: str) -> str:
    if text.startswith(_PYTHON_SHEBANG):
        return text[len(_PYTHON_SHEBANG) :]
    return text
