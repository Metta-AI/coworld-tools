"""OCR engine for the Persephone 3x5 pixel font.

Reads text from specific positions in the 128x128 frame by matching
known glyph patterns against pixels of a target color.
"""

from __future__ import annotations

import numpy as np

from ._common import SCREEN_HEIGHT, SCREEN_WIDTH

# ---------------------------------------------------------------------------
# Font data -- ported from rendering/framebuffer.ts
# Each glyph is a 5-row x 3-col array: 1 = pixel on, 0 = pixel off.
# ---------------------------------------------------------------------------

_GLYPHS: dict[str, list[list[int]]] = {
    "A": [[1,1,1],[1,0,1],[1,1,1],[1,0,1],[1,0,1]],
    "B": [[1,1,0],[1,0,1],[1,1,0],[1,0,1],[1,1,0]],
    "C": [[1,1,1],[1,0,0],[1,0,0],[1,0,0],[1,1,1]],
    "D": [[1,1,0],[1,0,1],[1,0,1],[1,0,1],[1,1,0]],
    "E": [[1,1,1],[1,0,0],[1,1,0],[1,0,0],[1,1,1]],
    "F": [[1,1,1],[1,0,0],[1,1,0],[1,0,0],[1,0,0]],
    "G": [[1,1,1],[1,0,0],[1,0,1],[1,0,1],[1,1,1]],
    "H": [[1,0,1],[1,0,1],[1,1,1],[1,0,1],[1,0,1]],
    "I": [[1,1,1],[0,1,0],[0,1,0],[0,1,0],[1,1,1]],
    "J": [[0,0,1],[0,0,1],[0,0,1],[1,0,1],[1,1,1]],
    "K": [[1,0,1],[1,0,1],[1,1,0],[1,0,1],[1,0,1]],
    "L": [[1,0,0],[1,0,0],[1,0,0],[1,0,0],[1,1,1]],
    "M": [[1,0,1],[1,1,1],[1,1,1],[1,0,1],[1,0,1]],
    "N": [[1,1,1],[1,0,1],[1,0,1],[1,0,1],[1,0,1]],
    "O": [[1,1,1],[1,0,1],[1,0,1],[1,0,1],[1,1,1]],
    "P": [[1,1,1],[1,0,1],[1,1,1],[1,0,0],[1,0,0]],
    "Q": [[1,1,1],[1,0,1],[1,0,1],[1,1,1],[0,0,1]],
    "R": [[1,1,1],[1,0,1],[1,1,0],[1,0,1],[1,0,1]],
    "S": [[0,1,1],[1,0,0],[0,1,1],[0,0,1],[1,1,0]],
    "T": [[1,1,1],[0,1,0],[0,1,0],[0,1,0],[0,1,0]],
    "U": [[1,0,1],[1,0,1],[1,0,1],[1,0,1],[1,1,1]],
    "V": [[1,0,1],[1,0,1],[1,0,1],[1,0,1],[0,1,0]],
    "W": [[1,0,1],[1,0,1],[1,0,1],[1,1,1],[1,0,1]],
    "X": [[1,0,1],[1,0,1],[0,1,0],[1,0,1],[1,0,1]],
    "Y": [[1,0,1],[1,0,1],[1,1,1],[0,1,0],[0,1,0]],
    "Z": [[1,1,1],[0,0,1],[0,1,0],[1,0,0],[1,1,1]],
    "0": [[0,1,0],[1,0,1],[1,0,1],[1,0,1],[0,1,0]],
    "1": [[0,1,0],[1,1,0],[0,1,0],[0,1,0],[1,1,1]],
    "2": [[1,1,1],[0,0,1],[1,1,1],[1,0,0],[1,1,1]],
    "3": [[1,1,1],[0,0,1],[1,1,1],[0,0,1],[1,1,1]],
    "4": [[1,0,1],[1,0,1],[1,1,1],[0,0,1],[0,0,1]],
    "5": [[1,1,1],[1,0,0],[1,1,1],[0,0,1],[1,1,1]],
    "6": [[1,1,1],[1,0,0],[1,1,1],[1,0,1],[1,1,1]],
    "7": [[1,1,1],[0,0,1],[0,0,1],[0,0,1],[0,0,1]],
    "8": [[1,1,1],[1,0,1],[1,1,1],[1,0,1],[1,1,1]],
    "9": [[1,1,1],[1,0,1],[1,1,1],[0,0,1],[1,1,1]],
    ":": [[0,0,0],[0,1,0],[0,0,0],[0,1,0],[0,0,0]],
    "!": [[0,1,0],[0,1,0],[0,1,0],[0,0,0],[0,1,0]],
    "?": [[1,1,1],[0,0,1],[0,1,1],[0,0,0],[0,1,0]],
    "'": [[0,1,0],[0,1,0],[0,0,0],[0,0,0],[0,0,0]],
    ".": [[0,0,0],[0,0,0],[0,0,0],[0,0,0],[0,1,0]],
    ",": [[0,0,0],[0,0,0],[0,0,0],[0,1,0],[1,0,0]],
    "-": [[0,0,0],[0,0,0],[1,1,1],[0,0,0],[0,0,0]],
    "/": [[0,0,1],[0,0,1],[0,1,0],[1,0,0],[1,0,0]],
    "*": [[0,0,0],[1,0,1],[0,1,0],[1,0,1],[0,0,0]],
    "(": [[0,1,0],[1,0,0],[1,0,0],[1,0,0],[0,1,0]],
    ")": [[0,1,0],[0,0,1],[0,0,1],[0,0,1],[0,1,0]],
    "<": [[0,0,1],[0,1,0],[1,0,0],[0,1,0],[0,0,1]],
    ">": [[1,0,0],[0,1,0],[0,0,1],[0,1,0],[1,0,0]],
}

