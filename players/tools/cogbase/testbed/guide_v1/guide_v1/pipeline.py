from __future__ import annotations

import logging
from collections.abc import Sequence, Set
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from .documents import DocumentSpec, all_documents, documents_by_stage
from .contracts import write_guide_contract
from .framework import AgentFrameworkRef, build_agent_framework_ref
from .prompts import build_runner_prompt, build_synthesizer_prompt
from .runners import run_claude, run_codex
from .synthesizer import run_synthesizer


LOGGER = logging.getLogger(__name__)

RunnerName = Literal["claude", "codex"]
DEFAULT_RUNNERS: tuple[RunnerName, ...] = ("claude", "codex")
_RUNNER_ALIASES: dict[str, RunnerName] = {
    "claude": "claude",
    "clod": "claude",
    "codex": "codex",
    "codec": "codex",
}


@dataclass(frozen=True, slots=True)
class PipelineResult:
    completed: frozenset[str]
    failed: frozenset[str]
    skipped: frozenset[str]

    @property
    def ok(self) -> bool:
        return not self.failed and not self.skipped


def run_pipeline(
    source: Path,
    *,
    output_dir: Path = Path("./output"),
    only: Sequence[str] | None = None,
    through_stage: int | None = None,
    claude_model: str | None = None,
    codex_model: str | None = None,
    agent_framework: AgentFrameworkRef | None = None,
    runners: Sequence[str] | None = None,
    dry_run: bool = False,
    skip_existing: bool = False,
    max_parallel: int = 4,
) -> PipelineResult:
    game_source = source.expanduser().resolve()
    output_path = output_dir.expanduser().resolve()
    framework_ref = agent_framework or build_agent_framework_ref()
    runner_names = normalize_runner_names(runners)
    selected_documents = _select_documents(only=only, through_stage=through_stage)
    selected_names = {document.name for document in selected_documents}

    if dry_run:
        _log_plan(
            game_source=game_source,
            output_dir=output_path,
            agent_framework=framework_ref,
            runners=runner_names,
            selected_documents=selected_documents,
            skip_existing=skip_existing,
        )
        return PipelineResult(frozenset(), frozenset(), frozenset())

    output_path.mkdir(parents=True, exist_ok=True)
    (output_path / ".drafts").mkdir(parents=True, exist_ok=True)

    completed = _initial_completed_documents(
        output_dir=output_path,
        selected_names=selected_names,
        skip_existing=skip_existing,
    )
    failed: set[str] = set()
    skipped: set[str] = set()

    if not selected_documents:
        LOGGER.warning("No guide documents selected")
        return PipelineResult(frozenset(), frozenset(), frozenset())

    for stage, stage_documents in documents_by_stage(selected_documents).items():
        LOGGER.info("Starting stage %s (%s document%s)", stage, len(stage_documents), "" if len(stage_documents) == 1 else "s")

        ready_documents = []
        for document in stage_documents:
            output_file = output_path / document.filename
            if skip_existing and output_file.exists():
                completed.add(document.name)
                LOGGER.info("Skipping %s: output already exists at %s", document.name, output_file)
                continue

            skip_reason = _dependency_skip_reason(
                document,
                completed_documents=completed,
                failed_documents=failed,
                skipped_documents=skipped,
            )
            if skip_reason is not None:
                skipped.add(document.name)
                LOGGER.warning("Skipping %s: %s", document.name, skip_reason)
                continue

            ready_documents.append(document)

        if not ready_documents:
            continue

        completed_snapshot = frozenset(completed)
        worker_count = min(max_parallel, len(ready_documents))
        with ThreadPoolExecutor(max_workers=worker_count) as executor:
            futures = {
                executor.submit(
                    _generate_with_retry,
                    document,
                    game_source=game_source,
                    output_dir=output_path,
                    agent_framework=framework_ref,
                    runners=runner_names,
                    completed_documents=completed_snapshot,
                    claude_model=claude_model,
                    codex_model=codex_model,
                ): document
                for document in ready_documents
            }

            for future in as_completed(futures):
                document = futures[future]
                try:
                    future.result()
                except Exception as exc:
                    failed.add(document.name)
                    LOGGER.error("Failed %s after retry: %s", document.name, exc)
                else:
                    completed.add(document.name)
                    LOGGER.info("Completed %s -> %s", document.name, output_path / document.filename)

    LOGGER.info(
        "Guide generation complete: %s completed, %s skipped, %s failed",
        len(completed & selected_names),
        len(skipped),
        len(failed),
    )
    if completed:
        contract_file = write_guide_contract(
            output_path,
            game_source=game_source,
            agent_framework=framework_ref,
        )
        LOGGER.info("Wrote guide contract -> %s", contract_file)
    return PipelineResult(frozenset(completed), frozenset(failed), frozenset(skipped))


