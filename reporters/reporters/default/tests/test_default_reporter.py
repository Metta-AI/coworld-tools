"""Tests for the Softmax default reporter.

The default reporter exists to satisfy ``min_length=1`` on
``manifest.reporter[]`` for Coworlds that have not shipped a
game-specific reporter. It is explicitly placeholder, and its primary
contract obligation is *never to crash* — these tests pin both the
shape of the output zip (manifest.json, summary.md, no event log) and
the defensive paths that handle missing/malformed/absent
``results.json`` data.
"""

from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

import pytest
from reporter_sdk import OutputManifest, ReporterInputs

import default_reporter as dr


_PINNED_MTIME = (1980, 1, 1, 0, 0, 0)


def _make_bundle_bytes(
    *,
    ereq_id: str = "ereq_default_test_0001",
    status: str = "success",
    include: list[str] | None = None,
    files: dict[str, str] | None = None,
    entries: list[tuple[str, bytes]] | None = None,
) -> bytes:
    """Hand-build a minimal episode bundle zip per ``EPISODE_BUNDLE_README.md``.

    Defaults: a three-slot ``results.json`` declared via ``include`` and
    ``files``. Callers override to exercise the defensive paths (missing
    ``results`` token, malformed ``results.json``, ``status="failed"``,
    etc.).
    """
    if include is None:
        include = ["results"]
    if files is None:
        files = {"results": "results.json"}
    if entries is None:
        entries = [
            (
                "results.json",
                json.dumps({"scores": [1.0, 2.5, 0.0]}).encode("utf-8"),
            )
        ]
    manifest = {
        "ereq_id": ereq_id,
        "status": status,
        "include": include,
        "files": files,
    }
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("manifest.json", json.dumps(manifest))
        for name, payload in entries:
            zf.writestr(name, payload)
    return buf.getvalue()


@pytest.fixture
def report_uri(tmp_path: Path) -> str:
    return (tmp_path / "report.zip").as_uri()


def _bundle_uri(tmp_path: Path, payload: bytes) -> str:
    p = tmp_path / "bundle.zip"
    p.write_bytes(payload)
    return p.as_uri()


def _read_report(report_uri: str) -> tuple[set[str], dict, str]:
    """Open the report zip at ``report_uri`` and return
    ``(entry_names, parsed_manifest, summary_md)``."""
    out_path = Path(report_uri.removeprefix("file://"))
    with zipfile.ZipFile(out_path) as zf:
        names = set(zf.namelist())
        manifest = json.loads(zf.read("manifest.json"))
        summary = zf.read("summary.md").decode("utf-8")
    return names, manifest, summary


def test_run_writes_report_zip(tmp_path: Path, report_uri: str) -> None:
    """End-to-end: the reporter runs against a synthetic bundle and writes
    a non-empty zip to ``COGAME_REPORT_URI``."""
    bundle_uri = _bundle_uri(tmp_path, _make_bundle_bytes())
    dr.run(ReporterInputs(episode_bundle_uri=bundle_uri, report_uri=report_uri))

    out_path = Path(report_uri.removeprefix("file://"))
    assert out_path.exists(), "default reporter did not write the output zip"
    names, _manifest, _summary = _read_report(report_uri)
    assert "manifest.json" in names
    assert "summary.md" in names


def test_output_manifest_shape(tmp_path: Path, report_uri: str) -> None:
    """The in-zip ``manifest.json`` declares ``reporter_id`` =
    ``"softmax/default-reporter"``, ``render="summary.md"``, and no
    ``event_log``. Pinned for the Coworld manifest -> default reporter
    contract: any change here is observable to downstream consumers."""
    bundle_uri = _bundle_uri(tmp_path, _make_bundle_bytes())
    dr.run(ReporterInputs(episode_bundle_uri=bundle_uri, report_uri=report_uri))

    _names, raw_manifest, _summary = _read_report(report_uri)
    manifest = OutputManifest.model_validate(raw_manifest)
    assert manifest.reporter_id == "softmax/default-reporter"
    assert manifest.render == "summary.md"
    assert manifest.event_log is None


def test_summary_lists_one_line_per_slot(tmp_path: Path, report_uri: str) -> None:
    """For a three-slot bundle, ``summary.md`` includes one line per
    slot with that slot's score."""
    bundle_uri = _bundle_uri(tmp_path, _make_bundle_bytes())
    dr.run(ReporterInputs(episode_bundle_uri=bundle_uri, report_uri=report_uri))

    _names, _manifest, summary = _read_report(report_uri)
    assert "Slot 0 scored 1.0" in summary
    assert "Slot 1 scored 2.5" in summary
    assert "Slot 2 scored 0.0" in summary
    # And the summary advertises the reporter id so a reader can tell
    # which image produced it.
    assert "softmax/default-reporter" in summary


def test_summary_handles_missing_results_token(
    tmp_path: Path, report_uri: str
) -> None:
    """A bundle whose ``manifest.include`` omits ``results`` produces a
    valid output zip — ``summary.md`` records that no scores were
    available rather than crashing."""
    bundle_uri = _bundle_uri(
        tmp_path,
        _make_bundle_bytes(include=[], files={}, entries=[]),
    )
    dr.run(ReporterInputs(episode_bundle_uri=bundle_uri, report_uri=report_uri))

    _names, manifest, summary = _read_report(report_uri)
    assert manifest["reporter_id"] == "softmax/default-reporter"
    assert "No scores were available" in summary


