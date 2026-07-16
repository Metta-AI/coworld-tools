"""Tests for the mettagrid_replay_atlas reporter."""

from __future__ import annotations

import io
import json
import sys
import zipfile
from pathlib import Path

import pytest

pytest.importorskip("matplotlib")

import mettagrid_replay_atlas as atlas  # noqa: E402

SMOKE = Path(__file__).resolve().parent.parent / "smoke" / "make_bundle.py"


def _bundle_bytes(tmp_path: Path) -> Path:
    out = tmp_path / "bundle.zip"
    import runpy

    argv = sys.argv
    sys.argv = [str(SMOKE), str(out)]
    try:
        runpy.run_path(str(SMOKE), run_name="__main__")
    finally:
        sys.argv = argv
    return out


def _replay_and_results(bundle: Path) -> tuple[dict, dict]:
    with zipfile.ZipFile(bundle) as zf:
        return (
            json.loads(zf.read("replay.json")),
            json.loads(zf.read("results.json")),
        )


def test_build_zip_bytes_shape(tmp_path):
    replay, results = _replay_and_results(_bundle_bytes(tmp_path))
    payload = atlas.build_zip_bytes(results, replay, location_order="xy")
    with zipfile.ZipFile(io.BytesIO(payload)) as zf:
        names = set(zf.namelist())
        manifest = json.loads(zf.read("manifest.json"))
        html = zf.read("summary.html").decode("utf-8")
        events = zf.read("events.parquet")
    assert names == {
        "manifest.json",
        "summary.html",
        "events.parquet",
        "occupancy.png",
        "timeline.png",
    }
    assert manifest["reporter_id"] == atlas.REPORTER_ID
    assert manifest["render"] == "summary.html"
    assert manifest["event_log"] == "events.parquet"
    # Self-contained render with both charts embedded.
    assert html.count("data:image/png;base64,") == 2
    assert "alpha" in html and "beta" in html  # policy names in the table

    # The parquet is the canonical event log and carries the derived rows.
    from episode_analysis import EventLog

    log = EventLog.from_parquet(events)
    assert log.players == [0, 1]
    assert log.filter(key="death", player=1)[0].ts == 40
    assert len(log.positions(player=0)) > 10


def test_run_end_to_end_over_file_uris(tmp_path, monkeypatch):
    bundle = _bundle_bytes(tmp_path)
    report = tmp_path / "report.zip"
    monkeypatch.setenv("COGAME_EPISODE_BUNDLE_URI", bundle.resolve().as_uri())
    monkeypatch.setenv("COGAME_REPORT_URI", report.resolve().as_uri())
    from reporter_sdk import load_reporter_inputs

    atlas.run(load_reporter_inputs())
    assert report.exists()
    with zipfile.ZipFile(report) as zf:
        assert "summary.html" in zf.namelist()


def test_run_rejects_non_mettascope_replay(tmp_path, monkeypatch):
    bundle = tmp_path / "bad.zip"
    manifest = {
        "ereq_id": "e",
        "status": "success",
        "include": ["results", "replay"],
        "files": {"results": "results.json", "replay": "replay.json"},
    }
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("manifest.json", json.dumps(manifest))
        zf.writestr("results.json", json.dumps({"scores": []}))
        zf.writestr("replay.json", json.dumps({"not": "mettascope"}))
    bundle.write_bytes(buf.getvalue())
    monkeypatch.setenv("COGAME_EPISODE_BUNDLE_URI", bundle.resolve().as_uri())
    monkeypatch.setenv("COGAME_REPORT_URI", (tmp_path / "r.zip").resolve().as_uri())
    from reporter_sdk import load_reporter_inputs

    with pytest.raises(RuntimeError, match="MettaScope"):
        atlas.run(load_reporter_inputs())
