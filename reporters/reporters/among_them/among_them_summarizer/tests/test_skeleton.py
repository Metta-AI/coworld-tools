"""Skeleton-level tests: env-var loading at the I/O contract boundary.

These tests are scoped to the contract surface that does not depend on
the reporter's output shape (which evolves phase-by-phase). The
output-shape tests live in test_phase2.py and later.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import among_them_summarizer as ats


def test_reporter_inputs_load_from_env(monkeypatch, tmp_path: Path) -> None:
    """load_reporter_inputs() reads the canonical COGAME_* env vars."""
    bundle_path = tmp_path / "bundle.zip"
    output_path = tmp_path / "report.zip"
    bundle_path.write_bytes(b"")  # not opened by load_reporter_inputs
    monkeypatch.setenv("COGAME_EPISODE_BUNDLE_URI", bundle_path.as_uri())
    monkeypatch.setenv("COGAME_REPORT_URI", output_path.as_uri())
    loaded = ats.load_reporter_inputs()
    assert loaded.episode_bundle_uri == bundle_path.as_uri()
    assert loaded.report_uri == output_path.as_uri()


def test_load_reporter_inputs_missing_env_var_raises(monkeypatch) -> None:
    for k in ("COGAME_EPISODE_BUNDLE_URI", "COGAME_REPORT_URI"):
        monkeypatch.delenv(k, raising=False)
    with pytest.raises(KeyError):
        ats.load_reporter_inputs()
