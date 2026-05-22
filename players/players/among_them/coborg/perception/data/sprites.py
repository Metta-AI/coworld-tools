"""Reference sprite atlas loaders.

The six reference sprites are sliced from the upstream
``among_them/spritesheet.aseprite`` (columns ``[0, 1, 6, 4, 3, 7]``) and
packed into ``sprites.bin`` as 864 bytes = 6 × 12 × 12 palette-indexed
pixels. ``sprite_atlas.npz`` is the NumPy mirror with shape
``(6, SPRITE_SIZE, SPRITE_SIZE)`` uint8.

Sprite names and order are ported from the ``Sprites*`` object in
``users/james/personal_cogs/among_them/guided_bot/perception/data.nim``
(``player, body, ghost, task, killButton, ghostIcon``) and exposed
through ``sprite_index.json`` in snake_case.

Loaders are lazy + cached: the atlas is only read on first call, and
the returned arrays are immutable so callers can hand them to kernels
without defensive copies.
"""

from __future__ import annotations

import functools
import json
from pathlib import Path

import numpy as np

from .palette import SPRITE_SIZE

_DATA_DIR = Path(__file__).resolve().parent
_ATLAS_PATH = _DATA_DIR / "sprite_atlas.npz"
_INDEX_PATH = _DATA_DIR / "sprite_index.json"

SPRITE_COUNT = 6


@functools.lru_cache(maxsize=1)
def load_sprite_atlas() -> np.ndarray:
    """Return the immutable ``(6, 12, 12) uint8`` sprite atlas."""
    with np.load(_ATLAS_PATH) as bundle:
        arr = bundle["sprite_atlas"].copy()
    if arr.shape != (SPRITE_COUNT, SPRITE_SIZE, SPRITE_SIZE):
        raise RuntimeError(
            f"sprite_atlas.npz has wrong shape {arr.shape}; "
            f"expected ({SPRITE_COUNT}, {SPRITE_SIZE}, {SPRITE_SIZE})"
        )
    if arr.dtype != np.uint8:
        raise RuntimeError(f"sprite_atlas.npz has wrong dtype {arr.dtype}; expected uint8")
    arr.flags.writeable = False
    return arr


@functools.lru_cache(maxsize=1)
def load_sprite_index() -> dict[str, int]:
    """Return the snake_case sprite-name -> atlas-index mapping."""
    raw = json.loads(_INDEX_PATH.read_text())
    if not isinstance(raw, dict):
        raise RuntimeError("sprite_index.json must be a JSON object")
    index = {str(k): int(v) for k, v in raw.items()}
    if len(index) != SPRITE_COUNT:
        raise RuntimeError(
            f"sprite_index.json has {len(index)} entries; expected {SPRITE_COUNT}"
        )
    if sorted(index.values()) != list(range(SPRITE_COUNT)):
        raise RuntimeError(
            f"sprite_index.json values must be 0..{SPRITE_COUNT - 1} with no duplicates; "
            f"got {sorted(index.values())}"
        )
    return index
