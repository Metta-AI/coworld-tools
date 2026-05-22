"""Baked perception assets ported from
``users/james/personal_cogs/among_them/guided_bot/perception/data.nim``
and the binary blobs under ``guided_bot/perception/baked/``.

Importing this package runs the digest invariant (PLAN R3) so any
drift between a checked-in ``.npz`` and the digests recorded in
``baked_manifest.json`` fails loudly at first use. The canonical
recovery is to re-run ``generate_baked.py``.
"""

from __future__ import annotations

from .baked_manifest import BakeManifestMismatch, verify_all
from .map import MAP_SHAPE, load_map_pixels, load_walk_mask, load_wall_mask
from .palette import (
    BAKE_SCHEMA_VERSION,
    DEFAULT_GLYPH_SPACING,
    FIRST_PRINTABLE_ASCII,
    LAST_PRINTABLE_ASCII,
    MAP_HEIGHT,
    MAP_VOID_COLOR,
    MAP_WIDTH,
    PALETTE,
    PALETTE_COLOR_TABLE_SIZE,
    PRINTABLE_ASCII_COUNT,
    SHADE_TINT_COLOR,
    SPACE_COLOR,
    SPRITE_DRAW_OFF_X,
    SPRITE_DRAW_OFF_Y,
    SPRITE_SIZE,
    TINT_COLOR,
    TRANSPARENT_INDEX,
)
from .sprites import SPRITE_COUNT, load_sprite_atlas, load_sprite_index

verify_all()

__all__ = [
    "BAKE_SCHEMA_VERSION",
    "BakeManifestMismatch",
    "DEFAULT_GLYPH_SPACING",
    "FIRST_PRINTABLE_ASCII",
    "LAST_PRINTABLE_ASCII",
    "MAP_HEIGHT",
    "MAP_SHAPE",
    "MAP_VOID_COLOR",
    "MAP_WIDTH",
    "PALETTE",
    "PALETTE_COLOR_TABLE_SIZE",
    "PRINTABLE_ASCII_COUNT",
    "SHADE_TINT_COLOR",
    "SPACE_COLOR",
    "SPRITE_COUNT",
    "SPRITE_DRAW_OFF_X",
    "SPRITE_DRAW_OFF_Y",
    "SPRITE_SIZE",
    "TINT_COLOR",
    "TRANSPARENT_INDEX",
    "load_map_pixels",
    "load_sprite_atlas",
    "load_sprite_index",
    "load_walk_mask",
    "load_wall_mask",
    "verify_all",
]