# Pre-compute NumPy arrays for fast matching
_GLYPH_ARRAYS: dict[str, np.ndarray] = {
    ch: np.array(rows, dtype=np.uint8)
    for ch, rows in _GLYPHS.items()
}

GLYPH_W = 3
GLYPH_H = 5
CHAR_ADVANCE = GLYPH_W + 1  # 4 pixels per character
SPACE_WIDTH = 4

# Characters previously believed to be ambiguous (S/5 and O/0).
# In reality, the game renders distinct glyphs for these pairs.
# Retained as empty for backward compatibility with callers that
# reference this constant.
AMBIGUOUS_PAIRS: dict[str, str] = {}


# ---------------------------------------------------------------------------
# OCR functions
# ---------------------------------------------------------------------------


def read_text_at(
    frame: np.ndarray,
    x: int,
    y: int,
    color: int,
    max_chars: int = 30,
) -> str:
    """Read text at position (x, y) rendered in a specific color.

    Scans left-to-right, matching glyphs against pixels that equal
    *color*. Stops when no glyph matches or *max_chars* is reached.

    Args:
        frame: (128, 128) uint8 array.
        x: Starting x pixel coordinate.
        y: Starting y pixel coordinate.
        color: Palette index to match against (0-15).
        max_chars: Maximum characters to read.

    Returns:
        Recognized text string. May contain ambiguous chars (S/5, O/0);
        use normalize_text() or normalize_digits() for context-specific
        interpretation.
    """
    if y < 0 or y + GLYPH_H > SCREEN_HEIGHT:
        return ""

    result: list[str] = []
    cx = x

    for _ in range(max_chars):
        if cx + GLYPH_W > SCREEN_WIDTH:
            break

        # Check for space: 4 columns of no target-color pixels
        if _is_space(frame, cx, y, color):
            # Verify there's actual content after the space (not end of text).
            # Peek ahead: if no target-color pixel exists in the next
            # SPACE_WIDTH + GLYPH_W columns, we've hit end of text.
            peek_end = min(cx + SPACE_WIDTH + GLYPH_W, SCREEN_WIDTH)
            if peek_end > cx + SPACE_WIDTH:
                peek_region = frame[y:y + GLYPH_H, cx + SPACE_WIDTH:peek_end]
                if not np.any(peek_region == color):
                    break  # End of text, not a real space
            else:
                break
            result.append(" ")
            cx += SPACE_WIDTH
            continue

        # Try to match a glyph
        matched = _match_glyph(frame, cx, y, color)
        if matched is None:
            break

        result.append(matched)
        cx += CHAR_ADVANCE

    return "".join(result)


