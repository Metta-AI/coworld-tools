"""Pixel-font OCR against a 128×128 framebuffer.

Port of ``among_them/texts.nim`` + the framebuffer-scoring procs from
``common/pixelfonts.nim``. Provides the three primitives modulabot
actually needs:

- :func:`text_matches` — "is this exact phrase visible at ``(x, y)``?"
  Used for interstitial banner detection (``"CREWMATE"``, ``"IMPS"``,
  ``"CREW WIN"``, ``"IMPS WIN"``) and for polling "SKIP" on the
  voting screen.
- :func:`find_text` — "is this phrase visible anywhere on the
  screen?" Used when the banner position drifts between rounds or
  when we want to detect a vote modal without committing to a
  coordinate.
- :func:`read_line` / :func:`read_run` — OCR-style reads for voting
  chat and free-form interstitial text.

All functions take a ``(128, 128) uint8`` indexed framebuffer and a
:class:`~modulabot.data.PixelFont`. The font's foreground vs.
background semantics inside the frame are indexed: any frame pixel
whose palette index is not :data:`~modulabot.data.SPACE_COLOR`
(default 0 = black) is treated as "text on". This matches the Nim
``framePixelOn(frame, x, y, 0'u8)`` convention and works because
BitWorld always renders interstitial banners and voting UI on a
black backdrop.

Compared with the scalar Nim implementation:

- :func:`text_matches` and :func:`find_text` are vectorised — the
  scanning sweep in :func:`find_text` uses a single numpy compare
  across every candidate anchor row/column per glyph, which keeps the
  cost well under one millisecond even on a worst-case SKIP sweep.
- :func:`best_glyph` (the per-position OCR pick) iterates the 95
  printable glyphs in Python, which is acceptable: OCR only runs on
  voting-chat frames (~once per meeting, < 50 glyph positions).

The font is variable-width — glyph advance equals
``glyph.width + font.spacing`` — so per-position OCR must use
:func:`best_glyph`'s returned advance to step through a string.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from . import nim_perception as _nim_perception
from .data import (
    FIRST_PRINTABLE_ASCII,
    SCREEN_HEIGHT,
    SCREEN_WIDTH,
    SPACE_COLOR,
    PixelFont,
    PixelGlyph,
)

# ---------------------------------------------------------------------------
# Score types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class GlyphScore:
    """Per-glyph OCR score, matching ``PixelGlyphScore`` in Nim.

    ``misses`` = expected-foreground pixels that were background in
    the frame. ``extras`` = background-in-glyph pixels that were
    foreground in the frame (e.g. another glyph bleeding into this
    one's cell). ``opaque`` = total expected-foreground pixels in
    the glyph. ``foreground`` = total on-pixels in the frame cell
    regardless of glyph expectations.

    :meth:`error` returns the total mismatch count used by
    :func:`text_matches` and :func:`best_glyph` to rank candidates
    against a ``max_errors`` budget.
    """

    misses: int
    extras: int
    opaque: int
    foreground: int

    @property
    def error(self) -> int:
        return self.misses + self.extras


@dataclass(frozen=True)
class TextMatch:
    """Return type for :func:`find_text`. ``found`` is ``False`` with
    zeroed coordinates when no match exists."""

    found: bool
    x: int = 0
    y: int = 0


# ---------------------------------------------------------------------------
# Glyph lookup
# ---------------------------------------------------------------------------


def glyph_at(font: PixelFont, ch: str) -> PixelGlyph:
    """Return the glyph for ``ch`` or fall back to ``'?'``.

    Matches ``glyphAt`` / ``glyphIndex`` in ``pixelfonts.nim`` —
    unknown characters become question marks, and a font that doesn't
    even ship ``'?'`` is treated as having zero-width glyphs for
    anything unknown.
    """
    idx = ord(ch) - FIRST_PRINTABLE_ASCII
    if idx < 0 or idx >= len(font.glyphs):
        idx = ord("?") - FIRST_PRINTABLE_ASCII
        if idx < 0 or idx >= len(font.glyphs):
            return PixelGlyph(ch=ch, width=0, height=font.height, pixels=np.zeros((font.height, 0), dtype=bool))
    return font.glyphs[idx]


def glyph_advance(font: PixelFont, ch: str) -> int:
    """Horizontal advance for one character. Zero-width glyphs (e.g.
    padding entries) don't advance the pen."""
    g = glyph_at(font, ch)
    if g.width <= 0:
        return 0
    return g.width + font.spacing


def text_width(font: PixelFont, text: str) -> int:
    """Return the max line-width in pixels for a multi-line text run.

    Matches ``textWidth`` in ``pixelfonts.nim``. Newlines reset the
    line width; spacing is inserted between non-first glyphs on each
    line.
    """
    line = 0
    best = 0
    for ch in text:
        if ch == "\n":
            best = max(best, line)
            line = 0
            continue
        g = glyph_at(font, ch)
        if g.width <= 0:
            continue
        if line > 0:
            line += font.spacing
        line += g.width
    return max(best, line)


# ---------------------------------------------------------------------------
# Frame scoring (vectorised)
# ---------------------------------------------------------------------------


def _frame_pixel_on(frame: np.ndarray, background: int = SPACE_COLOR) -> np.ndarray:
    """Boolean mask: ``True`` for every pixel that isn't the text
    background. Precomputed once per frame by callers that run many
    glyph scores — cheap but worth caching for long ``find_text`` or
    OCR sweeps."""
    return frame != background


def glyph_score(
    frame: np.ndarray,
    font: PixelFont,
    ch: str,
    x: int,
    y: int,
    background: int = SPACE_COLOR,
) -> GlyphScore:
    """Score one glyph against the frame at anchor ``(x, y)``.

    Scan width is ``glyph.width + font.spacing`` so the trailing
    inter-glyph gap is audited for bleed-over (matches the Nim
    scalar implementation). Off-screen pixels are treated as
    background.
    """
    g = glyph_at(font, ch)
    scan_w = g.width + font.spacing
    scan_h = g.height
    if scan_w <= 0 or scan_h <= 0:
        return GlyphScore(0, 0, 0, 0)

    # Allocate the expected + actual scan windows once.
    expected = np.zeros((scan_h, scan_w), dtype=bool)
    if g.width > 0:
        expected[:, : g.width] = g.pixels

    # Clip to the frame; pad missing area with background (-> actual = False).
    actual = np.zeros((scan_h, scan_w), dtype=bool)
    y0 = max(y, 0)
    x0 = max(x, 0)
    y1 = min(y + scan_h, SCREEN_HEIGHT)
    x1 = min(x + scan_w, SCREEN_WIDTH)
    if y1 > y0 and x1 > x0:
        dy0 = y0 - y
        dx0 = x0 - x
        actual[dy0 : dy0 + (y1 - y0), dx0 : dx0 + (x1 - x0)] = (
            frame[y0:y1, x0:x1] != background
        )

    misses = int(np.count_nonzero(expected & ~actual))
    extras = int(np.count_nonzero(~expected & actual))
    opaque = int(np.count_nonzero(expected))
    foreground = int(np.count_nonzero(actual))
    return GlyphScore(misses=misses, extras=extras, opaque=opaque, foreground=foreground)


def text_score(
    frame: np.ndarray,
    font: PixelFont,
    text: str,
    x: int,
    y: int,
    background: int = SPACE_COLOR,
) -> GlyphScore:
    """Sum of per-glyph scores for an expected text run.

    Multi-line strings split on ``\\n``. Newlines don't carry glyph
    spacing — they reset the pen X and advance Y by
    ``font.height + font.spacing``.
    """
    pen_x = x
    pen_y = y
    misses = extras = opaque = foreground = 0
    for ch in text:
        if ch == "\n":
            pen_x = x
            pen_y += font.height + font.spacing
            continue
        s = glyph_score(frame, font, ch, pen_x, pen_y, background)
        misses += s.misses
        extras += s.extras
        opaque += s.opaque
        foreground += s.foreground
        pen_x += glyph_advance(font, ch)
    return GlyphScore(misses=misses, extras=extras, opaque=opaque, foreground=foreground)


def text_matches(
    frame: np.ndarray,
    font: PixelFont,
    text: str,
    x: int,
    y: int,
    max_errors: int = 0,
    background: int = SPACE_COLOR,
) -> bool:
    """True when ``text`` is rendered at ``(x, y)`` within the error
    budget. Zero errors means a pixel-perfect match — the default —
    which is what interstitial-banner detection wants.

    Dispatches to the Nim FFI when available; both paths produce
    identical booleans (pinned by
    ``tests/test_nim_perception.py::OcrParityTests``).
    """
    if not text:
        return False
    if _nim_perception.HAVE_NATIVE:
        return _nim_perception.text_matches(
            frame, font, text, x, y, max_errors, background,
        )
    return _text_matches_numpy(frame, font, text, x, y, max_errors, background)


def _text_matches_numpy(
    frame: np.ndarray,
    font: PixelFont,
    text: str,
    x: int,
    y: int,
    max_errors: int = 0,
    background: int = SPACE_COLOR,
) -> bool:
    """Pure-Python fallback for :func:`text_matches`."""
    s = text_score(frame, font, text, x, y, background)
    return s.opaque > 0 and s.error <= max_errors


def find_text(
    frame: np.ndarray,
    font: PixelFont,
    text: str,
    max_errors: int = 0,
    background: int = SPACE_COLOR,
) -> TextMatch:
    """Return the first ``(x, y)`` where ``text`` renders cleanly, or
    an unfound match.

    Vectorised via :func:`numpy.lib.stride_tricks.sliding_window_view`:
    we build the expected-bitmap for the phrase once, then compute
    mismatch counts for every candidate anchor in a single numpy
    pass. This keeps the worst-case sweep (phrase not present →
    scanning every anchor) in the low single-digit milliseconds
    instead of the ~400 ms a scalar Python loop costs.

    Iteration order for the first-match semantics is raster (rows
    top-to-bottom, columns left-to-right), matching the Nim
    implementation so any known banner position in the Nim bot stays
    at the same coordinates here.
    """
    if not text:
        return TextMatch(found=False)
    expected, scan_w = _build_expected_bitmap(font, text)
    scan_h = font.height
    opaque_total = int(expected.sum())
    if scan_w <= 0 or scan_h <= 0 or opaque_total == 0:
        return TextMatch(found=False)
    max_x = SCREEN_WIDTH - scan_w
    max_y = SCREEN_HEIGHT - scan_h
    if max_x < 0 or max_y < 0:
        return TextMatch(found=False)

    from numpy.lib.stride_tricks import sliding_window_view

    frame_on = frame != background
    windows = sliding_window_view(frame_on, (scan_h, scan_w))
    # windows.shape == (max_y + 1, max_x + 1, scan_h, scan_w)
    mismatches = (windows ^ expected[None, None, :, :]).sum(axis=(2, 3))

    # Raster-order argwhere walks y-major then x; first entry is the
    # top-leftmost valid anchor.
    accepts = np.argwhere(mismatches <= max_errors)
    if accepts.size == 0:
        return TextMatch(found=False)
    y, x = accepts[0]
    return TextMatch(found=True, x=int(x), y=int(y))


def _build_expected_bitmap(
    font: PixelFont, text: str
) -> tuple[np.ndarray, int]:
    """Render the expected-foreground bitmap for a single-line phrase.

    Returns ``(bitmap, scan_width)`` where ``bitmap`` has shape
    ``(font.height, scan_width)`` and ``scan_width`` is the final pen
    X — i.e. each glyph's width plus the trailing inter-glyph
    spacing column (matching
    :func:`glyph_score`'s ``glyph.width + font.spacing`` scan width).

    Newlines are not supported here; the vectorised ``find_text``
    path is single-line only. Multi-line phrases still work through
    the scalar :func:`text_matches` path.
    """
    if not text:
        return np.zeros((font.height, 0), dtype=bool), 0
    # Accumulate total scan width.
    advances = [glyph_advance(font, ch) for ch in text]
    scan_w = sum(advances)
    if scan_w <= 0:
        return np.zeros((font.height, 0), dtype=bool), 0
    bitmap = np.zeros((font.height, scan_w), dtype=bool)
    pen = 0
    for ch, adv in zip(text, advances):
        g = glyph_at(font, ch)
        if g.width > 0:
            bitmap[:, pen : pen + g.width] = g.pixels
        pen += adv
    return bitmap, scan_w


# ---------------------------------------------------------------------------
# OCR readers
# ---------------------------------------------------------------------------


_GLYPH_PREFERENCE_RANGES: tuple[tuple[str, str, int], ...] = (
    ("a", "z", 4),
    ("0", "9", 3),
    ("A", "Z", 2),
)


def _glyph_preference(ch: str) -> int:
    """Tie-break preference used by :func:`best_glyph`. Matches
    ``glyphPreference`` in Nim — prefer lowercase letters, then
    digits, then uppercase, then space, then punctuation."""
    for lo, hi, score in _GLYPH_PREFERENCE_RANGES:
        if lo <= ch <= hi:
            return score
    if ch == " ":
        return 1
    return 0


def best_glyph(
    frame: np.ndarray,
    font: PixelFont,
    x: int,
    y: int,
    max_errors: int = 0,
    background: int = SPACE_COLOR,
) -> str:
    """Return the best-matching glyph at ``(x, y)`` or ``'?'`` if no
    glyph clears ``max_errors``.

    Dispatches to the Nim FFI when available. Both paths apply the
    same tie-break (fewer errors → more opaque pixels → preferred
    character class) and produce byte-identical output (pinned by
    ``tests/test_nim_perception.py::OcrParityTests``).
    """
    if _nim_perception.HAVE_NATIVE:
        ch, _errors, _advance = _nim_perception.best_glyph(
            frame, font, x, y, max_errors, background,
        )
        return ch
    return _best_glyph_numpy(frame, font, x, y, max_errors, background)


def _best_glyph_numpy(
    frame: np.ndarray,
    font: PixelFont,
    x: int,
    y: int,
    max_errors: int = 0,
    background: int = SPACE_COLOR,
) -> str:
    """Pure-Python vectorised fallback for :func:`best_glyph`.

    Vectorised: glyphs are pre-grouped by scan width (see
    :func:`_glyph_width_groups`). For each width group we extract a
    single frame slice, XOR it against the stacked expected bitmap
    for all glyphs of that width, and sum per-glyph errors in one
    numpy reduction. This replaces 95 sequential Python-dispatched
    :func:`glyph_score` calls with ~5 vectorised batches.

    Tie-breaks match the scalar reference (fewer errors > more
    opaque pixels > preferred character class).
    """
    groups = _glyph_width_groups(font)
    best_char = "?"
    best_errors = 1 << 30
    best_opaque = -1
    best_pref = -1

    for scan_w, info in groups.items():
        if scan_w <= 0 or font.height <= 0:
            continue
        expected = info["expected"]  # (n_glyphs, h, scan_w) bool
        opaque = info["opaque"]  # (n_glyphs,) int32
        chars = info["chars"]  # list[str]
        preferences = info["preferences"]  # (n_glyphs,) int32

        # Build the matching frame slice, zero-padded where it falls
        # off the screen. The padding bytes compare False against
        # `background` (i.e. "not on"), matching the scalar path.
        actual = np.zeros((font.height, scan_w), dtype=bool)
        y0 = max(y, 0)
        x0 = max(x, 0)
        y1 = min(y + font.height, SCREEN_HEIGHT)
        x1 = min(x + scan_w, SCREEN_WIDTH)
        if y1 > y0 and x1 > x0:
            dy0 = y0 - y
            dx0 = x0 - x
            actual[dy0 : dy0 + (y1 - y0), dx0 : dx0 + (x1 - x0)] = (
                frame[y0:y1, x0:x1] != background
            )

        # mismatch[g] = sum over (h, scan_w) of expected[g] != actual
        diffs = expected ^ actual[None, :, :]
        errors = diffs.sum(axis=(1, 2), dtype=np.int32)

        # Find the best glyph in this width group, applying the same
        # tie-break the scalar bestGlyph uses.
        # Candidates are ranked by (errors, -opaque, -preference); pick
        # argmin.
        keys = errors * (1 << 16) + (1 << 16) - opaque  # break tie by opaque desc
        # Preference is already small; fold in last as the finest grain.
        keys = keys * 16 + (15 - preferences)
        idx = int(np.argmin(keys))
        ge = int(errors[idx])
        go = int(opaque[idx])
        gp = int(preferences[idx])
        if (
            ge < best_errors
            or (ge == best_errors and go > best_opaque)
            or (ge == best_errors and go == best_opaque and gp > best_pref)
        ):
            best_char = chars[idx]
            best_errors = ge
            best_opaque = go
            best_pref = gp

    if best_errors > max_errors:
        return "?"
    return best_char


# --- Vectorised glyph-group cache -----------------------------------------
#
# The vectorised :func:`best_glyph` precomputes a per-scan-width stack of
# glyph expected bitmaps once per font. Keyed on ``id(font)`` because
# :class:`~modulabot.data.PixelFont` is frozen and not hashable.


_GLYPH_WIDTH_CACHE: dict[int, dict[int, dict[str, np.ndarray | list[str]]]] = {}


def _glyph_width_groups(
    font: PixelFont,
) -> dict[int, dict[str, np.ndarray | list[str]]]:
    """Return (and memoise) per-scan-width glyph batches for ``font``.

    Output structure is ``{scan_w: {expected, opaque, chars,
    preferences}}`` where ``expected`` is ``(n, h, scan_w) bool``.
    Zero-width glyphs (padding entries for fonts that don't cover
    the full printable range) are excluded — they match everything
    which would pollute tie-breaks.
    """
    key = id(font)
    cached = _GLYPH_WIDTH_CACHE.get(key)
    if cached is not None:
        return cached

    by_width: dict[int, list[tuple[str, np.ndarray, int, int]]] = {}
    for g in font.glyphs:
        if g.width <= 0:
            continue
        scan_w = g.width + font.spacing
        bm = np.zeros((font.height, scan_w), dtype=bool)
        bm[:, : g.width] = g.pixels
        opaque = int(g.pixels.sum())
        pref = _glyph_preference(g.ch)
        by_width.setdefault(scan_w, []).append((g.ch, bm, opaque, pref))

    out: dict[int, dict[str, np.ndarray | list[str]]] = {}
    for scan_w, entries in by_width.items():
        chars = [e[0] for e in entries]
        stacked = np.stack([e[1] for e in entries], axis=0)
        opaque_arr = np.array([e[2] for e in entries], dtype=np.int32)
        pref_arr = np.array([e[3] for e in entries], dtype=np.int32)
        out[scan_w] = {
            "chars": chars,
            "expected": stacked,
            "opaque": opaque_arr,
            "preferences": pref_arr,
        }
    _GLYPH_WIDTH_CACHE[key] = out
    return out


def read_run(
    frame: np.ndarray,
    font: PixelFont,
    x: int,
    y: int,
    count: int,
    max_errors: int = 0,
    background: int = SPACE_COLOR,
    strip: bool = True,
) -> str:
    """Read ``count`` variable-width glyphs starting at ``(x, y)``.

    Advances the pen by each glyph's actual width; a missing-glyph
    read (``'?'``) still advances by the question-mark glyph's width
    so we don't desync with the rest of the line.
    """
    pen = x
    out: list[str] = []
    for _ in range(count):
        ch = best_glyph(frame, font, pen, y, max_errors, background)
        out.append(ch)
        pen += glyph_advance(font, ch)
    text = "".join(out)
    if strip:
        text = text.strip()
    return text


def read_line(
    frame: np.ndarray,
    font: PixelFont,
    y: int,
    max_errors: int = 0,
    background: int = SPACE_COLOR,
) -> str:
    """Read the tiny-font line whose top row is at ``y``.

    The leftmost text column is found by scanning across *every row
    within the glyph height* — not just row ``y`` — so lowercase
    glyphs whose top row is empty (e.g. ``r``, ``e``, ``n``) don't
    cause us to start reading mid-word on the top pixel of a later
    ascender.

    This is a deliberate divergence from the Nim ``readAsciiLine``,
    which scans only row ``y`` and relies on the caller to try
    multiple ``y`` values and filter garbage. The Python version
    works correctly given a single ``y`` at the top of the text
    line; the Nim behaviour is reachable via ``read_line_strict``
    when parity matters.

    Returns ``""`` if no text row has content, otherwise the stripped
    result of reading up to 32 glyphs from the first text column.
    """
    if y < 0 or y + font.height > SCREEN_HEIGHT:
        return ""
    block = frame[y : y + font.height, :] != background
    any_col = block.any(axis=0)
    non_bg = np.where(any_col)[0]
    if non_bg.size == 0:
        return ""
    first_x = int(non_bg[0])
    return read_run(frame, font, first_x, y, 32, max_errors, background, strip=True)


def read_line_strict(
    frame: np.ndarray,
    font: PixelFont,
    y: int,
    max_errors: int = 0,
    background: int = SPACE_COLOR,
) -> str:
    """Strict port of the Nim ``readAsciiLine`` single-row scan.

    Scans only row ``y`` for the first non-background pixel, then
    reads up to 32 glyphs from there. Callers that want parity with
    the Nim bot (e.g. driving a chat-OCR loop across multiple ``y``
    values and filtering ``?``-heavy rows) should use this; most
    Python callers should prefer :func:`read_line` for its
    smarter-column-scan behaviour.
    """
    if y < 0 or y >= SCREEN_HEIGHT:
        return ""
    row = frame[y]
    non_bg = np.where(row != background)[0]
    if non_bg.size == 0:
        return ""
    first_x = int(non_bg[0])
    return read_run(frame, font, first_x, y, 32, max_errors, background, strip=True)


__all__ = [
    "GlyphScore",
    "TextMatch",
    "glyph_at",
    "glyph_advance",
    "text_width",
    "glyph_score",
    "text_score",
    "text_matches",
    "find_text",
    "best_glyph",
    "read_run",
    "read_line",
    "read_line_strict",
]
