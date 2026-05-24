"""Contract tests for the summarizer template.

The template is scaffolding that game-specific reporters copy and
customize; it is intentionally game-agnostic and produces stub
artifacts (a placeholder ``summary.md``, no event log). These tests
lock the *contract* — that the template runs against a synthetic
in-memory bundle and emits an output zip whose ``manifest.json``
satisfies the canonical Coworld reporter contract enforced by
:func:`reporter_sdk.build_report_zip`. They are deliberately thin:
the whole point of the template is to be specialized, so tests that
pin specific copy or layout would just become drag.
"""

from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

import pytest
from reporter_sdk import OutputManifest, ReporterInputs

import summarizer as tpl


_PINNED_MTIME = (1980, 1, 1, 0, 0, 0)


def _make_bundle_bytes() -> bytes:
    """Hand-build a minimal episode bundle zip per ``EPISODE_BUNDLE_README.md``.

    The template doesn't actually consume any bundle tokens, but it does
    open the bundle and inspect its inner manifest, so the fixture has
    to be a real, parseable bundle zip.
    """
    inner_manifest = {
        "ereq_id": "ereq_template_smoke_0001",
        "status": "success",
        "include": ["results"],
        "files": {"results": "results.json"},
    }
    results = {"scores": [0.5, 0.5]}
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("manifest.json", json.dumps(inner_manifest))
        zf.writestr("results.json", json.dumps(results))
    return buf.getvalue()


@pytest.fixture
def bundle_uri(tmp_path: Path) -> str:
    bundle_path = tmp_path / "bundle.zip"
    bundle_path.write_bytes(_make_bundle_bytes())
    return bundle_path.as_uri()


@pytest.fixture
def report_uri(tmp_path: Path) -> str:
    return (tmp_path / "report.zip").as_uri()


def test_run_writes_report_zip(bundle_uri: str, report_uri: str) -> None:
    """End-to-end: the template runs against a synthetic bundle and writes
    an output zip to ``COGAME_REPORT_URI``."""
    tpl.run(ReporterInputs(episode_bundle_uri=bundle_uri, report_uri=report_uri))

    out_path = Path(report_uri.removeprefix("file://"))
    assert out_path.exists(), "template did not write the output zip"
    with zipfile.ZipFile(out_path) as zf:
        names = set(zf.namelist())
    assert "manifest.json" in names
    assert "summary.md" in names


def test_output_manifest_is_valid(bundle_uri: str, report_uri: str) -> None:
    """The in-zip ``manifest.json`` parses as :class:`OutputManifest`,
    flags ``summary.md`` as ``render``, and declares no ``event_log``."""
    tpl.run(ReporterInputs(episode_bundle_uri=bundle_uri, report_uri=report_uri))

    out_path = Path(report_uri.removeprefix("file://"))
    with zipfile.ZipFile(out_path) as zf:
        raw = zf.read("manifest.json")
    manifest = OutputManifest.model_validate_json(raw)
    assert manifest.reporter_id == tpl.REPORTER_ID
    assert manifest.render == "summary.md"
    assert manifest.event_log is None


def test_render_target_points_at_existing_entry(
    bundle_uri: str, report_uri: str
) -> None:
    """``manifest.render`` must resolve to an actual zip entry — the same
    invariant ``build_report_zip`` enforces at construction time."""
    tpl.run(ReporterInputs(episode_bundle_uri=bundle_uri, report_uri=report_uri))

    out_path = Path(report_uri.removeprefix("file://"))
    with zipfile.ZipFile(out_path) as zf:
        manifest = json.loads(zf.read("manifest.json"))
        render = manifest["render"]
        assert render in zf.namelist()
        # And the render target is non-empty.
        assert len(zf.read(render)) > 0


def test_output_zip_uses_pinned_mtimes(bundle_uri: str, report_uri: str) -> None:
    """The SDK's deterministic-zip writer pins ``date_time`` on every entry
    so reruns over identical inputs are byte-identical. Templates inherit
    this for free; assert it so a future refactor that bypasses the SDK's
    writer would fail loudly."""
    tpl.run(ReporterInputs(episode_bundle_uri=bundle_uri, report_uri=report_uri))

    out_path = Path(report_uri.removeprefix("file://"))
    with zipfile.ZipFile(out_path) as zf:
        for info in zf.infolist():
            assert info.date_time == _PINNED_MTIME, (
                f"{info.filename} has date_time {info.date_time}, expected pinned {_PINNED_MTIME}"
            )
