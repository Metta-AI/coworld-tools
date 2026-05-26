"""Baked map raster loaders.

Three 952x534 uint8 rasters are baked from the upstream Aseprite map:

- ``map_pixels.bin`` (508368 B): palette-indexed background, values 1-15
  (palette index 0 / SPACE_COLOR is absent from the level)
- ``walk_mask.bin`` (508368 B): 0/1 per-pixel walkability for actor
  movement; mirrors Nim's ``WalkMaskBlob`` (passability via ``!= 0``)
- ``wall_mask.bin`` (508368 B): 0/1 per-pixel wall predicate; mirrors
  Nim's ``WallMaskBlob``

All three are stored as ``(MAP_HEIGHT, MAP_WIDTH) uint8`` so callers
can do row-major ``(y, x)`` indexing, matching the Nim ``y * MapWidth + x``
convention. Loaders are lazy + cached; the returned arrays are
immutable.
"""

from __future__ import annotations

import functools
from pathlib import Path

import numpy as np

from .palette import MAP_HEIGHT, MAP_WIDTH

_DATA_DIR = Path(__file__).resolve().parent
_MAP_PIXELS_PATH = _DATA_DIR / "map_pixels.npz"
_WALK_MASK_PATH = _DATA_DIR / "walk_mask.npz"
_WALL_MASK_PATH = _DATA_DIR / "wall_mask.npz"

MAP_SHAPE = (MAP_HEIGHT, MAP_WIDTH)


# --- Skeld map metadata (mirrors upstream baked/map.json) ----------------

# Emergency-button bounding box (world coordinates). Used by localize to
# seed the cold-start spiral search and the post-interstitial reseed.
# Values pinned to upstream
# `users/.../guided_bot/perception/baked/map.json::button`.
BUTTON_X = 524
BUTTON_Y = 114
BUTTON_W = 28
BUTTON_H = 34

# Initial home position (world coordinates). Belief layer reseeds the
# camera here after interstitials when no lock has been established yet.
# Mirrors `map.json::home`. Used by localize.reseed_camera_at_home only
# when `home_set` is False on the first reseed; subsequent reseeds use
# the locked-in self position.
HOME_X = 536
HOME_Y = 120


def _load_raster(path: Path, key: str) -> np.ndarray:
    with np.load(path) as bundle:
        arr = bundle[key].copy()
    if arr.shape != MAP_SHAPE:
        raise RuntimeError(
            f"{path.name} has wrong shape {arr.shape}; expected {MAP_SHAPE}"
        )
    if arr.dtype != np.uint8:
        raise RuntimeError(
            f"{path.name} has wrong dtype {arr.dtype}; expected uint8"
        )
    arr.flags.writeable = False
    return arr


@functools.lru_cache(maxsize=1)
def load_map_pixels() -> np.ndarray:
    """Return the immutable ``(534, 952) uint8`` palette-indexed map."""
    return _load_raster(_MAP_PIXELS_PATH, "map_pixels")


@functools.lru_cache(maxsize=1)
def load_walk_mask() -> np.ndarray:
    """Return the immutable ``(534, 952) uint8`` walkability mask (0/1)."""
    return _load_raster(_WALK_MASK_PATH, "walk_mask")


@functools.lru_cache(maxsize=1)
def load_wall_mask() -> np.ndarray:
    """Return the immutable ``(534, 952) uint8`` wall mask (0/1)."""
    return _load_raster(_WALL_MASK_PATH, "wall_mask")