def normalize_runner_names(values: Sequence[str] | None) -> tuple[RunnerName, ...]:
    if not values:
        return DEFAULT_RUNNERS

    normalized: list[RunnerName] = []
    unknown: list[str] = []
    for value in values:
        for part in value.split(","):
            key = part.strip().lower()
            if not key:
                continue
            runner = _RUNNER_ALIASES.get(key)
            if runner is None:
                unknown.append(part.strip())
                continue
            if runner not in normalized:
                normalized.append(runner)

    if unknown:
        allowed = ", ".join(sorted(_RUNNER_ALIASES))
        raise ValueError(f"unknown runner(s): {', '.join(unknown)}. Available: {allowed}")
    if not normalized:
        raise ValueError("at least one runner must be selected")
    return tuple(normalized)


def _select_documents(
    *,
    only: Sequence[str] | None,
    through_stage: int | None,
) -> list[DocumentSpec]:
    allowed_slugs = {slug.lower() for slug in only} if only else None
    selected = []
    for document in all_documents():
        if allowed_slugs is not None and document.slug not in allowed_slugs:
            continue
        if through_stage is not None and document.stage > through_stage:
            continue
        selected.append(document)
    return selected


def _initial_completed_documents(
    *,
    output_dir: Path,
    selected_names: Set[str],
    skip_existing: bool,
) -> set[str]:
    completed = set()
    for document in all_documents():
        if not (output_dir / document.filename).exists():
            continue
        if skip_existing or document.name not in selected_names:
            completed.add(document.name)
    return completed


def _dependency_skip_reason(
    document: DocumentSpec,
    *,
    completed_documents: Set[str],
    failed_documents: Set[str],
    skipped_documents: Set[str],
) -> str | None:
    for dependency in document.dependencies:
        if dependency in completed_documents:
            continue
        if dependency in failed_documents:
            return f"dependency {dependency} failed"
        if dependency in skipped_documents:
            return f"dependency {dependency} was skipped"
        return f"dependency {dependency} not available (not in output dir and not generated this run)"
    return None


def _generate_with_retry(
    document: DocumentSpec,
    *,
    game_source: Path,
    output_dir: Path,
    agent_framework: AgentFrameworkRef,
    runners: Sequence[RunnerName],
    completed_documents: Set[str],
    claude_model: str | None,
    codex_model: str | None,
) -> None:
    last_error: Exception | None = None
    for attempt in range(1, 3):
        try:
            _generate_document(
                document,
                game_source=game_source,
                output_dir=output_dir,
                agent_framework=agent_framework,
                runners=runners,
                completed_documents=completed_documents,
                claude_model=claude_model,
                codex_model=codex_model,
            )
            return
        except Exception as exc:
            last_error = exc
            if attempt == 1:
                LOGGER.warning("Retrying %s after failure: %s", document.name, exc)

    if last_error is None:
        raise RuntimeError(f"Unknown failure while generating {document.name}")
    raise last_error


