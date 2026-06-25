"""Tests for the Eurydice trace analyzer skeleton."""

from __future__ import annotations

import json

from scripts.analyze_eurydice_traces import analyze_trace_path


def test_trace_event_names_are_known(tmp_path) -> None:
    trace = tmp_path / "bot.jsonl"
    trace.write_text(
        "\n".join(
            [
                json.dumps({"type": "meta_decide_reason", "tick": 1}),
                json.dumps({"type": "whisper_fsm_transition", "tick": 2}),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    summary = analyze_trace_path(tmp_path)

    assert summary.files_scanned == 1
    assert summary.events_total == 2
    assert summary.unknown_event_types == []
    assert summary.event_counts["meta_decide_reason"] == 1
    assert summary.event_counts["whisper_fsm_transition"] == 1
    assert summary.first_tick == 1
    assert summary.last_tick == 2


def test_trace_analyzer_handles_empty_run(tmp_path) -> None:
    summary = analyze_trace_path(tmp_path)

    assert summary.files_scanned == 0
    assert summary.events_total == 0
    assert summary.malformed_lines == 0
    assert summary.event_counts == {}
    assert summary.unknown_event_types == []
    assert summary.first_tick is None
    assert summary.last_tick is None


def test_trace_analyzer_handles_prefixed_jsonl(tmp_path) -> None:
    trace = tmp_path / "runner.log"
    trace.write_text(
        '[bot_0] {"type":"mode_transition","tick":5}\n',
        encoding="utf-8",
    )

    summary = analyze_trace_path(trace)

    assert summary.files_scanned == 1
    assert summary.events_total == 1
    assert summary.event_counts["mode_transition"] == 1
    assert summary.unknown_event_types == []
