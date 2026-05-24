"""Phase 6 tests: determinism + zip-contract assertions.

Phase 6 is the smallest-LOC phase by design — the reporter already uses
``write_deterministic_zip`` from phase 1, so the mtime pinning that makes
two runs byte-identical is in place. This file locks the contract in
with explicit, contract-named assertions:

- ``test_run_is_byte_identical_on_rerun`` — two end-to-end ``run()``
  invocations over identical inputs produce byte-identical zips. Mirrors
  PaintArena's same-named test (the contract is identical across
  reporters; what changes is the synthetic bundle that drives it).
- ``test_in_zip_manifest_render_extension_renderable`` — the in-zip
  ``manifest.json``'s ``render`` value points at an entry whose suffix is
  on the renderable allowlist (``.md`` / ``.html``) per the canonical
  reporter contract.
- ``test_in_zip_manifest_render_and_event_log_paths_resolve`` — both the
  ``render`` and ``event_log`` paths resolve to entries that actually
  exist in the zip; the ``event_log`` opens as a Parquet table.
- ``test_zip_entries_use_pinned_mtime`` — every ``ZipInfo.date_time``
  matches the SDK's ``MTIME_SENTINEL`` ``(1980, 1, 1, 0, 0, 0)``.
- ``test_events_parquet_metadata_stable_across_runs`` — within one
  pinned pyarrow version, two runs over the same inputs produce the same
  Parquet footer (same ``created_by``, same schema, same row count).
  This is the per-Parquet half of byte-identical determinism; the
  whole-zip check above subsumes it but a focused assertion makes the
  invariant easier to debug when it fails.

The SDK's ``build_report_zip`` already validates that ``render`` and
``event_log`` paths resolve to entries with the right shape on the
*write* side; these tests confirm the assertion still holds end-to-end
after the full reporter run.

There is overlap with a few phase-2 zip-shape tests (which check the
same invariants on the pure ``build_zip_bytes`` surface); this file
asserts the same contract through the end-to-end ``run()`` path so the
determinism + manifest-consistency commitment is exercised on the
write-to-URI side too.
"""

from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq

import among_them_summarizer as ats
import fixtures  # see conftest.py — tests/ is added to sys.path
from reporter_sdk import MTIME_SENTINEL


_RENDERABLE_EXTS = {".md", ".html"}
_EXPECTED_ENTRIES = {
    "manifest.json",
    "summary.html",
    "stats.json",
    "events.parquet",
}


def _run_against_bundle(tmp_path: Path) -> Path:
    """Pack a synthetic bundle and invoke ``ats.run`` against it.

    Returns the path of the written output zip. Each call writes to a
    fresh ``report.zip`` inside ``tmp_path``; callers that want to
    compare two runs should pass distinct ``tmp_path`` subdirs.
    """
    tmp_path.mkdir(parents=True, exist_ok=True)
    bundle_path = tmp_path / "bundle.zip"
    bundle_path.write_bytes(fixtures.make_bundle_zip())
    output_path = tmp_path / "report.zip"
    ats.run(
        ats.ReporterInputs(
            episode_bundle_uri=bundle_path.as_uri(),
            report_uri=output_path.as_uri(),
        )
    )
    return output_path


def _open(payload: bytes) -> zipfile.ZipFile:
    return zipfile.ZipFile(io.BytesIO(payload))


def _manifest(payload: bytes) -> dict[str, Any]:
    with _open(payload) as zf:
        return json.loads(zf.read("manifest.json"))


# ---------- determinism ----------


def test_run_is_byte_identical_on_rerun(tmp_path: Path) -> None:
    """Two ``run()`` invocations over identical inputs produce
    byte-identical output zips. The invariant holds within one pinned
    pyarrow version (the ``requirements.txt`` pin); SDK
    ``write_deterministic_zip`` pins the zip-entry mtimes."""
    first = _run_against_bundle(tmp_path / "a").read_bytes()
    second = _run_against_bundle(tmp_path / "b").read_bytes()
    assert first == second


def test_events_parquet_metadata_stable_across_runs(tmp_path: Path) -> None:
    """Two runs over the same inputs produce Parquet files whose footer
    metadata agrees: same ``created_by`` writer string, same schema, same
    row count. The whole-zip byte-equality test subsumes this; a focused
    assertion on the Parquet metadata makes it easier to diagnose if
    determinism regresses on the Parquet side specifically (e.g. an
    unpinned pyarrow version or a row-order change in
    ``build_event_rows``)."""

    def _parquet_meta(payload: bytes) -> tuple[str, list[str], int]:
        with _open(payload) as zf:
            parquet_blob = zf.read("events.parquet")
        meta = pq.read_metadata(io.BytesIO(parquet_blob))
        schema_names = list(meta.schema.to_arrow_schema().names)
        return (meta.created_by or "", schema_names, meta.num_rows)

    first = _run_against_bundle(tmp_path / "a").read_bytes()
    second = _run_against_bundle(tmp_path / "b").read_bytes()
    assert _parquet_meta(first) == _parquet_meta(second)


# ---------- in-zip manifest.json contract ----------


def test_in_zip_manifest_render_extension_renderable(tmp_path: Path) -> None:
    """The ``render`` value's suffix is in the canonical contract's
    renderable allowlist (``.md`` / ``.html``)."""
    payload = _run_against_bundle(tmp_path).read_bytes()
    manifest = _manifest(payload)
    assert Path(manifest["render"]).suffix.lower() in _RENDERABLE_EXTS


def test_in_zip_manifest_render_and_event_log_paths_resolve(
    tmp_path: Path,
) -> None:
    """Both ``render`` and ``event_log`` point at entries that exist in
    the zip; the ``event_log`` opens as a Parquet table."""
    payload = _run_against_bundle(tmp_path).read_bytes()
    with _open(payload) as zf:
        manifest = json.loads(zf.read("manifest.json"))
        names = set(zf.namelist())
        # Sanity-check the event_log opens as a Parquet table.
        pq.read_table(io.BytesIO(zf.read(manifest["event_log"])))
    assert manifest["render"] in names
    assert manifest["event_log"] in names
    # The full expected entry set is also present (catches drift).
    assert names == _EXPECTED_ENTRIES


# ---------- pinned mtime ----------


def test_zip_entries_use_pinned_mtime(tmp_path: Path) -> None:
    """Every entry's ``ZipInfo.date_time`` matches the SDK's
    ``MTIME_SENTINEL``. This is the invariant that makes byte-identical
    reruns work — without it, ``zipfile.ZipInfo.date_time`` defaults to
    ``time.localtime()`` and drifts on every write."""
    payload = _run_against_bundle(tmp_path).read_bytes()
    with _open(payload) as zf:
        for info in zf.infolist():
            assert info.date_time == MTIME_SENTINEL, (
                f"{info.filename} has date_time {info.date_time}, "
                f"expected {MTIME_SENTINEL}"
            )