def read_text_any_color(
    frame: np.ndarray,
    x: int,
    y: int,
    max_chars: int = 30,
) -> tuple[str, int] | None:
    """Read text at (x, y) in whatever color is present there.

    Probes the pixel at (x, y) to determine the text color, then reads.

    Returns:
        (text, color) tuple, or None if no text found.
    """
    if x >= SCREEN_WIDTH or y >= SCREEN_HEIGHT:
        return None

    # Probe: find the first non-zero pixel in the glyph area
    probe_color = 0
    for dy in range(min(GLYPH_H, SCREEN_HEIGHT - y)):
        for dx in range(min(GLYPH_W, SCREEN_WIDTH - x)):
            c = int(frame[y + dy, x + dx])
            if c != 0:
                probe_color = c
                break
        if probe_color != 0:
            break

    if probe_color == 0:
        return None

    text = read_text_at(frame, x, y, probe_color, max_chars)
    if not text:
        return None
    return (text, probe_color)


def normalize_text(s: str) -> str:
    """Normalize OCR output for text interpretation.

    Previously converted 5->S and 0->O because those pairs were believed
    to be pixel-identical. The game actually renders distinct glyphs for
    S vs 5 and O vs 0, so this function is now a no-op. Retained for
    backward compatibility.
    """
    return s


def normalize_digits(s: str) -> str:
    """Normalize OCR output for numeric interpretation.

    Previously converted S->5 and O->0 because those pairs were believed
    to be pixel-identical. The game actually renders distinct glyphs, so
    this function is now a no-op. Retained for backward compatibility.
    """
    return s


def measure_text(text: str) -> int:
    """Compute the pixel width of rendered text (for centering calculations)."""
    w = 0
    for ch in text:
        if ch == " ":
            w += SPACE_WIDTH
        else:
            w += CHAR_ADVANCE
    return max(0, w - 1) if text else 0


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _is_space(frame: np.ndarray, x: int, y: int, color: int) -> bool:
    """Check if position x has a space (4 columns with no target color)."""
    if x + SPACE_WIDTH > SCREEN_WIDTH:
        return False

    region = frame[y:y + GLYPH_H, x:x + SPACE_WIDTH]
    return not np.any(region == color)


def _match_glyph(frame: np.ndarray, x: int, y: int, color: int) -> str | None:
    """Try to match a glyph at position (x, y) in the given color.

    Returns the character if matched, None otherwise.

    Scoring: combines on-pixel accuracy (glyph says on, pixel is color)
    with off-pixel accuracy (glyph says off, pixel is NOT color). Both
    must be high for a match. This discriminates between similar glyphs
    like 8/A, E/C, etc.
    """
    if x + GLYPH_W > SCREEN_WIDTH or y + GLYPH_H > SCREEN_HEIGHT:
        return None

    region = frame[y:y + GLYPH_H, x:x + GLYPH_W]
    color_mask = (region == color).astype(np.uint8)

    best_char: str | None = None
    best_score = 0.0
    threshold = 0.90

    for ch, glyph in _GLYPH_ARRAYS.items():
        on_pixels = int(glyph.sum())
        off_pixels = GLYPH_W * GLYPH_H - on_pixels
        if on_pixels == 0:
            continue

        # Hits: glyph on AND pixel is color
        hits = int((glyph & color_mask).sum())
        # Correct rejections: glyph off AND pixel is NOT color
        correct_off = int(((1 - glyph) & (1 - color_mask)).sum())

        # Score: weighted combination of on-accuracy and off-accuracy
        on_score = hits / on_pixels
        off_score = correct_off / off_pixels if off_pixels > 0 else 1.0

        # Both must be good. Use geometric mean for balanced scoring.
        score = (on_score * off_score) ** 0.5

        if score > best_score and score >= threshold:
            best_score = score
            best_char = ch

    return best_char
