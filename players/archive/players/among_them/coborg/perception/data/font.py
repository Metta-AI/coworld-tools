"""Baked tiny5 pixel font loader.

The upstream ``font.bin`` encodes the variable-width tiny5 glyph set
used by Coworld text rendering. Format (little-endian, matches
``loadFont`` in ``guided_bot/perception/data.nim``):

    u8 height
    u8 spacing
    u16 glyph_count
    for each glyph: u8 width, height*width bytes (0/1 row-major)

``count`` must equal ``PRINTABLE_ASCII_COUNT`` (95); glyph ``i``
corresponds to ASCII ``FIRST_PRINTABLE_ASCII + i`` (i.e. ``chr(32 + i)``).

The .npz packs the variable-width glyphs into a fixed
``(count, height, max_width)`` zero-padded uint8 array plus a
``(count,) uint8`` widths array. Callers retrieve a glyph as
``pixels[i, :, :widths[i]]``.
"""

from __future__ import annotations

import functools
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .palette import (
    DEFAULT_GLYPH_SPACING,
    FIRST_PRINTABLE_ASCII,
    PRINTABLE_ASCII_COUNT,
)

_DATA_DIR = Path(__file__).resolve().parent
_FONT_PATH = _DATA_DIR / "font.npz"


@dataclass(frozen=True)
class Font:
    """Decoded variable-width font.

    Attributes:
        height: row count for every glyph.
        spacing: horizontal padding inserted between rendered glyphs.
        widths: ``(95,) uint8`` per-glyph column count, immutable.
        pixels: ``(95, height, max_width) uint8`` zero-padded glyph
            pixels (0 = off, 1 = on), immutable. Access glyph ``i``
            with ``pixels[i, :, :widths[i]]``.
    """

    height: int
    spacing: int
    widths: np.ndarray
    pixels: np.ndarray

    def glyph(self, ch: str) -> np.ndarray:
        """Return the trimmed ``(height, width)`` pixels for ASCII ``ch``."""
        if len(ch) != 1:
            raise ValueError(f"glyph(ch) expects a 1-char string, got {ch!r}")
        idx = ord(ch) - FIRST_PRINTABLE_ASCII
        if not 0 <= idx < PRINTABLE_ASCII_COUNT:
            raise ValueError(
                f"{ch!r} (ord {ord(ch)}) is outside the printable-ASCII range "
                f"[{FIRST_PRINTABLE_ASCII}, {FIRST_PRINTABLE_ASCII + PRINTABLE_ASCII_COUNT - 1}]"
            )
        width = int(self.widths[idx])
        return self.pixels[idx, :, :width]


@functools.lru_cache(maxsize=1)
def load_font() -> Font:
    """Return the immutable tiny5 :class:`Font` decoded from ``font.npz``."""
    with np.load(_FONT_PATH) as bundle:
        height = int(bundle["font_height"])
        spacing = int(bundle["font_spacing"])
        widths = bundle["glyph_widths"].copy()
        pixels = bundle["glyph_pixels"].copy()

    if widths.shape != (PRINTABLE_ASCII_COUNT,) or widths.dtype != np.uint8:
        raise RuntimeError(
            f"font.npz glyph_widths has wrong shape/dtype: {widths.shape} {widths.dtype}"
        )
    if pixels.ndim != 3 or pixels.shape[0] != PRINTABLE_ASCII_COUNT or pixels.shape[1] != height:
        raise RuntimeError(
            f"font.npz glyph_pixels has wrong shape {pixels.shape}; "
            f"expected ({PRINTABLE_ASCII_COUNT}, {height}, max_width)"
        )
    if pixels.dtype != np.uint8:
        raise RuntimeError(f"font.npz glyph_pixels wrong dtype {pixels.dtype}; expected uint8")
    if spacing != DEFAULT_GLYPH_SPACING:
        raise RuntimeError(
            f"font.npz spacing {spacing} != DEFAULT_GLYPH_SPACING {DEFAULT_GLYPH_SPACING}; "
            "upstream font changed — review palette.py constants"
        )

    widths.flags.writeable = False
    pixels.flags.writeable = False
    return Font(height=height, spacing=spacing, widths=widths, pixels=pixels)
