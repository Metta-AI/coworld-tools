"""Tests for OutputManifest and build_report_zip.

Pins the validation contract — ``render`` must be an ``.md``/``.html`` zip
entry and ``event_log`` must be a ``.parquet`` zip entry — and verifies
that the in-zip ``manifest.json`` carries the declared fields, prepended
as the first entry in the output zip.
"""

from __future__ import annotations

import io
import json
import zipfile

import pytest

from reporter_sdk import (
    MTIME_SENTINEL,
    OutputManifest,
    build_report_zip,
)


def _entries(payload: bytes) -> dict[str, bytes]:
    with zipfile.ZipFile(io.BytesIO(payload)) as zf:
        return {info.filename: zf.read(info.filename) for info in zf.infolist()}


def _entry_order(payload: bytes) -> list[str]:
    with zipfile.ZipFile(io.BytesIO(payload)) as zf:
        return [info.filename for info in zf.infolist()]


# ---------- happy path ----------


def test_happy_path_both_set() -> None:
    manifest = OutputManifest(
        reporter_id="paint-arena-summarizer",
        render="summary.html",
        event_log="proximity.parquet",
    )
    payload = build_report_zip(
        manifest,
        [
            ("summary.html", b"<!DOCTYPE html>"),
            ("stats.json", b"{}"),
            ("proximity.parquet", b"PAR1"),
        ],
    )
    entries = _entries(payload)
    assert set(entries.keys()) == {
        "manifest.json",
        "summary.html",
        "stats.json",
        "proximity.parquet",
    }
    parsed = json.loads(entries["manifest.json"])
    assert parsed["reporter_id"] == "paint-arena-summarizer"
    assert parsed["render"] == "summary.html"
    assert parsed["event_log"] == "proximity.parquet"


def test_manifest_is_first_entry() -> None:
    """Downstream consumers rely on ``manifest.json`` being readable
    without scanning the whole zip; pinning it as the first entry keeps
    that cheap."""
    manifest = OutputManifest(reporter_id="x")
    payload = build_report_zip(manifest, [("a.txt", b"a"), ("b.txt", b"b")])
    assert _entry_order(payload)[0] == "manifest.json"


def test_manifest_json_uses_deterministic_mtime() -> None:
    manifest = OutputManifest(reporter_id="x")
    payload = build_report_zip(manifest, [("a.txt", b"a")])
    with zipfile.ZipFile(io.BytesIO(payload)) as zf:
        for info in zf.infolist():
            assert info.date_time == MTIME_SENTINEL


def test_render_optional() -> None:
    """A reporter that produces no renderable artifact omits the field."""
    manifest = OutputManifest(reporter_id="x", event_log="evt.parquet")
    payload = build_report_zip(manifest, [("evt.parquet", b"PAR1")])
    parsed = json.loads(_entries(payload)["manifest.json"])
    assert parsed["render"] is None
    assert parsed["event_log"] == "evt.parquet"


def test_event_log_optional() -> None:
    """A reporter that has no event log omits the field."""
    manifest = OutputManifest(reporter_id="x", render="summary.md")
    payload = build_report_zip(manifest, [("summary.md", b"# title")])
    parsed = json.loads(_entries(payload)["manifest.json"])
    assert parsed["render"] == "summary.md"
    assert parsed["event_log"] is None


# ---------- validation failures ----------


def test_render_must_exist_in_entries() -> None:
    manifest = OutputManifest(reporter_id="x", render="missing.html")
    with pytest.raises(ValueError, match="render"):
        build_report_zip(manifest, [("other.html", b"")])


def test_render_must_have_renderable_extension() -> None:
    manifest = OutputManifest(reporter_id="x", render="summary.txt")
    with pytest.raises(ValueError, match=r"render"):
        build_report_zip(manifest, [("summary.txt", b"")])


def test_event_log_must_exist_in_entries() -> None:
    manifest = OutputManifest(reporter_id="x", event_log="missing.parquet")
    with pytest.raises(ValueError, match="event_log"):
        build_report_zip(manifest, [("other.parquet", b"")])


def test_event_log_must_be_parquet_extension() -> None:
    manifest = OutputManifest(reporter_id="x", event_log="events.json")
    with pytest.raises(ValueError, match="event_log"):
        build_report_zip(manifest, [("events.json", b"")])


def test_byte_identical_on_rerun() -> None:
    manifest = OutputManifest(reporter_id="x", render="s.html", event_log="e.parquet")
    entries = [("s.html", b"<x/>"), ("e.parquet", b"PAR1")]
    assert build_report_zip(manifest, entries) == build_report_zip(manifest, entries)


def test_renderable_extensions_md_accepted() -> None:
    manifest = OutputManifest(reporter_id="x", render="summary.md")
    payload = build_report_zip(manifest, [("summary.md", b"# title")])
    assert "summary.md" in _entries(payload)
