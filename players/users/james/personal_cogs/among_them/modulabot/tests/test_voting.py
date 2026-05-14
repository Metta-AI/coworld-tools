"""Tests for :mod:`modulabot.voting` — parse half of the voting screen.

Layered roughly the same way the Nim parser is organised:

1. **Pure helpers** — grid layout math, chat-text normalisation and
   sus lookup, useful-line filter. Cheap unit tests with no sprites
   or frame painting.
2. **Pixel helpers** — slot / cursor / self-marker / vote-dot
   parsing. Use a synthetic-frame builder that renders player sprites
   where the parser expects them, then assert round-trips.
3. **Top-level parser** — :func:`parse_voting_screen` on a fully
   synthetic voting screen, plus a rejection test to guard the
   strict-invariant contract.

Every test builds its own frame from scratch — no fixture captures
yet, since we don't have real voting-screen frames in
``fixtures_frames.npy``. Add fixture-based integration tests as soon
as we capture a real meeting.
"""

from __future__ import annotations

import unittest

import numpy as np

from modulabot import ascii as ascii_mod
from modulabot import voting
from modulabot.data import (
    PLAYER_COLORS,
    SCREEN_HEIGHT,
    SCREEN_WIDTH,
    SPRITE_SIZE,
    load_reference_data,
)
from modulabot.state import Bot, Role, VoteChatLine, VoteSlot
from modulabot.voting import (
    MAX_PLAYERS,
    VOTE_BLACK_MARKER,
    VOTE_CELL_H,
    VOTE_CELL_W,
    VOTE_CHARS_PER_LINE,
    VOTE_CHAT_ICON_X,
    VOTE_CHAT_TEXT_X,
    VOTE_SKIP,
    VOTE_SKIP_W,
    VOTE_START_Y,
    VOTE_UNKNOWN,
    chat_sus_color_index,
    clear_voting_state,
    normalize_chat_text,
    parse_voting_candidate,
    parse_voting_screen,
    parse_vote_dots_for_target,
    parse_vote_slot,
    read_vote_chat_speakers,
    read_vote_chat_text,
    self_vote_choice,
    useful_chat_line,
    visible_chat_lines,
    vote_cell_origin,
    vote_cell_selected,
    vote_chat_speaker_at,
    vote_chat_speaker_for_line,
    vote_dot_color_index,
    vote_grid_layout,
    vote_self_marker_present,
    vote_skip_selected,
    vote_skip_text_matches,
    vote_slot_for_color,
    vote_target_name,
)


# ---------------------------------------------------------------------------
# Shared fixtures / helpers
# ---------------------------------------------------------------------------


_CURSOR_COLOR = 2


def _blank_frame() -> np.ndarray:
    return np.zeros((SCREEN_HEIGHT, SCREEN_WIDTH), dtype=np.uint8)


def _paint_crewmate(
    frame: np.ndarray, sprite, x: int, y: int, tint_palette_index: int
) -> None:
    """Paint the player sprite at ``(x, y)`` with a given tint colour.

    Mirrors the sprite-match semantics: TINT_COLOR pixels become
    ``tint_palette_index``, SHADE_TINT_COLOR pixels become its
    shadow, transparent pixels stay zero. Used by the slot tests to
    build a voting screen that will actually match
    :func:`parse_vote_slot`.
    """
    from modulabot.data import SHADOW_MAP, SHADE_TINT_COLOR, TINT_COLOR, TRANSPARENT_INDEX

    sh, sw = sprite.height, sprite.width
    for sy in range(sh):
        fy = y + sy
        if fy < 0 or fy >= SCREEN_HEIGHT:
            continue
        for sx in range(sw):
            fx = x + sx
            if fx < 0 or fx >= SCREEN_WIDTH:
                continue
            color = int(sprite.pixels[sy, sx])
            if color == TRANSPARENT_INDEX:
                continue
            if color == TINT_COLOR:
                frame[fy, fx] = tint_palette_index
            elif color == SHADE_TINT_COLOR:
                frame[fy, fx] = int(SHADOW_MAP[tint_palette_index & 0x0F])
            else:
                frame[fy, fx] = color


def _paint_text(frame: np.ndarray, font, text: str, x: int, y: int, color: int = 2) -> None:
    pen = x
    for ch in text:
        g = ascii_mod.glyph_at(font, ch)
        for gy in range(g.height):
            for gx in range(g.width):
                if g.pixels[gy, gx]:
                    yy = y + gy
                    xx = pen + gx
                    if 0 <= yy < SCREEN_HEIGHT and 0 <= xx < SCREEN_WIDTH:
                        frame[yy, xx] = color
        pen += ascii_mod.glyph_advance(font, ch)


