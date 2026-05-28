"""Pixel-font OCR. Port of
``users/james/personal_cogs/among_them/common/perception_kernels/ocr.nim``
plus the wrappers and helpers in
``users/james/personal_cogs/among_them/guided_bot/perception/ocr.nim``.

Reads the baked tiny5 font (5px tall, variable-width glyphs) from
:mod:`perception.data.font` and matches glyphs against frame pixels by
comparing the glyph's binary pixel mask to a "pixel-on" predicate over
the frame (``frame[y, x] != background``). Six public functions:

- :func:`best_glyph` — pick the best-matching ASCII glyph at ``(x, y)``.
- :func:`text_matches` — exact-phrase check at a fixed position.
- :func:`read_run` — read ``count`` variable-width glyphs starting at a
  pen position.
- :func:`read_line_strict` — read a line starting at the first
  non-background pixel on a row.
- :func:`find_text` — full-frame raster sweep for the first position
  where ``text`` matches.
- :func:`classify_interstitial` — refine
  :class:`interstitial.InterstitialKind` from
  :data:`interstitial.InterstitialKind.UNKNOWN` to the OCR-specific
  variants (role-reveal {/crewmate/imposter}, game-over).

**Pythonic departure from the upstream Nim:** :func:`best_glyph`
vectorises across all 95 glyphs in one numpy op instead of looping
glyph-by-glyph with a per-glyph early-exit budget. Reason: a 95-element
``for`` loop in Python has ~95 × ``np.count_nonzero`` setup cost which
exceeds the cost of the actual pixel arithmetic; one fused
``(95, h, max_w + spacing) bool`` reduction is faster on the only
hardware we run (CPython on M-series Mac). The early-exit budget the
upstream uses is irrelevant in numpy where reduction is always
all-pixels.

The packed-font tensor + column-mask are precomputed once per process
via :func:`_packed_font` (lru-cached).
"""

from __future__ import annotations

import functools
from dataclasses import dataclass
from typing import NamedTuple

import numpy as np

from .data import (
    FIRST_PRINTABLE_ASCII,
    LAST_PRINTABLE_ASCII,
    PRINTABLE_ASCII_COUNT,
    SPACE_COLOR,
    load_font,
)
from .frame import SCREEN_HEIGHT, SCREEN_WIDTH, oob_filled_patch
from .interstitial import InterstitialKind


# --- glyph preferences --------------------------------------------------


def _glyph_preference(ch: str) -> int:
    """Tie-break preference per glyph character. Mirrors upstream
    `glyphPreference`: lowercase > digit > uppercase > space > other."""
    if "a" <= ch <= "z":
        return 4
    if "0" <= ch <= "9":
        return 3
    if "A" <= ch <= "Z":
        return 2
    if ch == " ":
        return 1
    return 0


# --- packed-font cache --------------------------------------------------


@dataclass(frozen=True)
class _PackedFont:
    """Pre-arranged tensors used by the vectorised :func:`best_glyph`.

    - ``expected``: ``(95, height, max_width + spacing) uint8``. Glyph
      pixels are placed in cols ``0..width-1``; cols
      ``width..max_width+spacing-1`` are zero (background-expected so
      mismatches in the spacing column count as a miss when text
      bleeds over).
    - ``col_mask``: ``(95, max_width + spacing) bool``. True iff that
      column is part of the per-glyph scan rect (cols
      ``0..width+spacing-1``).
    - ``opaque``: ``(95,) int64``. Number of on-pixels in each glyph
      (used as a tie-break: richer glyphs beat near-blanks).
    - ``preferences``: ``(95,) int64``. See :func:`_glyph_preference`.
    - ``widths``: ``(95,) int64``. Cached as int64 to avoid casts at
      scan time.
    """

    height: int
    spacing: int
    max_width: int
    patch_width: int  # = max_width + spacing
    expected: np.ndarray
    col_mask: np.ndarray
    opaque: np.ndarray
    preferences: np.ndarray
    widths: np.ndarray


