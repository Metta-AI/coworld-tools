"""PICO-8 palette and named perception constants.

Constants are ported from
``users/james/personal_cogs/among_them/guided_bot/perception/data.nim``.
The 16x3 RGB ``PALETTE`` is hand-transcribed from
``guided_bot/perception/baked/palette.bin`` (48 bytes = 16 RGB
triples). ``tests/test_baked_assets.py::test_palette_constant_matches_source_bin``
asserts byte-for-byte equality against that source blob; if the
upstream palette ever changes, that test fires and ``PALETTE`` here
must be hand-updated.

Per S1.4a decision (Option X), the palette ships as a Python constant
rather than a generated ``.npz`` artifact.
"""

from __future__ import annotations

import numpy as np

BAKE_SCHEMA_VERSION = 1

TRANSPARENT_INDEX = 255
SPRITE_SIZE = 12
SPRITE_DRAW_OFF_X = 2
SPRITE_DRAW_OFF_Y = 8

MAP_WIDTH = 952
MAP_HEIGHT = 534

TINT_COLOR = 3
SHADE_TINT_COLOR = 9
MAP_VOID_COLOR = 12
SPACE_COLOR = 0

FIRST_PRINTABLE_ASCII = 32
LAST_PRINTABLE_ASCII = 126
PRINTABLE_ASCII_COUNT = LAST_PRINTABLE_ASCII - FIRST_PRINTABLE_ASCII + 1
DEFAULT_GLYPH_SPACING = 1

PALETTE_COLOR_TABLE_SIZE = 16

PALETTE: np.ndarray = np.array(
    [
        (  0,   0,   0),
        (194, 195, 199),
        (255, 241, 232),
        (255,   0,  77),
        (255, 119, 168),
        ( 95,  87,  79),
        (171,  82,  54),
        (255, 163,   0),
        (255, 236,  39),
        (126,  37,  83),
        (  0, 135,  81),
        (  0, 228,  54),
        ( 29,  43,  83),
        (131, 118, 156),
        ( 41, 173, 255),
        (255, 204, 170),
    ],
    dtype=np.uint8,
)
PALETTE.flags.writeable = False
