"""Tests for :mod:`modulabot.ascii`.

Three layers:

1. **Font loader invariants** — 95 glyphs, expected widths for a few
   known characters, background colour, glyph foreground pixel
   counts. Guard against silent upstream font regressions.
2. **Draw-and-read round trips** — render a phrase into a synthetic
   frame via the font bitmaps, then assert every reader primitive
   (:func:`text_matches`, :func:`find_text`, :func:`read_line`,
   :func:`read_run`, :func:`best_glyph`) reads it back exactly.
3. **Permissiveness & error budgets** — one-pixel corruption should
   fail exact matching but succeed under ``max_errors=1``; a total
   garbage frame should never claim a match.

No fixture-frame banner test yet — the captured ``fixtures_frames.npy``
doesn't contain text-heavy frames at a known position. Add one when we
have a voting-screen capture.
"""

from __future__ import annotations

import unittest

import numpy as np

from modulabot import ascii as ascii_mod
from modulabot.ascii import (
    best_glyph,
    find_text,
    glyph_advance,
    glyph_at,
    glyph_score,
    read_line,
    read_run,
    text_matches,
    text_score,
    text_width,
)
from modulabot.data import (
    FIRST_PRINTABLE_ASCII,
    PRINTABLE_ASCII_COUNT,
    SCREEN_HEIGHT,
    SCREEN_WIDTH,
    SPACE_COLOR,
    PixelFont,
    load_reference_data,
)


def _draw_text(
    frame: np.ndarray,
    font: PixelFont,
    text: str,
    x: int,
    y: int,
    color: int = 7,
) -> int:
    """Paint ``text`` into ``frame`` using ``color`` for foreground.

    Helper shared by the round-trip tests. Returns the final pen X so
    tests can assert layout invariants without re-running
    :func:`text_width`.
    """
    pen_x = x
    pen_y = y
    for ch in text:
        if ch == "\n":
            pen_x = x
            pen_y += font.height + font.spacing
            continue
        g = glyph_at(font, ch)
        if g.width <= 0:
            continue
        h = g.height
        w = g.width
        # Clip to frame bounds.
        for gy in range(h):
            yy = pen_y + gy
            if yy < 0 or yy >= SCREEN_HEIGHT:
                continue
            for gx in range(w):
                xx = pen_x + gx
                if xx < 0 or xx >= SCREEN_WIDTH:
                    continue
                if g.pixels[gy, gx]:
                    frame[yy, xx] = color
        pen_x += glyph_advance(font, ch)
    return pen_x


class FontLoaderTests(unittest.TestCase):
    """Pin invariants the upstream font loader has to maintain."""

    @classmethod
    def setUpClass(cls):
        cls.data = load_reference_data()
        cls.font = cls.data.font

    def test_has_printable_ascii_range(self):
        self.assertEqual(len(self.font.glyphs), PRINTABLE_ASCII_COUNT)

    def test_background_is_map_void_colour(self):
        # RGB 29, 43, 83 = BitWorld's MapVoidColor (palette index 12).
        self.assertEqual(self.font.background_rgba, (29, 43, 83, 255))

    def test_known_glyph_widths(self):
        """Pin a handful of glyph widths against the rendered PNG.

        If the upstream font changes, these break first — the
        expected values here are what we actually loaded on
        2026-04-30 from tiny5.aseprite. Update deliberately rather
        than silently on a font change.
        """
        widths = {ch: glyph_at(self.font, ch).width for ch in "ASKIP ? .0"}
        self.assertEqual(widths["A"], 4)
        self.assertEqual(widths["S"], 4)
        self.assertEqual(widths["K"], 4)
        self.assertEqual(widths["I"], 1)
        self.assertEqual(widths["P"], 4)
        self.assertEqual(widths[" "], 3)  # space is a 3px advance in tiny5
        self.assertEqual(widths["?"], 3)
        self.assertEqual(widths["."], 1)
        self.assertEqual(widths["0"], 3)

    def test_glyph_height_matches_font_height(self):
        for g in self.font.glyphs:
            self.assertEqual(g.height, self.font.height)

    def test_space_glyph_has_no_foreground(self):
        self.assertEqual(int(glyph_at(self.font, " ").pixels.sum()), 0)

    def test_spacing_default(self):
        self.assertEqual(self.font.spacing, 1)

    def test_text_width_sums_glyph_advances(self):
        # "SKIP" = 4 + 1 + 4 + 1 + 1 + 1 + 4 = 16? That's with 1px
        # spacing between each pair of non-zero-width glyphs.
        expected = 0
        for i, ch in enumerate("SKIP"):
            if i > 0:
                expected += self.font.spacing
            expected += glyph_at(self.font, ch).width
        self.assertEqual(text_width(self.font, "SKIP"), expected)