def test_summary_handles_results_missing_scores_field(
    tmp_path: Path, report_uri: str
) -> None:
    """``results.json`` exists but does not include a ``scores`` field —
    the reporter still produces a valid report and notes the missing
    data in the summary."""
    bundle_uri = _bundle_uri(
        tmp_path,
        _make_bundle_bytes(
            entries=[
                (
                    "results.json",
                    json.dumps({"other_field": "value"}).encode("utf-8"),
                )
            ],
        ),
    )
    dr.run(ReporterInputs(episode_bundle_uri=bundle_uri, report_uri=report_uri))

    _names, _manifest, summary = _read_report(report_uri)
    assert "No scores were available" in summary


def test_summary_handles_empty_scores_list(
    tmp_path: Path, report_uri: str
) -> None:
    """``results.scores`` is an empty list (zero-player episode) — the
    reporter notes that explicitly instead of emitting a per-slot
    section with zero rows."""
    bundle_uri = _bundle_uri(
        tmp_path,
        _make_bundle_bytes(
            entries=[
                (
                    "results.json",
                    json.dumps({"scores": []}).encode("utf-8"),
                )
            ],
        ),
    )
    dr.run(ReporterInputs(episode_bundle_uri=bundle_uri, report_uri=report_uri))

    _names, _manifest, summary = _read_report(report_uri)
    assert "empty `scores` list" in summary


def test_summary_handles_unparseable_results_json(
    tmp_path: Path, report_uri: str
) -> None:
    """``results.json`` is in ``manifest.include`` but contains malformed
    JSON. The reporter logs a warning and still writes a valid zip."""
    bundle_uri = _bundle_uri(
        tmp_path,
        _make_bundle_bytes(
            entries=[("results.json", b"not json {")],
        ),
    )
    dr.run(ReporterInputs(episode_bundle_uri=bundle_uri, report_uri=report_uri))

    _names, manifest, summary = _read_report(report_uri)
    assert manifest["reporter_id"] == "softmax/default-reporter"
    assert "No scores were available" in summary


def test_summary_handles_failed_bundle_status(
    tmp_path: Path, report_uri: str
) -> None:
    """A bundle whose inner manifest reports ``status="failed"`` (no
    results.json typically present) — the reporter still produces a
    summary, surfaces the failure status, and does not crash."""
    bundle_uri = _bundle_uri(
        tmp_path,
        _make_bundle_bytes(
            status="failed",
            include=[],
            files={},
            entries=[],
        ),
    )
    dr.run(ReporterInputs(episode_bundle_uri=bundle_uri, report_uri=report_uri))

    _names, manifest, summary = _read_report(report_uri)
    assert manifest["reporter_id"] == "softmax/default-reporter"
    assert "`failed`" in summary
    assert "No scores were available" in summary


def test_summary_handles_non_numeric_score(
    tmp_path: Path, report_uri: str
) -> None:
    """Score entries that are not numeric (e.g. ``None``, a string,
    booleans) format gracefully rather than crashing the report build."""
    bundle_uri = _bundle_uri(
        tmp_path,
        _make_bundle_bytes(
            entries=[
                (
                    "results.json",
                    json.dumps({"scores": [None, "n/a", True, 7]}).encode("utf-8"),
                )
            ],
        ),
    )
    dr.run(ReporterInputs(episode_bundle_uri=bundle_uri, report_uri=report_uri))

    _names, _manifest, summary = _read_report(report_uri)
    assert "Slot 0 scored missing" in summary
    assert "Slot 1 scored 'n/a'" in summary
    assert "Slot 2 scored True" in summary
    assert "Slot 3 scored 7" in summary


def test_output_zip_uses_pinned_mtimes(
    tmp_path: Path, report_uri: str
) -> None:
    """The SDK's deterministic-zip writer pins ``date_time`` on every
    entry so reruns over identical inputs are byte-identical. Assert it
    so a future refactor that bypasses the SDK's writer fails loudly."""
    bundle_uri = _bundle_uri(tmp_path, _make_bundle_bytes())
    dr.run(ReporterInputs(episode_bundle_uri=bundle_uri, report_uri=report_uri))

    out_path = Path(report_uri.removeprefix("file://"))
    with zipfile.ZipFile(out_path) as zf:
        for info in zf.infolist():
            assert info.date_time == _PINNED_MTIME, (
                f"{info.filename} has date_time {info.date_time}, "
                f"expected pinned {_PINNED_MTIME}"
            )


def test_run_is_byte_identical_on_rerun(
    tmp_path: Path, report_uri: str
) -> None:
    """The default reporter is a pure function of the bundle — two runs
    over the same inputs produce byte-identical zips. Enables caching."""
    bundle_uri = _bundle_uri(tmp_path, _make_bundle_bytes())

    out_a = (tmp_path / "report_a.zip").as_uri()
    out_b = (tmp_path / "report_b.zip").as_uri()
    dr.run(ReporterInputs(episode_bundle_uri=bundle_uri, report_uri=out_a))
    dr.run(ReporterInputs(episode_bundle_uri=bundle_uri, report_uri=out_b))

    bytes_a = Path(out_a.removeprefix("file://")).read_bytes()
    bytes_b = Path(out_b.removeprefix("file://")).read_bytes()
    assert bytes_a == bytes_b


def test_reporter_id_constant() -> None:
    """The exported ``REPORTER_ID`` matches the value referenced in
    Coworld manifests. Pinned because the C3 cogs_vs_clips manifest
    update relies on this exact string."""
    assert dr.REPORTER_ID == "softmax/default-reporter"