@functools.lru_cache(maxsize=1)
def _packed_font() -> _PackedFont:
    """Pack the loaded :class:`data.Font` into the tensors the kernel
    consumes. Called once per process via lru_cache."""
    font = load_font()
    h = font.height
    max_w = int(font.pixels.shape[2])
    spacing = font.spacing
    patch_w = max_w + spacing
    widths = font.widths.astype(np.int64)

    # expected: zero-padded per-glyph pixels in a (95, h, patch_w) array.
    expected = np.zeros((PRINTABLE_ASCII_COUNT, h, patch_w), dtype=np.uint8)
    expected[:, :, :max_w] = font.pixels

    # col_mask: True for cols 0..widths[g]+spacing-1 per glyph.
    col_indices = np.arange(patch_w, dtype=np.int64)
    col_mask = col_indices[None, :] < (widths + spacing)[:, None]

    # opaque count per glyph, computed only over the in-width region.
    in_width = col_indices[None, None, :max_w] < widths[:, None, None]
    opaque = (font.pixels.astype(np.int64) * in_width).sum(axis=(1, 2))

    preferences = np.array(
        [_glyph_preference(chr(FIRST_PRINTABLE_ASCII + i)) for i in range(PRINTABLE_ASCII_COUNT)],
        dtype=np.int64,
    )

    expected.flags.writeable = False
    col_mask.flags.writeable = False
    opaque.flags.writeable = False
    preferences.flags.writeable = False
    return _PackedFont(
        height=h,
        spacing=spacing,
        max_width=max_w,
        patch_width=patch_w,
        expected=expected,
        col_mask=col_mask,
        opaque=opaque,
        preferences=preferences,
        widths=widths,
    )


# --- best_glyph + text_matches + read helpers ---------------------------


class GlyphMatch(NamedTuple):
    """Result of :func:`best_glyph`. ``char`` is '?' when nothing
    cleared ``max_errors``; ``advance`` is then 0."""

    char: str
    errors: int
    advance: int


def best_glyph(
    frame: np.ndarray,
    x: int,
    y: int,
    max_errors: int = 0,
    background: int = SPACE_COLOR,
) -> GlyphMatch:
    """Pick the best-matching ASCII glyph at ``(x, y)``.

    Tie-break order (mirrors upstream ``mb_best_glyph``):

    1. Fewer mismatches.
    2. More opaque pixels (glyphs with richer structure beat near-blanks).
    3. Higher :func:`_glyph_preference` (lowercase > digit > upper > space > other).

    Returns ``('?', errors, 0)`` when no glyph clears ``max_errors`` —
    where ``errors`` is the lowest miss count any candidate achieved.
    """
    pf = _packed_font()
    patch = oob_filled_patch(frame, x, y, (pf.height, pf.patch_width))
    patch_on = (patch != background).astype(np.uint8)

    # diff is (95, h, patch_w). The col_mask filters mismatches outside
    # each glyph's scan rect.
    diff = (pf.expected != patch_on[None]) & pf.col_mask[:, None, :]
    errors = diff.sum(axis=(1, 2)).astype(np.int64)
    # Glyphs with width <= 0 (none in tiny5, but guard upstream rule):
    errors = np.where(pf.widths > 0, errors, np.iinfo(np.int64).max)

    # Restrict to candidates inside the error budget.
    feasible = errors <= max_errors
    if not feasible.any():
        # Upstream's `mb_best_glyph` reports `errors = max_errors + 1`
        # as the failure sentinel (the initial value of `bestErrors`
        # that never gets overwritten when no glyph clears budget),
        # not the true minimum-error count. Mirror it for parity.
        return GlyphMatch(char="?", errors=max_errors + 1, advance=0)

    # Lex-sort within feasible: (errors asc, -opaque asc = opaque desc,
    # -pref asc = pref desc). `np.lexsort` reads keys in reverse —
    # last key is primary.
    cand = np.where(feasible)[0]
    order = np.lexsort(
        (
            -pf.preferences[cand],
            -pf.opaque[cand],
            errors[cand],
        )
    )
    best_idx = int(cand[order[0]])
    ch = chr(FIRST_PRINTABLE_ASCII + best_idx)
    width = int(pf.widths[best_idx])
    return GlyphMatch(char=ch, errors=int(errors[best_idx]), advance=width + pf.spacing)


