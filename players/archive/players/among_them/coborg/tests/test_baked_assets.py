"""Tests for the baked perception assets (PLAN §5.4 / R3)."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pytest

from players.among_them.coborg.perception.data import (
    BAKE_SCHEMA_VERSION,
    DEFAULT_GLYPH_SPACING,
    FIRST_PRINTABLE_ASCII,
    MAP_HEIGHT,
    MAP_SHAPE,
    MAP_WIDTH,
    PALETTE,
    ATLAS_BODY,
    ATLAS_GHOST,
    ATLAS_GHOST_ICON,
    ATLAS_KILL_BUTTON,
    ATLAS_PLAYER,
    ATLAS_TASK,
    PALETTE_COLOR_TABLE_SIZE,
    PRINTABLE_ASCII_COUNT,
    SPRITE_COUNT,
    SPRITE_SIZE,
    TRANSPARENT_INDEX,
    BakeManifestMismatch,
    Font,
    load_font,
    load_map_pixels,
    load_sprite_atlas,
    load_sprite_index,
    load_walk_mask,
    load_wall_mask,
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


def test_atlas_named_constants_match_sprite_index() -> None:
    """The ``ATLAS_*`` constants in ``data.sprites`` are the named-access
    surface for the atlas. They must agree with the canonical
    ``sprite_index.json`` mapping, or callers using them will silently
    pick the wrong sprite. The same invariant is also enforced at import
    time by ``load_sprite_index`` itself; this test is the explicit
    failure point so a future spritesheet rotation can't go unnoticed."""
    index = load_sprite_index()
    assert index["player"] == ATLAS_PLAYER
    assert index["body"] == ATLAS_BODY
    assert index["ghost"] == ATLAS_GHOST
    assert index["task"] == ATLAS_TASK
    assert index["kill_button"] == ATLAS_KILL_BUTTON
    assert index["ghost_icon"] == ATLAS_GHOST_ICON


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


# --- map rasters (S1.4c) ----------------------------------------------------


_RASTER_LOADERS = [
    ("map_pixels.bin", "map_pixels.npz", load_map_pixels),
    ("walk_mask.bin", "walk_mask.npz", load_walk_mask),
    ("wall_mask.bin", "wall_mask.npz", load_wall_mask),
]


@pytest.mark.parametrize(("source_name", "npz_name", "loader"), _RASTER_LOADERS)
def test_raster_shape_and_dtype(source_name: str, npz_name: str, loader) -> None:
    arr = loader()
    assert arr.shape == MAP_SHAPE == (MAP_HEIGHT, MAP_WIDTH)
    assert arr.dtype == np.uint8
    assert arr.flags.writeable is False


@pytest.mark.parametrize(("source_name", "npz_name", "loader"), _RASTER_LOADERS)
def test_raster_matches_source_bin(source_name: str, npz_name: str, loader) -> None:
    raw = (_UPSTREAM_BAKED_DIR / source_name).read_bytes()
    arr = loader()
    # Row-major reshape must round-trip back to the source bytes exactly.
    assert arr.tobytes() == raw


@pytest.mark.parametrize(("source_name", "npz_name", "loader"), _RASTER_LOADERS)
def test_raster_load_is_cached(source_name: str, npz_name: str, loader) -> None:
    assert loader() is loader()


def test_walk_and_wall_masks_are_binary() -> None:
    walk = load_walk_mask()
    wall = load_wall_mask()
    assert set(np.unique(walk).tolist()) <= {0, 1}
    assert set(np.unique(wall).tolist()) <= {0, 1}


def test_map_pixels_uses_valid_palette_indices() -> None:
    pixels = load_map_pixels()
    # Source observation: map_pixels uses palette indices 1..15
    # (SPACE_COLOR / index 0 never appears in the level).
    assert int(pixels.min()) >= 1
    assert int(pixels.max()) <= PALETTE_COLOR_TABLE_SIZE - 1


@pytest.mark.parametrize(("source_name", "npz_name", "loader"), _RASTER_LOADERS)
def test_raster_in_checked_in_manifest(
    source_name: str, npz_name: str, loader
) -> None:
    manifest = baked_manifest.load_manifest()
    by_name = {a["name"]: a for a in manifest["artifacts"]}
    assert npz_name in by_name
    assert by_name[npz_name]["source"] == source_name