class ScalarOcrTests(unittest.TestCase):
    """Draw → read round trips for the main OCR primitives."""

    @classmethod
    def setUpClass(cls):
        cls.font = load_reference_data().font

    def _blank(self) -> np.ndarray:
        return np.full((SCREEN_HEIGHT, SCREEN_WIDTH), SPACE_COLOR, dtype=np.uint8)

    def test_text_matches_exact(self):
        frame = self._blank()
        _draw_text(frame, self.font, "SKIP", 32, 100)
        self.assertTrue(text_matches(frame, self.font, "SKIP", 32, 100))
        # Shift one pixel off — must fail at zero errors.
        self.assertFalse(text_matches(frame, self.font, "SKIP", 33, 100))

    def test_text_matches_empty_returns_false(self):
        """Empty string has no glyphs; matcher should refuse to claim
        a match anywhere."""
        frame = self._blank()
        self.assertFalse(text_matches(frame, self.font, "", 0, 0))

    def test_find_text_returns_first_rendered_position(self):
        frame = self._blank()
        _draw_text(frame, self.font, "CREWMATE", 16, 32)
        hit = find_text(frame, self.font, "CREWMATE")
        self.assertTrue(hit.found)
        self.assertEqual((hit.x, hit.y), (16, 32))

    def test_find_text_missing_returns_not_found(self):
        frame = self._blank()
        hit = find_text(frame, self.font, "CREWMATE")
        self.assertFalse(hit.found)

    def test_read_line_recovers_full_text(self):
        frame = self._blank()
        phrase = "VOTE NOW"
        _draw_text(frame, self.font, phrase, 10, 48)
        read = read_line(frame, self.font, 48)
        self.assertEqual(read, phrase)

    def test_read_line_empty_row_returns_empty_string(self):
        frame = self._blank()
        self.assertEqual(read_line(frame, self.font, 48), "")

    def test_read_line_handles_lowercase_leading_letter(self):
        """Lowercase letters like ``r`` / ``e`` / ``n`` have empty top
        rows; a naive first-column scan on the top pixel row would
        start reading mid-word at the first ascender (``d``'s
        top-right corner, etc.). Confirm our smarter
        multi-row scan handles this.
        """
        frame = self._blank()
        phrase = "red: i saw green do it"
        _draw_text(frame, self.font, phrase, 3, 40)
        self.assertEqual(read_line(frame, self.font, 40), phrase)

    def test_read_run_matches_written_count(self):
        frame = self._blank()
        _draw_text(frame, self.font, "ABC123", 4, 60)
        result = read_run(frame, self.font, 4, 60, 6)
        self.assertEqual(result, "ABC123")

    def test_best_glyph_picks_letter(self):
        frame = self._blank()
        _draw_text(frame, self.font, "S", 4, 4)
        self.assertEqual(best_glyph(frame, self.font, 4, 4), "S")

    def test_best_glyph_returns_question_on_garbage(self):
        frame = self._blank()
        # Paint a deliberately weird shape that no real glyph matches.
        frame[10:16, 10:16] = 8
        self.assertEqual(best_glyph(frame, self.font, 10, 10), "?")

    def test_text_matches_max_errors_tolerance(self):
        """One-pixel corruption: exact match fails but max_errors=1 succeeds.

        Guards against the budget semantics silently drifting. If
        misses vs. extras semantics ever flip this test breaks
        immediately.
        """
        frame = self._blank()
        _draw_text(frame, self.font, "SKIP", 32, 100)
        # Turn off one foreground pixel within the S glyph.
        frame[100, 33] = SPACE_COLOR
        self.assertFalse(text_matches(frame, self.font, "SKIP", 32, 100, max_errors=0))
        self.assertTrue(text_matches(frame, self.font, "SKIP", 32, 100, max_errors=1))

    def test_score_counts_misses_and_extras(self):
        frame = self._blank()
        _draw_text(frame, self.font, "A", 4, 4)
        # Corrupt one pixel: creates 1 miss.
        ay = 4
        # Find a foreground pixel we can stamp to background.
        g = glyph_at(self.font, "A")
        for gy in range(g.height):
            for gx in range(g.width):
                if g.pixels[gy, gx]:
                    frame[4 + gy, 4 + gx] = SPACE_COLOR
                    break
            else:
                continue
            break
        # Add a foreground pixel outside the glyph footprint: creates 1 extra.
        frame[4 + g.height - 1, 4 + g.width + 0] = 7
        s = text_score(frame, self.font, "A", 4, 4)
        self.assertGreaterEqual(s.misses, 1)
        self.assertGreaterEqual(s.extras, 1)