def _text_to_indices(text: str) -> list[int]:
    """Map an arbitrary string to glyph indices. ``'\\n'`` -> -1
    (newline sentinel); out-of-range chars fall back to '?'."""
    result: list[int] = []
    fallback = ord("?") - FIRST_PRINTABLE_ASCII
    for ch in text:
        if ch == "\n":
            result.append(-1)
            continue
        code = ord(ch)
        if code < FIRST_PRINTABLE_ASCII or code > LAST_PRINTABLE_ASCII:
            result.append(fallback)
        else:
            result.append(code - FIRST_PRINTABLE_ASCII)
    return result


def text_matches(
    frame: np.ndarray,
    text: str,
    x: int,
    y: int,
    max_errors: int = 0,
    background: int = SPACE_COLOR,
) -> bool:
    """True iff ``text`` renders at ``(x, y)`` within ``max_errors``
    total mismatches. Mirrors upstream ``mb_text_matches``.

    Newlines reset the pen x to ``x`` and advance the pen y by
    ``font.height + font.spacing``. The match is reported as the
    upstream's ``opaque > 0 and errors <= max_errors`` predicate so
    an empty string can never match.
    """
    if not text:
        return False
    pf = _packed_font()
    indices = _text_to_indices(text)
    total_errors = 0
    total_opaque = 0
    pen_x = x
    pen_y = y
    for idx in indices:
        if idx == -1:  # newline
            pen_x = x
            pen_y += pf.height + pf.spacing
            continue
        width = int(pf.widths[idx])
        if width <= 0:
            continue
        scan_w = width + pf.spacing
        # Expected glyph pixels, padded with zeros in the spacing column.
        expected = np.zeros((pf.height, scan_w), dtype=np.uint8)
        expected[:, :width] = pf.expected[idx, :, :width]
        # Actual frame patch under the pen.
        patch = oob_filled_patch(frame, pen_x, pen_y, (pf.height, scan_w))
        actual_on = (patch != background).astype(np.uint8)
        total_errors += int(np.count_nonzero(expected != actual_on))
        total_opaque += int(expected.sum())
        pen_x += width + pf.spacing
    return total_opaque > 0 and total_errors <= max_errors


def read_run(
    frame: np.ndarray,
    x: int,
    y: int,
    count: int,
    max_errors: int = 0,
    background: int = SPACE_COLOR,
    strip: bool = True,
) -> str:
    """Read ``count`` variable-width glyphs starting at ``(x, y)``,
    advancing the pen by the winning glyph's width + spacing each
    step. Unknown glyphs ('?') advance by ``font.max_width + spacing``
    so a single bad position can't lock the pen in place."""
    pf = _packed_font()
    pen_x = x
    buf: list[str] = []
    fallback_advance = pf.max_width + pf.spacing
    for _ in range(count):
        match = best_glyph(frame, pen_x, y, max_errors, background)
        buf.append(match.char)
        pen_x += match.advance if match.advance > 0 else fallback_advance
    out = "".join(buf)
    return out.strip(" ") if strip else out


def read_line_strict(
    frame: np.ndarray,
    y: int,
    max_errors: int = 0,
    background: int = SPACE_COLOR,
) -> str:
    """Read a line starting at the first non-background pixel on row
    ``y``. Returns ``""`` if the row is entirely background. Reads up
    to 32 glyphs (upstream cap)."""
    row = np.asarray(frame[y])
    nonbg = np.where(row != background)[0]
    if len(nonbg) == 0:
        return ""
    return read_run(frame, int(nonbg[0]), y, 32, max_errors, background)


# --- find_text + classify_interstitial ----------------------------------