def _paint_cell_cursor(frame: np.ndarray, count: int, index: int) -> None:
    """Draw the cursor outline rows around one cell so
    :func:`vote_cell_selected` returns True."""
    cx, cy = vote_cell_origin(count, index)
    frame[cy - 1, cx : cx + VOTE_CELL_W] = _CURSOR_COLOR
    frame[cy + VOTE_CELL_H - 2, cx : cx + VOTE_CELL_W] = _CURSOR_COLOR


def _paint_skip_cursor(frame: np.ndarray, skip_x: int, skip_y: int) -> None:
    frame[skip_y - 1, skip_x : skip_x + VOTE_SKIP_W] = _CURSOR_COLOR
    frame[skip_y + 6, skip_x : skip_x + VOTE_SKIP_W] = _CURSOR_COLOR


def _build_voting_frame(data, count: int, *, cursor_index: int | None = None) -> np.ndarray:
    """Paint a minimally-complete voting screen for ``count`` players.

    Slot ``i`` gets a player sprite tinted with ``PLAYER_COLORS[i]``;
    SKIP banner is painted below the last row; an optional cursor
    can be drawn around one cell or the skip region. Returns the
    frame ready for :func:`parse_voting_candidate`.
    """
    frame = _blank_frame()
    layout = vote_grid_layout(count)
    for i in range(count):
        cx, cy = vote_cell_origin(count, i)
        spx = cx + (VOTE_CELL_W - data.sprites.player.width) // 2
        spy = cy + 1
        _paint_crewmate(frame, data.sprites.player, spx, spy, int(PLAYER_COLORS[i]))
    _paint_text(frame, data.font, "SKIP", layout.skip_x, layout.skip_y, color=2)
    if cursor_index is not None:
        if cursor_index == count:
            _paint_skip_cursor(frame, layout.skip_x, layout.skip_y)
        elif 0 <= cursor_index < count:
            _paint_cell_cursor(frame, count, cursor_index)
    return frame


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


