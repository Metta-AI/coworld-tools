"""Tests for the baked perception assets (PLAN §5.4 / R3)."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pytest

from players.among_them.coborg.perception.data import (
    BAKE_SCHEMA_VERSION,
    MAP_HEIGHT,
    MAP_WIDTH,
    PALETTE,
    PALETTE_COLOR_TABLE_SIZE,
    SPRITE_SIZE,
    TRANSPARENT_INDEX,
    BakeManifestMismatch,
    verify_all,
)
from players.among_them.coborg.perception.data import baked_manifest, generate_baked

_REPO_ROOT = Path(__file__).resolve().parents[4]
_UPSTREAM_BAKED_DIR = (
    _REPO_ROOT
    / "users/james/personal_cogs/among_them/guided_bot/perception/baked"
)


def _load_upstream_manifest() -> dict:
    return json.loads((_UPSTREAM_BAKED_DIR / "manifest.json").read_text())


def test_palette_constant_matches_source_bin() -> None:
    palette_bin = (_UPSTREAM_BAKED_DIR / "palette.bin").read_bytes()
    assert PALETTE.tobytes() == palette_bin


def test_palette_metadata() -> None:
    assert PALETTE.shape == (PALETTE_COLOR_TABLE_SIZE, 3)
    assert PALETTE.dtype == np.uint8
    assert PALETTE.flags.writeable is False


def test_constants_match_upstream_manifest() -> None:
    src = _load_upstream_manifest()
    assert src["schema_version"] == BAKE_SCHEMA_VERSION
    assert src["map"]["width"] == MAP_WIDTH
    assert src["map"]["height"] == MAP_HEIGHT
    assert src["sprite"]["size"] == SPRITE_SIZE
    assert src["sprite"]["transparent_index"] == TRANSPARENT_INDEX


def test_verify_all_noop_on_empty_artifacts() -> None:
    # The checked-in baked_manifest.json starts with no artifacts; verify_all
    # must succeed against it. (It also runs at package import — see __init__.)
    verify_all()


def test_checked_in_manifest_records_source_digest() -> None:
    manifest = baked_manifest.load_manifest()
    assert manifest["schema_version"] == BAKE_SCHEMA_VERSION
    expected = hashlib.sha256(
        (_UPSTREAM_BAKED_DIR / "manifest.json").read_bytes()
    ).hexdigest()
    assert manifest["source_manifest_sha256"] == expected, (
        "checked-in baked_manifest.json source_manifest_sha256 is stale; "
        "re-run generate_baked.py to refresh"
    )


def test_verify_all_detects_digest_drift(tmp_path: Path) -> None:
    blob = tmp_path / "fake.npz"
    blob.write_bytes(b"actual contents")
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "schema_version": BAKE_SCHEMA_VERSION,
                "source_manifest_sha256": "0" * 64,
                "artifacts": [{"name": "fake.npz", "source": "x.bin", "sha256": "0" * 64}],
            }
        )
    )
    with pytest.raises(BakeManifestMismatch, match="digest drift"):
        verify_all(manifest_path=manifest, data_dir=tmp_path)


def test_verify_all_detects_missing_file(tmp_path: Path) -> None:
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "schema_version": BAKE_SCHEMA_VERSION,
                "source_manifest_sha256": "0" * 64,
                "artifacts": [{"name": "missing.npz", "source": "x.bin", "sha256": "0" * 64}],
            }
        )
    )
    with pytest.raises(BakeManifestMismatch, match="missing"):
        verify_all(manifest_path=manifest, data_dir=tmp_path)


def test_verify_source_digest_accepts_sha1_and_sha256() -> None:
    data = b"abc"
    sha1 = hashlib.sha1(data).hexdigest()
    sha256 = hashlib.sha256(data).hexdigest()
    generate_baked._verify_source_digest("x", data, sha1)
    generate_baked._verify_source_digest("x", data, sha256)
    with pytest.raises(RuntimeError, match="digest mismatch"):
        generate_baked._verify_source_digest("x", data, "0" * 40)
    with pytest.raises(RuntimeError, match="unsupported length"):
        generate_baked._verify_source_digest("x", data, "deadbeef")


def test_generate_baked_skeleton_produces_empty_artifact_list(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # No handlers are registered in S1.4a; regenerating against the real
    # upstream dir must succeed and emit a manifest with zero artifacts.
    monkeypatch.setattr(generate_baked, "HANDLERS", {})
    out_manifest = tmp_path / "baked_manifest.json"
    manifest = generate_baked.regenerate(
        source_dir=_UPSTREAM_BAKED_DIR,
        output_dir=tmp_path,
        output_manifest=out_manifest,
    )
    assert manifest["artifacts"] == []
    assert manifest["schema_version"] == BAKE_SCHEMA_VERSION
    on_disk = json.loads(out_manifest.read_text())
    assert on_disk == manifest