class BannerScenarioTests(unittest.TestCase):
    """Simulate the banner / SKIP detection pathway end-to-end.

    No captured banner frames yet, so we render synthetic ones that
    reproduce the same black-backdrop layout BitWorld uses during
    interstitials and voting. The goal: prove the primitives we need
    for the crewmate/voting policies (exact-position banner lookup,
    phrase sweep, voting-chat OCR) compose correctly.
    """

    @classmethod
    def setUpClass(cls):
        cls.font = load_reference_data().font

    def test_interstitial_banner_detection(self):
        """Render a ``CREWMATE`` banner centred on a black frame and
        confirm we can find it regardless of X position."""
        frame = np.full((SCREEN_HEIGHT, SCREEN_WIDTH), SPACE_COLOR, dtype=np.uint8)
        # Centre it vaguely — the finder should locate it.
        banner_x = (SCREEN_WIDTH - text_width(self.font, "CREWMATE")) // 2
        banner_y = SCREEN_HEIGHT // 2 - self.font.height // 2
        _draw_text(frame, self.font, "CREWMATE", banner_x, banner_y)
        hit = find_text(frame, self.font, "CREWMATE")
        self.assertTrue(hit.found, "expected CREWMATE banner to be findable")
        self.assertEqual((hit.x, hit.y), (banner_x, banner_y))

    def test_skip_detection_on_voting_screen(self):
        """Voting screen has a SKIP slot; exact-position match is how
        the voting policy decides whether the cursor is on it."""
        frame = np.full((SCREEN_HEIGHT, SCREEN_WIDTH), SPACE_COLOR, dtype=np.uint8)
        _draw_text(frame, self.font, "SKIP", 100, 110)
        self.assertTrue(text_matches(frame, self.font, "SKIP", 100, 110))
        self.assertFalse(text_matches(frame, self.font, "SKIP", 99, 110))

    def test_voting_chat_line_recovery(self):
        """OCR a realistic chat line back from a black-backed row —
        mirrors how the Nim voting parser consumes chat text."""
        frame = np.full((SCREEN_HEIGHT, SCREEN_WIDTH), SPACE_COLOR, dtype=np.uint8)
        phrase = "i was in admin"
        _draw_text(frame, self.font, phrase, 3, 80)
        # Spot check: readLine from row 80 recovers the whole phrase.
        self.assertEqual(read_line(frame, self.font, 80), phrase)


class PerformanceTests(unittest.TestCase):
    """Loose wall-clock guards. Not strict perf tests but enough to
    catch gross regressions (e.g. accidentally dropping vectorisation
    on find_text). Skip in CI if they end up flaky."""

    @classmethod
    def setUpClass(cls):
        cls.font = load_reference_data().font

    def test_find_text_worst_case_sweep(self):
        """Find a phrase that isn't there — the fullest possible sweep
        across the 128×128 frame. Should complete in well under
        100 ms even on a slow box."""
        import time

        frame = np.full((SCREEN_HEIGHT, SCREEN_WIDTH), SPACE_COLOR, dtype=np.uint8)
        # Warm-up once for any cache fill.
        find_text(frame, self.font, "NONEXISTENT")
        t0 = time.perf_counter()
        for _ in range(5):
            find_text(frame, self.font, "NONEXISTENT")
        elapsed_ms = (time.perf_counter() - t0) / 5 * 1000
        self.assertLess(
            elapsed_ms,
            100.0,
            f"find_text sweep regressed: {elapsed_ms:.1f} ms/call",
        )


if __name__ == "__main__":
    unittest.main()