class GridLayoutTests(unittest.TestCase):
    def test_one_player(self):
        l = vote_grid_layout(1)
        self.assertEqual((l.cols, l.rows), (1, 1))
        self.assertEqual(l.start_x, (SCREEN_WIDTH - VOTE_CELL_W) // 2)

    def test_eight_players_is_single_row(self):
        l = vote_grid_layout(8)
        self.assertEqual((l.cols, l.rows), (8, 1))

    def test_nine_players_wraps_to_two_rows(self):
        l = vote_grid_layout(9)
        self.assertEqual((l.cols, l.rows), (8, 2))

    def test_sixteen_players_two_full_rows(self):
        l = vote_grid_layout(16)
        self.assertEqual((l.cols, l.rows), (8, 2))

    def test_cell_origin_derived_from_layout(self):
        # Slot 0 sits at (start_x, start_y).
        cx, cy = vote_cell_origin(8, 0)
        self.assertEqual(cx, vote_grid_layout(8).start_x)
        self.assertEqual(cy, VOTE_START_Y)
        # Slot 7 sits at the right edge of the first row.
        cx, cy = vote_cell_origin(8, 7)
        self.assertEqual(cx, vote_grid_layout(8).start_x + 7 * VOTE_CELL_W)


class NormalizeChatTextTests(unittest.TestCase):
    def test_lowercases(self):
        self.assertEqual(normalize_chat_text("RED IS SUS"), "red is sus")

    def test_collapses_punctuation_to_single_space(self):
        self.assertEqual(normalize_chat_text("red... is... sus!!"), "red is sus")

    def test_strips_leading_and_trailing_whitespace(self):
        self.assertEqual(normalize_chat_text("   red sus   "), "red sus")

    def test_preserves_digits(self):
        self.assertEqual(normalize_chat_text("player 12 sus"), "player 12 sus")


class UsefulChatLineTests(unittest.TestCase):
    def test_mostly_letters_is_useful(self):
        self.assertTrue(useful_chat_line("red is sus"))

    def test_two_letters_meets_bar(self):
        self.assertTrue(useful_chat_line("ab"))

    def test_one_letter_rejected(self):
        self.assertFalse(useful_chat_line("a"))

    def test_mostly_unknown_rejected(self):
        # 3 letters + 10 question marks -> more than half unknown.
        self.assertFalse(useful_chat_line("abc??????????"))


class ChatSusColorTests(unittest.TestCase):
    def test_simple_sus(self):
        # 6 = "blue" in PLAYER_COLOR_NAMES.
        self.assertEqual(chat_sus_color_index("blue is sus"), 6)

    def test_sus_then_color(self):
        self.assertEqual(chat_sus_color_index("sus green"), 13)

    def test_no_sus_returns_unknown(self):
        self.assertEqual(chat_sus_color_index("red vented"), VOTE_UNKNOWN)

    def test_prefers_longer_color_name(self):
        """'light blue sus' should resolve to light blue (3), not
        blue (6). This is the tiebreaker the imposter bandwagon
        policy depends on."""
        self.assertEqual(chat_sus_color_index("light blue is sus"), 3)

    def test_prefers_later_sus_mention(self):
        """When two sus calls exist, the later one wins so the most
        recent chat drives the vote. Matches the Nim tiebreak."""
        idx = chat_sus_color_index("red sus later green sus")
        self.assertEqual(idx, 13)  # green


class ClearVotingStateTests(unittest.TestCase):
    def test_clears_all_parsed_fields(self):
        bot = Bot(agent_id=0, role=Role.CREWMATE)
        bot.voting.active = True
        bot.voting.player_count = 5
        bot.voting.chat_text = "red sus"
        bot.voting.chat_sus_color = 0
        bot.voting.chat_lines = [VoteChatLine(speaker_color=6, y=70, text="hi")]
        bot.voting.slots = [VoteSlot(color_index=1, alive=True) for _ in range(5)]
        bot.voting.choices = [3] + [VOTE_UNKNOWN] * 15

        clear_voting_state(bot)

        self.assertFalse(bot.voting.active)
        self.assertEqual(bot.voting.player_count, 0)
        self.assertEqual(bot.voting.chat_text, "")
        self.assertEqual(bot.voting.chat_sus_color, VOTE_UNKNOWN)
        self.assertEqual(bot.voting.chat_lines, [])
        self.assertEqual(len(bot.voting.slots), MAX_PLAYERS)
        self.assertEqual(bot.voting.slots[0].color_index, VOTE_UNKNOWN)
        self.assertEqual(bot.voting.choices, [VOTE_UNKNOWN] * MAX_PLAYERS)


# ---------------------------------------------------------------------------
# Pixel helpers
# ---------------------------------------------------------------------------


class SlotParseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = load_reference_data()

    def test_parse_vote_slot_player_sprite(self):
        """Painting a player sprite at the slot position reads back
        as a live slot with the right colour index."""
        frame = _blank_frame()
        count = 4
        cx, cy = vote_cell_origin(count, 2)
        spx = cx + (VOTE_CELL_W - self.data.sprites.player.width) // 2
        spy = cy + 1
        _paint_crewmate(frame, self.data.sprites.player, spx, spy, int(PLAYER_COLORS[2]))
        slot = parse_vote_slot(frame, self.data.sprites, count, 2)
        self.assertEqual(slot.color_index, 2)
        self.assertTrue(slot.alive)

    def test_parse_vote_slot_missing_returns_unknown(self):
        """Blank slot → unknown colour."""
        frame = _blank_frame()
        slot = parse_vote_slot(frame, self.data.sprites, 4, 2)
        self.assertEqual(slot.color_index, VOTE_UNKNOWN)
        self.assertFalse(slot.alive)


class CursorTests(unittest.TestCase):
    def test_cell_cursor_detected(self):
        frame = _blank_frame()
        _paint_cell_cursor(frame, 4, 1)
        self.assertTrue(vote_cell_selected(frame, 4, 1))
        self.assertFalse(vote_cell_selected(frame, 4, 2))

    def test_skip_cursor_detected(self):
        frame = _blank_frame()
        layout = vote_grid_layout(4)
        _paint_skip_cursor(frame, layout.skip_x, layout.skip_y)
        self.assertTrue(vote_skip_selected(frame, layout.skip_x, layout.skip_y))


class SelfMarkerTests(unittest.TestCase):
    def test_coloured_marker(self):
        frame = _blank_frame()
        count = 4
        cx, cy = vote_cell_origin(count, 1)
        mx = cx + VOTE_CELL_W // 2 - 1
        my = cy - 2
        frame[my, mx] = int(PLAYER_COLORS[1])
        frame[my, mx + 1] = int(PLAYER_COLORS[1])
        self.assertTrue(vote_self_marker_present(frame, count, 1, 1))

    def test_black_marker_uses_cursor_colour(self):
        frame = _blank_frame()
        count = 4
        # Black is PLAYER_COLORS index 15 (palette 0).
        cx, cy = vote_cell_origin(count, 0)
        mx = cx + VOTE_CELL_W // 2 - 1
        my = cy - 2
        # Find the index of black in PLAYER_COLORS.
        black_idx = int(np.where(PLAYER_COLORS == 0)[0][0])
        frame[my, mx] = _CURSOR_COLOR
        frame[my, mx + 1] = VOTE_BLACK_MARKER
        self.assertTrue(vote_self_marker_present(frame, count, 0, black_idx))


class VoteDotTests(unittest.TestCase):
    def test_coloured_dot_resolves_to_palette_index(self):
        frame = _blank_frame()
        # Paint a red-tint dot at (10, 10) → red is palette index 3,
        # which is PLAYER_COLORS[0].
        frame[10, 10] = int(PLAYER_COLORS[0])
        self.assertEqual(vote_dot_color_index(frame, 10, 10), 0)

    def test_background_returns_unknown(self):
        frame = _blank_frame()
        self.assertEqual(vote_dot_color_index(frame, 10, 10), VOTE_UNKNOWN)

    def test_black_dot_uses_cursor_and_marker(self):
        frame = _blank_frame()
        frame[10, 9] = VOTE_BLACK_MARKER
        frame[10, 10] = _CURSOR_COLOR
        black_idx = int(np.where(PLAYER_COLORS == 0)[0][0])
        self.assertEqual(vote_dot_color_index(frame, 10, 10), black_idx)

    def test_parse_vote_dots_for_target_records_every_voter(self):
        frame = _blank_frame()
        # Paint two dots at offsets (0,0) and (2,0) → voters idx 0 and idx 1.
        frame[5, 3] = int(PLAYER_COLORS[0])  # red voter
        frame[5, 5] = int(PLAYER_COLORS[1])  # orange voter
        bot = Bot(agent_id=0, role=Role.CREWMATE)
        clear_voting_state(bot)
        parse_vote_dots_for_target(frame, bot, target=2, dot_x=3, dot_y=5)
        self.assertEqual(bot.voting.choices[0], 2)
        self.assertEqual(bot.voting.choices[1], 2)
        # Unpainted voter slots remain unknown.
        self.assertEqual(bot.voting.choices[2], VOTE_UNKNOWN)


# ---------------------------------------------------------------------------
# Chat OCR helpers
# ---------------------------------------------------------------------------


class ChatLineSpeakerTests(unittest.TestCase):
    def test_prefer_above_pip(self):
        speakers = [(60, 3), (80, 5)]
        # text_y = 70 → pip at y=60 (idx 3) is nearest above.
        self.assertEqual(vote_chat_speaker_for_line(speakers, 70), 3)

    def test_fallback_to_below_within_search(self):
        speakers = [(80, 5)]
        # text_y = 70 → no above, pip at y=80 is within search window.
        self.assertEqual(vote_chat_speaker_for_line(speakers, 70), 5)

    def test_too_far_returns_unknown(self):
        speakers = [(10, 3)]
        # text_y = 100 → pip above but >= SPEAKER_SEARCH distance away.
        self.assertEqual(vote_chat_speaker_for_line(speakers, 100), VOTE_UNKNOWN)


# ---------------------------------------------------------------------------
# Top-level integration
# ---------------------------------------------------------------------------


class ParseVotingScreenTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = load_reference_data()

    def test_happy_path_four_players(self):
        """A cleanly-drawn 4-player voting screen should parse, set
        the right player_count, populate all four slots with matching
        colours, and detect the cursor on the selected cell."""
        frame = _build_voting_frame(self.data, 4, cursor_index=1)
        bot = Bot(agent_id=0, role=Role.CREWMATE)
        ok = parse_voting_screen(bot, self.data.sprites, self.data.font, frame, tick=100)
        self.assertTrue(ok)
        self.assertTrue(bot.voting.active)
        self.assertEqual(bot.voting.player_count, 4)
        for i in range(4):
            self.assertEqual(bot.voting.slots[i].color_index, i)
            self.assertTrue(bot.voting.slots[i].alive)
        self.assertEqual(bot.voting.cursor, 1)
        self.assertEqual(bot.voting.start_tick, 100)

    def test_skip_cursor_produces_count_cursor(self):
        """Cursor at SKIP means ``cursor == player_count`` in the
        parsed state — mirrors the Nim convention that callers rely
        on for direction math."""
        frame = _build_voting_frame(self.data, 3, cursor_index=3)
        bot = Bot(agent_id=0, role=Role.CREWMATE)
        self.assertTrue(
            parse_voting_screen(bot, self.data.sprites, self.data.font, frame, tick=0)
        )
        self.assertEqual(bot.voting.cursor, 3)

    def test_non_voting_frame_rejected_and_state_cleared(self):
        """A frame without the SKIP banner and slot sprites must be
        rejected; leftover state from a previous meeting should be
        wiped so the next parse starts fresh."""
        bot = Bot(agent_id=0, role=Role.CREWMATE)
        clear_voting_state(bot)
        bot.voting.active = True
        bot.voting.player_count = 4
        bot.voting.chat_text = "stale"
        ok = parse_voting_screen(
            bot, self.data.sprites, self.data.font, _blank_frame(), tick=0
        )
        self.assertFalse(ok)
        self.assertFalse(bot.voting.active)
        self.assertEqual(bot.voting.player_count, 0)
        self.assertEqual(bot.voting.chat_text, "")

    def test_preserves_start_tick_across_reparse(self):
        """A parse re-run while already active keeps the first
        meeting tick so the decision policy's listen timer counts
        from meeting start, not the current frame."""
        frame = _build_voting_frame(self.data, 4, cursor_index=0)
        bot = Bot(agent_id=0, role=Role.CREWMATE)
        parse_voting_screen(bot, self.data.sprites, self.data.font, frame, tick=100)
        parse_voting_screen(bot, self.data.sprites, self.data.font, frame, tick=150)
        self.assertEqual(bot.voting.start_tick, 100)

    def test_chat_lines_carry_speaker_colours_end_to_end(self):
        """Integration: paint two chat pips + text lines at realistic
        spacing and confirm :func:`parse_voting_screen` populates
        ``chat_lines`` with the right ``speaker_color`` for each line.

        This is the test that proves the whole chain — pip sprite
        detection, text OCR, prefer-above pairing — composes
        correctly on a full voting frame rather than just working in
        isolation. The per-component unit tests
        (:class:`ChatLineSpeakerTests`) would all pass even if the
        top-level parser forgot to wire them together.
        """
        from modulabot.voting import VOTE_CHAT_ICON_X

        frame = _build_voting_frame(self.data, 4, cursor_index=0)
        layout = vote_grid_layout(4)
        chat_y = layout.skip_y + 10

        # Paint two pips + text lines. Pip sprite height is 12 so we
        # leave 4 rows of gap after each pip before the next one.
        _paint_crewmate(
            frame, self.data.sprites.player,
            VOTE_CHAT_ICON_X, chat_y + 1, int(PLAYER_COLORS[0]),
        )
        _paint_text(frame, self.data.font, "red is sus", VOTE_CHAT_TEXT_X, chat_y + 3, color=7)
        _paint_crewmate(
            frame, self.data.sprites.player,
            VOTE_CHAT_ICON_X, chat_y + 16, int(PLAYER_COLORS[1]),
        )
        _paint_text(frame, self.data.font, "i was in admin", VOTE_CHAT_TEXT_X, chat_y + 18, color=7)

        bot = Bot(agent_id=0, role=Role.CREWMATE)
        self.assertTrue(
            parse_voting_screen(bot, self.data.sprites, self.data.font, frame, tick=0)
        )
        self.assertEqual(len(bot.voting.chat_lines), 2)

        first, second = bot.voting.chat_lines
        self.assertEqual(first.text, "red is sus")
        self.assertEqual(first.speaker_color, 0)  # red
        self.assertEqual(second.text, "i was in admin")
        self.assertEqual(second.speaker_color, 1)  # orange

        # And the sus detector picked up "red is sus" via the
        # concatenated chat text.
        self.assertEqual(bot.voting.chat_sus_color, 0)


class LookupHelpersTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = load_reference_data()

    def test_vote_slot_for_color_and_target_name(self):
        frame = _build_voting_frame(self.data, 4, cursor_index=0)
        bot = Bot(agent_id=0, role=Role.CREWMATE)
        parse_voting_screen(bot, self.data.sprites, self.data.font, frame, tick=0)
        self.assertEqual(vote_slot_for_color(bot, 2), 2)
        self.assertEqual(vote_slot_for_color(bot, 99), VOTE_UNKNOWN)
        self.assertEqual(vote_target_name(bot, 0), "red")
        self.assertEqual(vote_target_name(bot, VOTE_SKIP), "skip")
        self.assertEqual(vote_target_name(bot, 99), "unknown")

    def test_self_vote_choice_returns_unknown_when_no_self(self):
        frame = _build_voting_frame(self.data, 4, cursor_index=0)
        bot = Bot(agent_id=0, role=Role.CREWMATE)
        parse_voting_screen(bot, self.data.sprites, self.data.font, frame, tick=0)
        # No self marker painted, so self_slot stays VOTE_UNKNOWN and
        # self_color on Identity is still -1.
        self.assertEqual(self_vote_choice(bot), VOTE_UNKNOWN)


if __name__ == "__main__":
    unittest.main()
