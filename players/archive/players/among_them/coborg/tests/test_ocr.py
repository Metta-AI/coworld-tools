"""Unit tests for :mod:`players.among_them.coborg.perception.ocr`.

Whole-fixture parity against the Nim oracle is covered by
``tests/test_perception_parity.py`` (via ``run_parity``). This file
focuses on the public-API contract and hand-crafted edge cases the
fixture set doesn't exercise."""

from __future__ import annotations

from pathlib import Path

import numpy as np

from players.among_them.coborg.perception.data import (
    FIRST_PRINTABLE_ASCII,
    SPACE_COLOR,
    load_font,
)
from players.among_them.coborg.perception.frame import (
    SCREEN_HEIGHT,
    SCREEN_WIDTH,
)
from players.among_them.coborg.perception.interstitial import InterstitialKind
from players.among_them.coborg.perception.ocr import (
    GlyphMatch,
    _glyph_preference,
    _packed_font,
    best_glyph,
    classify_interstitial,
    find_text,
    read_line_strict,
    read_run,
    text_matches,
)

_FIXTURES_DIR = (
    Path(__file__).resolve().parent.parent / "perception/parity/fixtures"
)


def _empty_frame() -> np.ndarray:
    return np.full((SCREEN_HEIGHT, SCREEN_WIDTH), SPACE_COLOR, dtype=np.uint8)


def _stamp_text(frame: np.ndarray, text: str, x: int, y: int, color: int = 7) -> None:
    """Render ``text`` into ``frame`` at ``(x, y)`` using the tiny5 font.
    Glyph 'on' pixels become ``color``; off pixels stay as
    ``SPACE_COLOR``. Helper for synthetic OCR tests."""
    font = load_font()
    pen_x = x
    for ch in text:
        if ch == "\n":
            pen_x = x
            y += font.height + font.spacing
            continue
        glyph = font.glyph(ch)
        h, w = glyph.shape
        for sy in range(h):
            for sx in range(w):
                if glyph[sy, sx]:
                    fy, fx = y + sy, pen_x + sx
                    if 0 <= fy < SCREEN_HEIGHT and 0 <= fx < SCREEN_WIDTH:
                        frame[fy, fx] = color
        pen_x += w + font.spacing


# --- public API: glyph preference ----------------------------------------


def test_glyph_preference_ordering():
    """Upstream rule: lowercase > digit > uppercase > space > other."""
    assert _glyph_preference("a") == 4
    assert _glyph_preference("z") == 4
    assert _glyph_preference("0") == 3
    assert _glyph_preference("9") == 3
    assert _glyph_preference("A") == 2
    assert _glyph_preference("Z") == 2
    assert _glyph_preference(" ") == 1
    assert _glyph_preference("!") == 0
    assert _glyph_preference("?") == 0


# --- public API: packed-font cache ---------------------------------------


def test_packed_font_is_cached():
    pf1 = _packed_font()
    pf2 = _packed_font()
    assert pf1 is pf2
    # Sanity-check shape against the loaded font.
    font = load_font()
    assert pf1.height == font.height
    assert pf1.spacing == font.spacing
    assert pf1.expected.shape[0] == 95
    assert pf1.col_mask.shape == (95, pf1.patch_width)


def test_packed_font_tensors_are_read_only():
    pf = _packed_font()
    assert not pf.expected.flags.writeable
    assert not pf.col_mask.flags.writeable
    assert not pf.opaque.flags.writeable
    assert not pf.preferences.flags.writeable


# --- public API: best_glyph ----------------------------------------------


def test_best_glyph_on_empty_frame_returns_space():
    """An all-background frame should match the space glyph cleanly
    (space has zero opaque pixels but width > 0). The match has
    errors == 0."""
    frame = _empty_frame()
    match = best_glyph(frame, 5, 5, max_errors=0)
    assert match.char == " "
    assert match.errors == 0
    assert match.advance > 0


def test_best_glyph_returns_failure_sentinel_when_no_match():
    """When the frame has noise nothing can match, the upstream
    sentinel rules report ``('?', max_errors + 1, 0)`` rather than
    the true minimum error count."""
    frame = _empty_frame()
    # Stamp solid noise (every pixel "on") so no glyph clears
    # max_errors=0 — every off-pixel in the glyph is a miss.
    frame[3:9, 1:6] = 7
    match = best_glyph(frame, 1, 3, max_errors=0)
    assert match.char == "?"
    assert match.errors == 1  # max_errors + 1 sentinel
    assert match.advance == 0


def test_best_glyph_recognises_synthetic_letter():
    """Stamp the letter 'A' onto a blank frame and verify best_glyph
    recovers it."""
    frame = _empty_frame()
    _stamp_text(frame, "A", x=10, y=10)
    match = best_glyph(frame, 10, 10, max_errors=0)
    assert match.char == "A"
    assert match.errors == 0


# --- public API: text_matches --------------------------------------------


def test_text_matches_empty_text_is_false():
    """text_matches on the empty string returns False (the upstream
    ``opaque > 0`` predicate forbids it)."""
    assert not text_matches(_empty_frame(), "", 0, 0)


def test_text_matches_stamped_text_succeeds():
    frame = _empty_frame()
    _stamp_text(frame, "HELLO", x=20, y=40)
    assert text_matches(frame, "HELLO", 20, 40, max_errors=0)


def test_text_matches_wrong_position_fails():
    frame = _empty_frame()
    _stamp_text(frame, "HELLO", x=20, y=40)
    # Same text, off by one pixel — should miss with max_errors=0.
    assert not text_matches(frame, "HELLO", 21, 40, max_errors=0)