def find_text(
    frame: np.ndarray,
    text: str,
    max_errors: int = 0,
    background: int = SPACE_COLOR,
) -> tuple[bool, int, int]:
    """Full-frame raster sweep for the first ``(x, y)`` where ``text``
    matches. Mirrors upstream ``findText``.

    The X bound clamps to ``SCREEN_WIDTH - render_width + spacing`` so
    the last glyph's spacing column can still partially fall on
    screen — exact match to the upstream Nim. Raster order
    (y-major) means the top-leftmost match wins.
    """
    if not text:
        return False, 0, 0
    pf = _packed_font()
    indices = _text_to_indices(text)
    # Compute render width: sum of widths + spacing for each non-newline.
    text_w = 0
    for idx in indices:
        if idx < 0:
            continue
        if 0 <= idx < PRINTABLE_ASCII_COUNT:
            text_w += int(pf.widths[idx]) + pf.spacing
    max_x = SCREEN_WIDTH - text_w + pf.spacing
    max_y = SCREEN_HEIGHT - pf.height
    for ty in range(0, max_y + 1):
        for tx in range(0, max(0, max_x) + 1):
            if text_matches(frame, text, tx, ty, max_errors, background):
                return True, tx, ty
    return False, 0, 0


# Known interstitial banner strings and their classification. Searched
# in this order; first match wins. Longer strings come first so
# "IMPS WIN" beats the "IMPS" role-reveal banner. Mirrors upstream
# `InterstitialBanners`.
_INTERSTITIAL_BANNERS: tuple[tuple[str, InterstitialKind], ...] = (
    ("CREW WINS", InterstitialKind.GAME_OVER),
    ("CREW WIN", InterstitialKind.GAME_OVER),
    ("IMPS WIN", InterstitialKind.GAME_OVER),
    ("CREWMATE", InterstitialKind.ROLE_REVEAL_CREWMATE),
    ("IMPS", InterstitialKind.ROLE_REVEAL_IMPOSTER),
)


def _count_color_in_rect(
    frame: np.ndarray, x0: int, y0: int, w: int, h: int, color: int
) -> int:
    """Count pixels equal to ``color`` in the clamped rect
    ``[x0, x0+w) × [y0, y0+h)``. Used by
    :func:`_looks_like_game_over_summary`."""
    y_lo = max(0, y0)
    y_hi = min(SCREEN_HEIGHT, y0 + h)
    x_lo = max(0, x0)
    x_hi = min(SCREEN_WIDTH, x0 + w)
    if y_lo >= y_hi or x_lo >= x_hi:
        return 0
    return int(np.count_nonzero(frame[y_lo:y_hi, x_lo:x_hi] == color))


# Game-over summary layout. The live game-over screen uses the server's
# 7px ASCII font, while the current OCR font is 6px tall — so
# `find_text` can't match the title text directly. Detect the layout
# instead: a top white title plus role labels in the player list.
_GAME_OVER_TITLE_WHITE_MIN = 50
_GAME_OVER_ROLE_WHITE_MIN = 80
_GAME_OVER_ROLE_ROWS = (20, 34, 48, 62, 76, 90, 104, 118)
_PALETTE_WHITE = 2


def _looks_like_game_over_summary(frame: np.ndarray) -> bool:
    title = _count_color_in_rect(frame, 20, 2, 89, 9, _PALETTE_WHITE)
    role_total = sum(
        _count_color_in_rect(frame, 19, y, 36, 8, _PALETTE_WHITE)
        for y in _GAME_OVER_ROLE_ROWS
    )
    return title >= _GAME_OVER_TITLE_WHITE_MIN and role_total >= _GAME_OVER_ROLE_WHITE_MIN


def classify_interstitial(
    frame: np.ndarray, max_errors: int = 2
) -> InterstitialKind:
    """Refine an interstitial frame's :class:`InterstitialKind` by
    scanning for known banner text. Returns
    :data:`InterstitialKind.UNKNOWN` when no banner matches and the
    game-over layout heuristic doesn't fire.

    Callers should have already classified the frame as an
    interstitial via :func:`interstitial.detect_interstitial` — this
    function makes no black-pixel check.
    """
    for text, kind in _INTERSTITIAL_BANNERS:
        found, _, _ = find_text(frame, text, max_errors)
        if found:
            return kind
    if _looks_like_game_over_summary(frame):
        return InterstitialKind.GAME_OVER
    return InterstitialKind.UNKNOWN
