"""Phase 1 skeleton tests for among_them_summarizer.

Phase 1 is the I/O-contract round-trip: load env URIs, ignore input
content, write a deterministic zip whose only entry is an empty
`render.txt`. These tests assert the zip is well-formed per
REPORTER_DESIGN.md D12 (readable zip; if `render.txt` is present, every
listed path must exist and have a renderable extension), pins the
deterministic mtime that D12's byte-identical-rerun clause requires,
and verifies the reporter exits 0 on the happy path.

Later phases extend the reporter to include `summary.html`,
`stats.json`, `events.parquet`; the assertions here are scoped to the
current `{render.txt}`-only output and will be replaced once those
phases land.
"""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

import among_them_summarizer as ats

_PINNED_MTIME = (1980, 1, 1, 0, 0, 0)


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


def _write_bytes(path: Path, payload: bytes) -> None:
    path.write_bytes(payload)


def _stub_inputs(tmp_path: Path) -> ats.ReporterInputs:
    """Build a ReporterInputs pointing at tmp-path file:// URIs.

    Phase 1 does not read input bytes, so the stubs only need to exist
    (the path resolution in read_uri does not touch them). Later phases
    will replace these stubs with format-conformant fixtures.
    """
    results_path = tmp_path / "results.json"
    metadata_path = tmp_path / "metadata.json"
    replay_path = tmp_path / "replay.bitreplay"
    output_path = tmp_path / "report.zip"
    _write_json(results_path, {"scores": [0]})
    _write_json(metadata_path, {"variant_id": "default"})
    _write_bytes(replay_path, b"")
    return ats.ReporterInputs(
        results_uri=results_path.as_uri(),
        replay_uri=replay_path.as_uri(),
        episode_metadata_uri=metadata_path.as_uri(),
        report_output_uri=output_path.as_uri(),
        reporter_id="among-them-summarizer",
    )


def test_run_writes_zip_with_only_render_txt(tmp_path: Path) -> None:
    inputs = _stub_inputs(tmp_path)
    ats.run(inputs)

    output_path = tmp_path / "report.zip"
    assert output_path.exists()
    with zipfile.ZipFile(output_path) as zf:
        names = zf.namelist()
        assert names == ["render.txt"], names
        assert zf.read("render.txt") == b""


def test_zip_entry_mtime_is_pinned(tmp_path: Path) -> None:
    inputs = _stub_inputs(tmp_path)
    ats.run(inputs)
    with zipfile.ZipFile(tmp_path / "report.zip") as zf:
        for info in zf.infolist():
            assert info.date_time == _PINNED_MTIME, (info.filename, info.date_time)


def test_run_is_byte_identical_on_rerun(tmp_path: Path) -> None:
    """Two invocations over identical inputs produce byte-identical zips."""
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    inputs_a = _stub_inputs(tmp_path / "a")
    inputs_b = _stub_inputs(tmp_path / "b")
    ats.run(inputs_a)
    ats.run(inputs_b)
    assert (tmp_path / "a" / "report.zip").read_bytes() == (
        tmp_path / "b" / "report.zip"
    ).read_bytes()


def test_reporter_inputs_load_from_env(monkeypatch, tmp_path: Path) -> None:
    """load_reporter_inputs() reads the documented COGAME_* env vars."""
    results_path = tmp_path / "results.json"
    metadata_path = tmp_path / "metadata.json"
    replay_path = tmp_path / "replay.bitreplay"
    output_path = tmp_path / "report.zip"
    _write_json(results_path, {})
    _write_json(metadata_path, {})
    _write_bytes(replay_path, b"")
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
