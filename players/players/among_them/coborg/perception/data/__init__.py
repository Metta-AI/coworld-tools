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
from .font import Font, load_font
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
    PLAYER_BODY_LUT,
    PLAYER_COLORS,
    PRINTABLE_ASCII_COUNT,
    SHADE_TINT_COLOR,
    SHADOW_MAP,
    SPACE_COLOR,
    SPRITE_DRAW_OFF_X,
    SPRITE_DRAW_OFF_Y,
    SPRITE_SIZE,
    TINT_COLOR,
    TRANSPARENT_INDEX,
)
from .sprites import (
    ATLAS_BODY,
    ATLAS_GHOST,
    ATLAS_GHOST_ICON,
    ATLAS_KILL_BUTTON,
    ATLAS_PLAYER,
    ATLAS_TASK,
    SPRITE_COUNT,
    load_sprite_atlas,
    load_sprite_index,
)

verify_all()
# Trigger the ATLAS_* invariant check in load_sprite_index (asserts the
# JSON layout matches the named constants) at package import time, so a
# drift fails loudly before any module that uses ATLAS_* runs.
load_sprite_index()

__all__ = [
    "ATLAS_BODY",
    "ATLAS_GHOST",
    "ATLAS_GHOST_ICON",
    "ATLAS_KILL_BUTTON",
    "ATLAS_PLAYER",
    "ATLAS_TASK",
    "BAKE_SCHEMA_VERSION",
    "BakeManifestMismatch",
    "DEFAULT_GLYPH_SPACING",
    "FIRST_PRINTABLE_ASCII",
    "Font",
    "LAST_PRINTABLE_ASCII",
    "MAP_HEIGHT",
    "MAP_SHAPE",
    "MAP_VOID_COLOR",
    "MAP_WIDTH",
    "PALETTE",
    "PALETTE_COLOR_TABLE_SIZE",
    "PLAYER_BODY_LUT",
    "PLAYER_COLORS",
    "PRINTABLE_ASCII_COUNT",
    "SHADE_TINT_COLOR",
    "SHADOW_MAP",
    "SPACE_COLOR",
    "SPRITE_COUNT",
    "SPRITE_DRAW_OFF_X",
    "SPRITE_DRAW_OFF_Y",
    "SPRITE_SIZE",
    "TINT_COLOR",
    "TRANSPARENT_INDEX",
    "load_font",
    "load_map_pixels",
    "load_sprite_atlas",
    "load_sprite_index",
    "load_walk_mask",
    "load_wall_mask",
    "verify_all",
]
