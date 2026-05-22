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
    SPRITE_COUNT,
    SPRITE_SIZE,
    TRANSPARENT_INDEX,
    BakeManifestMismatch,
    load_sprite_atlas,
    load_sprite_index,
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


def test_generate_baked_no_handlers_produces_empty_artifact_list(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # When no handlers are registered, regenerating against the real
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


# --- sprite atlas (S1.4b) ---------------------------------------------------


_EXPECTED_SPRITE_NAMES = ("player", "body", "ghost", "task", "kill_button", "ghost_icon")


def test_sprite_atlas_shape_and_dtype() -> None:
    atlas = load_sprite_atlas()
    assert atlas.shape == (SPRITE_COUNT, SPRITE_SIZE, SPRITE_SIZE)
    assert atlas.dtype == np.uint8
    assert atlas.flags.writeable is False


def test_sprite_atlas_matches_source_bin() -> None:
    sprites_bin = (_UPSTREAM_BAKED_DIR / "sprites.bin").read_bytes()
    atlas = load_sprite_atlas()
    # The handler reshapes 864 bytes row-major into (6, 12, 12); the
    # raw bytes must round-trip back identically.
    assert atlas.tobytes() == sprites_bin


def test_sprite_atlas_load_is_cached() -> None:
    a1 = load_sprite_atlas()
    a2 = load_sprite_atlas()
    assert a1 is a2


def test_sprite_index_keys_and_values() -> None:
    index = load_sprite_index()
    assert set(index.keys()) == set(_EXPECTED_SPRITE_NAMES)
    assert sorted(index.values()) == list(range(SPRITE_COUNT))
    # Preserve the canonical Nim ordering: player=0, body=1, ghost=2,
    # task=3, kill_button=4, ghost_icon=5.
    for expected_idx, name in enumerate(_EXPECTED_SPRITE_NAMES):
        assert index[name] == expected_idx, (
            f"sprite '{name}' expected at atlas index {expected_idx}, got {index[name]}"
        )


def test_sprite_index_load_is_cached() -> None:
    i1 = load_sprite_index()
    i2 = load_sprite_index()
    assert i1 is i2


def test_sprite_atlas_in_checked_in_manifest() -> None:
    manifest = baked_manifest.load_manifest()
    names = {a["name"] for a in manifest["artifacts"]}
    assert "sprite_atlas.npz" in names
    entry = next(a for a in manifest["artifacts"] if a["name"] == "sprite_atlas.npz")
    assert entry["source"] == "sprites.bin"


def test_regenerate_produces_deterministic_sprite_atlas(tmp_path: Path) -> None:
    # Re-running the generator must produce byte-identical output so the
    # checked-in manifest digest is stable across machines/runs.
    out_manifest_1 = tmp_path / "m1.json"
    out_dir_1 = tmp_path / "d1"
    generate_baked.regenerate(
        source_dir=_UPSTREAM_BAKED_DIR,
        output_dir=out_dir_1,
        output_manifest=out_manifest_1,
    )
    out_manifest_2 = tmp_path / "m2.json"
    out_dir_2 = tmp_path / "d2"
    generate_baked.regenerate(
        source_dir=_UPSTREAM_BAKED_DIR,
        output_dir=out_dir_2,
        output_manifest=out_manifest_2,
    )
    a1 = (out_dir_1 / "sprite_atlas.npz").read_bytes()
    a2 = (out_dir_2 / "sprite_atlas.npz").read_bytes()
    assert hashlib.sha256(a1).hexdigest() == hashlib.sha256(a2).hexdigest()


def test_regenerate_matches_checked_in_manifest(tmp_path: Path) -> None:
    # Regenerating into a tmpdir must produce a manifest equal (modulo
    # ordering) to the checked-in one. Catches accidental drift between
    # source bytes and the recorded digests.
    out_manifest = tmp_path / "baked_manifest.json"
    fresh = generate_baked.regenerate(
        source_dir=_UPSTREAM_BAKED_DIR,
        output_dir=tmp_path,
        output_manifest=out_manifest,
    )
    checked_in = baked_manifest.load_manifest()
    assert fresh["source_manifest_sha256"] == checked_in["source_manifest_sha256"]
    fresh_by_name = {a["name"]: a for a in fresh["artifacts"]}
    checked_by_name = {a["name"]: a for a in checked_in["artifacts"]}
    assert fresh_by_name == checked_by_name