# --- font (S1.4d) -----------------------------------------------------------


def _decode_font_bin_header(blob: bytes) -> tuple[int, int, int]:
    height = blob[0]
    spacing = blob[1]
    count = blob[2] | (blob[3] << 8)
    return height, spacing, count


def test_font_header_matches_source_bin() -> None:
    blob = (_UPSTREAM_BAKED_DIR / "font.bin").read_bytes()
    height, spacing, count = _decode_font_bin_header(blob)
    font = load_font()
    assert font.height == height
    assert font.spacing == spacing == DEFAULT_GLYPH_SPACING
    assert count == PRINTABLE_ASCII_COUNT


def test_font_arrays_shape_and_dtype() -> None:
    font = load_font()
    assert font.widths.shape == (PRINTABLE_ASCII_COUNT,)
    assert font.widths.dtype == np.uint8
    assert font.widths.flags.writeable is False
    assert font.pixels.ndim == 3
    assert font.pixels.shape[0] == PRINTABLE_ASCII_COUNT
    assert font.pixels.shape[1] == font.height
    assert font.pixels.shape[2] == int(font.widths.max())
    assert font.pixels.dtype == np.uint8
    assert font.pixels.flags.writeable is False
    # 0/1 only.
    assert set(np.unique(font.pixels).tolist()) <= {0, 1}


def test_font_per_glyph_byte_parity() -> None:
    blob = (_UPSTREAM_BAKED_DIR / "font.bin").read_bytes()
    font = load_font()
    pos = 4
    for i in range(PRINTABLE_ASCII_COUNT):
        w = blob[pos]
        pos += 1
        expected_body = blob[pos : pos + font.height * w]
        pos += font.height * w
        assert int(font.widths[i]) == w, f"glyph {i} width mismatch"
        trimmed = font.pixels[i, :, :w]
        assert trimmed.tobytes() == expected_body, f"glyph {i} pixel mismatch"
    assert pos == len(blob), "trailing bytes in font.bin"


def test_font_round_trip_to_source_bin() -> None:
    # Reconstruct font.bin entirely from the npz and require byte-equality.
    blob = (_UPSTREAM_BAKED_DIR / "font.bin").read_bytes()
    font = load_font()
    parts: list[bytes] = [
        bytes([font.height, font.spacing]),
        bytes([PRINTABLE_ASCII_COUNT & 0xFF, (PRINTABLE_ASCII_COUNT >> 8) & 0xFF]),
    ]
    for i in range(PRINTABLE_ASCII_COUNT):
        w = int(font.widths[i])
        parts.append(bytes([w]))
        parts.append(font.pixels[i, :, :w].tobytes())
    rebuilt = b"".join(parts)
    assert rebuilt == blob


def test_font_glyph_accessor_returns_trimmed_pixels() -> None:
    font = load_font()
    # ' ' (space) is glyph 0; per upstream it's a blank 3-wide glyph.
    space = font.glyph(" ")
    assert space.shape == (font.height, 3)
    assert int(space.sum()) == 0
    # '!' is glyph 1, width 1.
    bang = font.glyph("!")
    assert bang.shape == (font.height, 1)
    assert int(bang.sum()) > 0


def test_font_glyph_rejects_out_of_range() -> None:
    font = load_font()
    with pytest.raises(ValueError, match="outside the printable-ASCII range"):
        font.glyph(chr(FIRST_PRINTABLE_ASCII - 1))
    with pytest.raises(ValueError, match="outside the printable-ASCII range"):
        font.glyph(chr(FIRST_PRINTABLE_ASCII + PRINTABLE_ASCII_COUNT))
    with pytest.raises(ValueError, match="1-char string"):
        font.glyph("ab")


def test_font_load_returns_same_instance() -> None:
    f1 = load_font()
    f2 = load_font()
    assert f1 is f2
    assert isinstance(f1, Font)


def test_font_in_checked_in_manifest() -> None:
    manifest = baked_manifest.load_manifest()
    by_name = {a["name"]: a for a in manifest["artifacts"]}
    assert "font.npz" in by_name
    assert by_name["font.npz"]["source"] == "font.bin"
