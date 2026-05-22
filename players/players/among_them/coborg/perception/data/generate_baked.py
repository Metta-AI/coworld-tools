"""One-shot converter from upstream ``baked/*.bin`` blobs to ``.npz``.

This script reads
``users/james/personal_cogs/among_them/guided_bot/perception/baked/`` (the
Coworld-cleanup-frozen artifacts produced by the now-deleted Nim bake tool)
and rewrites each blob into a NumPy ``.npz`` file alongside this module,
then refreshes ``baked_manifest.json`` with sha256 digests of every output.

S1.4a registers no handlers; later sub-commits in the S1.4 stack add
sprites/map/font handlers via :func:`register`.

Upstream digest quirk (PLAN §5.4 finding, 2026-05-22): the upstream
``manifest.json`` records 40-char hex digests under a field misnamed
``"sha256"`` — they are actually **sha1**. We detect the algorithm from
digest length so the source-drift check works correctly without
back-editing the frozen upstream artifact.

Usage:
    uv run python -m players.among_them.coborg.perception.data.generate_baked
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import sys
from pathlib import Path
from typing import Callable

import numpy as np

from .palette import BAKE_SCHEMA_VERSION, SPRITE_SIZE
from .sprites import SPRITE_COUNT

_DATA_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _DATA_DIR.parents[4]
_DEFAULT_SOURCE_DIR = (
    _REPO_ROOT
    / "users/james/personal_cogs/among_them/guided_bot/perception/baked"
)
_OUTPUT_MANIFEST = _DATA_DIR / "baked_manifest.json"

# filename (e.g. "sprites.bin") -> handler(source_bytes) -> dict for np.savez
Handler = Callable[[bytes], dict[str, np.ndarray]]
HANDLERS: dict[str, tuple[str, Handler]] = {}


def register(source_filename: str, output_filename: str) -> Callable[[Handler], Handler]:
    """Register a handler that converts ``source_filename`` to ``output_filename``."""

    def decorator(fn: Handler) -> Handler:
        HANDLERS[source_filename] = (output_filename, fn)
        return fn

    return decorator


@register("sprites.bin", "sprite_atlas.npz")
def _convert_sprites(data: bytes) -> dict[str, np.ndarray]:
    """Reshape sprites.bin (864 bytes) into a (6, 12, 12) uint8 atlas."""
    expected = SPRITE_COUNT * SPRITE_SIZE * SPRITE_SIZE
    if len(data) != expected:
        raise RuntimeError(
            f"sprites.bin has {len(data)} bytes; expected {expected} "
            f"({SPRITE_COUNT} sprites x {SPRITE_SIZE}x{SPRITE_SIZE} palette-indexed)"
        )
    atlas = np.frombuffer(data, dtype=np.uint8).reshape(
        SPRITE_COUNT, SPRITE_SIZE, SPRITE_SIZE
    )
    return {"sprite_atlas": atlas}


def _hex_digest(data: bytes, algo: str) -> str:
    return hashlib.new(algo, data).hexdigest()


def _verify_source_digest(name: str, data: bytes, expected_hex: str) -> None:
    """Verify ``data`` against ``expected_hex``, picking algo by digest length.

    Upstream's ``"sha256"`` field is actually sha1 (40 hex chars); a proper
    64-char sha256 is also accepted in case upstream ever fixes the misnomer.
    """
    expected = expected_hex.lower()
    if len(expected) == 40:
        algo = "sha1"
    elif len(expected) == 64:
        algo = "sha256"
    else:
        raise RuntimeError(
            f"upstream digest for {name} has unsupported length "
            f"{len(expected)} (expected 40=sha1 or 64=sha256)"
        )
    actual = _hex_digest(data, algo)
    if actual != expected:
        raise RuntimeError(
            f"upstream blob {name} digest mismatch ({algo}):\n"
            f"  expected: {expected}\n  actual:   {actual}"
        )


def _npz_bytes(arrays: dict[str, np.ndarray]) -> bytes:
    buf = io.BytesIO()
    np.savez(buf, **arrays)
    return buf.getvalue()


def regenerate(
    source_dir: Path = _DEFAULT_SOURCE_DIR,
    output_dir: Path = _DATA_DIR,
    output_manifest: Path = _OUTPUT_MANIFEST,
) -> dict:
    """Regenerate every registered baked artifact and rewrite the manifest."""
    src_manifest_path = source_dir / "manifest.json"
    src_manifest_bytes = src_manifest_path.read_bytes()
    src_manifest = json.loads(src_manifest_bytes)

    if src_manifest.get("schema_version") != BAKE_SCHEMA_VERSION:
        raise RuntimeError(
            "upstream baked manifest schema_version "
            f"{src_manifest.get('schema_version')!r} != "
            f"expected {BAKE_SCHEMA_VERSION}; review generator before regenerating"
        )

    output_dir.mkdir(parents=True, exist_ok=True)
    output_manifest.parent.mkdir(parents=True, exist_ok=True)

    source_index = {entry["name"]: entry for entry in src_manifest["files"]}
    artifacts: list[dict] = []

    for source_name, (output_name, handler) in sorted(HANDLERS.items()):
        if source_name not in source_index:
            raise RuntimeError(
                f"handler registered for {source_name} but file not in upstream manifest"
            )
        source_bytes = (source_dir / source_name).read_bytes()
        _verify_source_digest(source_name, source_bytes, source_index[source_name]["sha256"])
        arrays = handler(source_bytes)
        payload = _npz_bytes(arrays)
        (output_dir / output_name).write_bytes(payload)
        artifacts.append(
            {
                "name": output_name,
                "source": source_name,
                "sha256": hashlib.sha256(payload).hexdigest(),
            }
        )

    manifest = {
        "schema_version": BAKE_SCHEMA_VERSION,
        "source_manifest_sha256": hashlib.sha256(src_manifest_bytes).hexdigest(),
        "artifacts": artifacts,
    }
    output_manifest.write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", type=Path, default=_DEFAULT_SOURCE_DIR)
    parser.add_argument("--output-dir", type=Path, default=_DATA_DIR)
    parser.add_argument("--output-manifest", type=Path, default=_OUTPUT_MANIFEST)
    args = parser.parse_args(argv)
    manifest = regenerate(args.source_dir, args.output_dir, args.output_manifest)
    print(f"wrote {len(manifest['artifacts'])} artifact(s) to {args.output_dir}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
