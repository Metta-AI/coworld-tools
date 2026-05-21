"""Skeleton-level tests: env-var loading at the I/O contract boundary.

These tests are scoped to the contract surface that does not depend on
the reporter's output shape (which evolves phase-by-phase). The
output-shape tests live in test_phase2.py and later.
"""

from __future__ import annotations

import json
from pathlib import Path

import among_them_summarizer as ats


def test_reporter_inputs_load_from_env(monkeypatch, tmp_path: Path) -> None:
    """load_reporter_inputs() reads the documented COGAME_* env vars."""
    results_path = tmp_path / "results.json"
    metadata_path = tmp_path / "metadata.json"
    replay_path = tmp_path / "replay.bitreplay"
    output_path = tmp_path / "report.zip"
    results_path.write_text(json.dumps({}))
    metadata_path.write_text(json.dumps({}))
    replay_path.write_bytes(b"")
    monkeypatch.setenv("COGAME_RESULTS_URI", results_path.as_uri())
    monkeypatch.setenv("COGAME_REPLAY_URI", replay_path.as_uri())
    monkeypatch.setenv("COGAME_EPISODE_METADATA_URI", metadata_path.as_uri())
    monkeypatch.setenv("COGAME_REPORT_OUTPUT_URI", output_path.as_uri())
    monkeypatch.setenv("COGAME_REPORTER_ID", "among-them-summarizer")
    loaded = ats.load_reporter_inputs()
    assert loaded.results_uri == results_path.as_uri()
    assert loaded.replay_uri == replay_path.as_uri()
    assert loaded.episode_metadata_uri == metadata_path.as_uri()
    assert loaded.report_output_uri == output_path.as_uri()
    assert loaded.reporter_id == "among-them-summarizer"
