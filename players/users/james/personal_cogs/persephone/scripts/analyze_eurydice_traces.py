#!/usr/bin/env python3
"""Summarize Eurydice/Orpheus JSONL trace output.

This is intentionally small for Phase 0: it validates that trace files are
parseable, counts event types, and reports unknown event names. Later phases
should extend this script with behavioral metrics rather than creating a
separate trace scanner.
"""

from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import asdict, dataclass, field
import json
from pathlib import Path
import sys
from typing import Any


KNOWN_EVENT_TYPES: frozenset[str] = frozenset(
    {
        "act_command",
        "action_memory_mutation",
        "belief_diff",
        "cooldown_change",
        "cover_blown",
        "deception_decision",
        "evaluator_branch",
        "grid_change",
        "hook_failure",
        "info_screen_reconcile_scheduled",
        "info_screen_reconciled",
        "inference_fired",
        "invalid_mode_directive",
        "invalid_mode_switch_override",
        "lie_recorded",
        "llm_context",
        "llm_decision",
        "llm_decision_accepted",
        "llm_decision_rejected",
        "llm_directive_ignored",
        "llm_directive_selected",
        "meta_decide_bad_return",
        "meta_decide_input",
        "meta_decide_output",
        "meta_decide_reason",
        "minimap_sighting",
        "mode_enter",
        "mode_switch_cleanup",
        "mode_transition",
        "outer_loop_cycle",
        "outer_loop_restart",
        "perception",
        "entry_granted",
        "entry_requested",
        "probe_attempt_started",
        "probe_completed",
        "probe_failed",
        "probe_target_selected",
        "whisper_created",
        "whisper_offer_state",
        "whisper_system_message_observed",
        "raw",
        "select_task",
        "strategic_state_change",
        "strategic_state_snapshot",
        "task_change",
        "valid_views_mismatch",
        "view_transition",
        "watchdog_activation",
        "whisper_exchange_outcome",
        "whisper_exit",
        "whisper_fsm_transition",
        "whisper_protocol_selected",
    }
)


@dataclass
class TraceSummary:
    """Machine-readable summary for one trace tree."""

    files_scanned: int = 0
    events_total: int = 0
    malformed_lines: int = 0
    event_counts: dict[str, int] = field(default_factory=dict)
    unknown_event_types: list[str] = field(default_factory=list)
    first_tick: int | None = None
    last_tick: int | None = None


def analyze_trace_path(path: Path) -> TraceSummary:
    """Analyze one file or directory of JSONL traces."""

    files = list(_trace_files(path))
    event_counts: Counter[str] = Counter()
    malformed_lines = 0
    first_tick: int | None = None
    last_tick: int | None = None

    for file_path in files:
        with file_path.open("r", encoding="utf-8") as handle:
            for line in handle:
                entry = _parse_jsonl_line(line)
                if entry is None:
                    if line.strip():
                        malformed_lines += 1
                    continue

                event_type = entry.get("type")
                if isinstance(event_type, str):
                    event_counts[event_type] += 1

                tick = entry.get("tick")
                if isinstance(tick, int):
                    first_tick = tick if first_tick is None else min(first_tick, tick)
                    last_tick = tick if last_tick is None else max(last_tick, tick)

    unknown = sorted(
        event_type
        for event_type in event_counts
        if event_type not in KNOWN_EVENT_TYPES
    )
    return TraceSummary(
        files_scanned=len(files),
        events_total=sum(event_counts.values()),
        malformed_lines=malformed_lines,
        event_counts=dict(sorted(event_counts.items())),
        unknown_event_types=unknown,
        first_tick=first_tick,
        last_tick=last_tick,
    )


def _trace_files(path: Path):
    if path.is_file():
        if _looks_like_trace_file(path):
            yield path
        return

    if not path.exists():
        return

    for file_path in sorted(path.rglob("*")):
        if file_path.is_file() and _looks_like_trace_file(file_path):
            yield file_path


def _looks_like_trace_file(path: Path) -> bool:
    return path.suffix in {".jsonl", ".log", ".txt"}


def _parse_jsonl_line(line: str) -> dict[str, Any] | None:
    stripped = line.strip()
    if not stripped:
        return None

    start = stripped.find("{")
    if start < 0:
        return None

    try:
        parsed = json.loads(stripped[start:])
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", type=Path, help="Trace file or directory")
    parser.add_argument("--json", action="store_true", help="Emit JSON summary")
    args = parser.parse_args(argv)

    summary = analyze_trace_path(args.path)
    payload = asdict(summary)
    if args.json:
        print(json.dumps(payload, sort_keys=True))
    else:
        print(f"files_scanned: {summary.files_scanned}")
        print(f"events_total: {summary.events_total}")
        print(f"malformed_lines: {summary.malformed_lines}")
        print(f"first_tick: {summary.first_tick}")
        print(f"last_tick: {summary.last_tick}")
        if summary.unknown_event_types:
            print("unknown_event_types: " + ", ".join(summary.unknown_event_types))
        else:
            print("unknown_event_types: none")
        for event_type, count in summary.event_counts.items():
            print(f"{event_type}: {count}")

    return 1 if summary.unknown_event_types or summary.malformed_lines else 0


if __name__ == "__main__":
    sys.exit(main())