def _generate_document(
    document: DocumentSpec,
    *,
    game_source: Path,
    output_dir: Path,
    agent_framework: AgentFrameworkRef,
    runners: Sequence[RunnerName],
    completed_documents: Set[str],
    claude_model: str | None,
    codex_model: str | None,
) -> None:
    draft_dir = output_dir / ".drafts" / document.name
    draft_dir.mkdir(parents=True, exist_ok=True)

    claude_draft = draft_dir / "claude_draft.md"
    codex_draft = draft_dir / "codex_draft.md"
    final_output = output_dir / document.filename

    for path in (claude_draft, codex_draft, final_output):
        path.unlink(missing_ok=True)

    generated_drafts: list[tuple[RunnerName, Path]] = []
    for runner in runners:
        if runner == "claude":
            LOGGER.info("Generating %s Claude draft", document.name)
            claude_prompt = build_runner_prompt(
                document,
                game_source_path=game_source,
                agent_framework=agent_framework,
                output_dir=output_dir,
                output_file=claude_draft,
                completed_documents=completed_documents,
            )
            claude_stdout = run_claude(
                claude_prompt,
                game_source=game_source,
                output_dir=output_dir,
                agent_framework=agent_framework,
                model=claude_model,
            )
            _ensure_file_content(claude_draft, fallback_content=claude_stdout, label="Claude draft")
            generated_drafts.append((runner, claude_draft))
            continue

        if runner == "codex":
            LOGGER.info("Generating %s Codex draft", document.name)
            codex_prompt = build_runner_prompt(
                document,
                game_source_path=game_source,
                agent_framework=agent_framework,
                output_dir=output_dir,
                output_file=codex_draft,
                completed_documents=completed_documents,
            )
            codex_output = run_codex(
                codex_prompt,
                game_source=game_source,
                output_dir=output_dir,
                agent_framework=agent_framework,
                draft_output_file=codex_draft,
                model=codex_model,
            )
            _ensure_file_content(codex_draft, fallback_content=codex_output, label="Codex draft")
            generated_drafts.append((runner, codex_draft))
            continue

        raise AssertionError(f"Unhandled runner: {runner}")

    if len(generated_drafts) == 1:
        runner, draft_path = generated_drafts[0]
        LOGGER.info(
            "Skipping synthesis for %s: only %s runner selected",
            document.name,
            _runner_display_name(runner),
        )
        content = _ensure_file_content(
            draft_path,
            fallback_content="",
            label=f"{_runner_display_name(runner)} draft",
        )
        final_output.write_text(content, encoding="utf-8")
        return

    LOGGER.info("Synthesizing %s", document.name)
    synthesizer_prompt = build_synthesizer_prompt(
        document,
        game_source_path=game_source,
        agent_framework=agent_framework,
        output_dir=output_dir,
        output_file=final_output,
        draft_a=generated_drafts[0][1],
        draft_b=generated_drafts[1][1],
        completed_documents=completed_documents,
    )
    synthesizer_stdout = run_synthesizer(
        synthesizer_prompt,
        game_source=game_source,
        output_dir=output_dir,
        agent_framework=agent_framework,
        output_file=final_output,
        model=claude_model,
    )
    _ensure_file_content(final_output, fallback_content=synthesizer_stdout, label="synthesized document")


def _runner_display_name(runner: RunnerName) -> str:
    return {"claude": "Claude", "codex": "Codex"}[runner]


def _ensure_file_content(path: Path, *, fallback_content: str, label: str) -> str:
    if path.exists():
        content = path.read_text(encoding="utf-8")
        if content.strip():
            return content

    if fallback_content.strip():
        path.write_text(fallback_content, encoding="utf-8")
        return fallback_content

    raise RuntimeError(f"{label} was not written: {path}")


def _log_plan(
    *,
    game_source: Path,
    output_dir: Path,
    agent_framework: AgentFrameworkRef,
    runners: Sequence[RunnerName],
    selected_documents: Sequence[DocumentSpec],
    skip_existing: bool,
) -> None:
    LOGGER.info("Guide generation plan")
    LOGGER.info("Source: %s", game_source)
    LOGGER.info("Output directory: %s", output_dir)
    LOGGER.info("Agent framework: %s (%s)", agent_framework.framework_dir, agent_framework.package)
    LOGGER.info(
        "Runners: %s%s",
        ", ".join(_runner_display_name(runner) for runner in runners),
        " (synthesis disabled)" if len(runners) == 1 else " (synthesis enabled)",
    )
    LOGGER.info("Skip existing: %s", "yes" if skip_existing else "no")

    if not selected_documents:
        LOGGER.warning("No guide documents selected")
        return

    for stage, stage_documents in documents_by_stage(selected_documents).items():
        LOGGER.info("Stage %s", stage)
        for document in stage_documents:
            dependencies = ", ".join(document.dependencies) if document.dependencies else "none"
            existing = " [exists]" if (output_dir / document.filename).exists() else ""
            LOGGER.info(
                "  %s (%s) -> %s; dependencies: %s%s",
                document.name,
                document.slug,
                output_dir / document.filename,
                dependencies,
                existing,
            )
