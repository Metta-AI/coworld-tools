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


# --- player-color slot mapping --------------------------------------------

# Player color slots -> lit palette index. Must match ``sim.nim``'s
# ``PlayerColors`` and ``common/perception_kernels/sprite_match.nim``'s
# ``PlayerColors``. The 16 slots cover every PICO-8 palette entry exactly
# once (a permutation), which has implications for
# ``perception.sprite_match.actor_color_index_all``.
PLAYER_COLORS: np.ndarray = np.array(
    [3, 7, 8, 14, 4, 11, 13, 15, 1, 2, 5, 6, 9, 10, 12, 0], dtype=np.uint8
)
PLAYER_COLORS.flags.writeable = False

# Palette index -> shadowed variant. Mirrors ``sim.nim``'s ``ShadowMap``.
SHADOW_MAP: np.ndarray = np.array(
    [0, 12, 9, 5, 5, 0, 5, 5, 5, 12, 9, 9, 0, 12, 12, 9], dtype=np.uint8
)
SHADOW_MAP.flags.writeable = False


def _build_player_body_lut() -> np.ndarray:
    """256-entry bool LUT: index ``c`` is True iff ``c`` is a plausible
    player-body palette index (lit color OR its shadowed variant).
    Mirrors ``isPlayerBodyColor`` in the upstream Nim kernel."""
    lut = np.zeros(256, dtype=bool)
    for pc in PLAYER_COLORS:
        lut[int(pc)] = True
        lut[int(SHADOW_MAP[int(pc) & 0x0F])] = True
    return lut


PLAYER_BODY_LUT: np.ndarray = _build_player_body_lut()
PLAYER_BODY_LUT.flags.writeable = False