def test_text_matches_with_newline_resets_pen_x():
    frame = _empty_frame()
    _stamp_text(frame, "AB\nCD", x=10, y=10)
    assert text_matches(frame, "AB\nCD", 10, 10, max_errors=0)


# --- public API: read_run ------------------------------------------------


def test_read_run_reads_stamped_string():
    frame = _empty_frame()
    _stamp_text(frame, "Skeld", x=10, y=20)
    out = read_run(frame, 10, 20, count=5)
    assert out == "Skeld"


def test_read_run_strips_whitespace_by_default():
    frame = _empty_frame()
    _stamp_text(frame, "ab", x=20, y=20)
    # Read 5 glyphs; positions 2..4 are blank space.
    out = read_run(frame, 20, 20, count=5)
    assert out == "ab"


def test_read_run_no_strip_preserves_spaces():
    frame = _empty_frame()
    _stamp_text(frame, "ab", x=20, y=20)
    out = read_run(frame, 20, 20, count=5, strip=False)
    # Trailing spaces are part of the run when strip=False.
    assert out.startswith("ab")
    assert out.endswith(" ")


# --- public API: read_line_strict ----------------------------------------


def test_read_line_strict_empty_row_returns_empty_string():
    assert read_line_strict(_empty_frame(), 10) == ""


def test_read_line_strict_finds_text_on_row():
    """read_line_strict assumes the leading glyph has at least one
    on-pixel in column 0 of its top row (otherwise the row-scan starts
    at an interior column and the strict match misses). 'H' satisfies
    that — its row 0 column 0 is on (`#..#`). Use 'HA' to avoid the
    `I` / `l` tie-break (the tiny5 vertical bar matches both, and the
    tie-break prefers lowercase)."""
    frame = _empty_frame()
    _stamp_text(frame, "HA", x=30, y=15)
    out = read_line_strict(frame, 15)
    assert out.startswith("HA"), f"got {out!r}"


def test_read_line_strict_skips_when_lead_glyph_starts_with_offpixel():
    """Documents the upstream convention: a leading glyph like 'G'
    (top row `.###`) defeats read_line_strict because the row scan
    locks onto col 31 while the strict match expects col 30. This is
    not a bug — callers know which text to expect at the row they
    target. The test pins the behavior so a future refactor doesn't
    silently change it."""
    frame = _empty_frame()
    _stamp_text(frame, "GO", x=30, y=15)
    out = read_line_strict(frame, 15)
    # The leading '?' surfaces because the strict match at col 31
    # mismatches every glyph at the budget.
    assert not out.startswith("GO")


# --- public API: find_text -----------------------------------------------


def test_find_text_locates_stamped_banner():
    frame = _empty_frame()
    _stamp_text(frame, "IMPS", x=48, y=60)
    found, x, y = find_text(frame, "IMPS")
    assert found
    assert (x, y) == (48, 60)


def test_find_text_returns_false_when_missing():
    frame = _empty_frame()
    found, x, y = find_text(frame, "CREW WINS")
    assert not found
    assert (x, y) == (0, 0)


def test_find_text_empty_text_is_false():
    """Mirrors upstream: empty banner can't match."""
    found, _, _ = find_text(_empty_frame(), "")
    assert not found


# --- public API: classify_interstitial -----------------------------------


def test_classify_interstitial_empty_frame_is_unknown():
    """An all-background frame matches none of the banners and doesn't
    trigger the game-over layout heuristic."""
    kind = classify_interstitial(_empty_frame())
    assert kind is InterstitialKind.UNKNOWN


def test_classify_interstitial_stamped_imps_banner():
    frame = _empty_frame()
    _stamp_text(frame, "IMPS", x=48, y=60)
    kind = classify_interstitial(frame)
    assert kind is InterstitialKind.ROLE_REVEAL_IMPOSTER


def test_classify_interstitial_stamped_crew_wins_beats_crewmate():
    """Banner order matters — 'CREW WINS' is checked before 'CREWMATE'
    so a frame containing both must classify as game_over, not as
    role-reveal-crewmate. The upstream invariant we're mirroring."""
    frame = _empty_frame()
    _stamp_text(frame, "CREW WINS", x=20, y=60)
    kind = classify_interstitial(frame)
    assert kind is InterstitialKind.GAME_OVER


def test_classify_interstitial_real_gameover_fixture_uses_heuristic():
    """`gameover_crew_wins_real` renders the title in the server's 7px
    ASCII font, which doesn't OCR with the tiny5 6px font. The
    ``_looks_like_game_over_summary`` layout heuristic catches it."""
    raw = (_FIXTURES_DIR / "gameover_crew_wins_real.bin").read_bytes()
    frame = np.frombuffer(raw, dtype=np.uint8).reshape(SCREEN_HEIGHT, SCREEN_WIDTH)
    kind = classify_interstitial(frame)
    assert kind is InterstitialKind.GAME_OVER


# --- GlyphMatch shape ----------------------------------------------------


def test_glyph_match_is_namedtuple():
    m = GlyphMatch(char="x", errors=0, advance=5)
    # Both attribute access and positional unpacking work.
    assert m.char == "x"
    assert m.errors == 0
    assert m.advance == 5
    ch, err, adv = m
    assert (ch, err, adv) == ("x", 0, 5)


# --- printable ASCII coverage in packed font ----------------------------


def test_every_printable_ascii_is_at_correct_atlas_index():
    font = load_font()
    # Sanity: each of the 95 indices corresponds to chr(32+i).
    for i in range(95):
        ch = chr(FIRST_PRINTABLE_ASCII + i)
        # The font.glyph() round-trip should select the same glyph.
        assert font.glyph(ch).shape[1] == int(font.widths[i])
