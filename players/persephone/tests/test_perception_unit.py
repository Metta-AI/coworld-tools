"""Unit tests for the perception module foundation."""

from __future__ import annotations

import numpy as np
import pytest

from orpheus.perception import parse_frame
from orpheus.perception._bubbles import scan_speech_bubbles
from orpheus.perception._detect import detect_view
from orpheus.perception._hostage_grid import parse_hostage_grid
from orpheus.perception._overworld import parse_overworld
from orpheus.perception._unpack import unpack_frame
from orpheus.perception._ocr import (
    read_text_at,
    read_text_any_color,
    normalize_text,
    normalize_digits,
    _GLYPH_ARRAYS,
    GLYPH_W,
    GLYPH_H,
    CHAR_ADVANCE,
    SPACE_WIDTH,
    measure_text,
)
from orpheus.perception._common import (
    COLOR_HOSTAGE_CHECK,
    COLOR_HUD_ALERT,
    COLOR_HUD_DIM,
    COLOR_HUD_NORMAL,
    HOSTAGE_CELL_H,
    HOSTAGE_CELL_W,
    HOSTAGE_GRID_Y,
    PLAYER_H,
    PLAYER_W,
    SCREEN_WIDTH,
    SCREEN_HEIGHT,
    PROTOCOL_BYTES,
)
from orpheus.perception._sprites import _RAW_TEMPLATES
from orpheus.perception.types import PlayerShape, Room, View


# ---------------------------------------------------------------------------
# _unpack tests
# ---------------------------------------------------------------------------


class TestUnpack:
    def test_basic_unpack(self):
        """Verify low/high nibble extraction."""
        # Byte 0xAB -> low nibble = 0xB, high nibble = 0xA
        data = bytes([0xAB]) + bytes(PROTOCOL_BYTES - 1)
        frame = unpack_frame(data)
        assert frame[0, 0] == 0x0B  # low nibble
        assert frame[0, 1] == 0x0A  # high nibble

    def test_shape(self):
        """Output shape is (128, 128)."""
        data = bytes(PROTOCOL_BYTES)
        frame = unpack_frame(data)
        assert frame.shape == (SCREEN_HEIGHT, SCREEN_WIDTH)
        assert frame.dtype == np.uint8

    def test_all_zeros(self):
        """All-zero input produces all-zero output."""
        data = bytes(PROTOCOL_BYTES)
        frame = unpack_frame(data)
        assert np.all(frame == 0)

    def test_all_ones(self):
        """0xFF bytes produce all-15 pixels."""
        data = bytes([0xFF] * PROTOCOL_BYTES)
        frame = unpack_frame(data)
        assert np.all(frame == 15)

    def test_wrong_size_raises(self):
        """Non-8192-byte input raises ValueError."""
        with pytest.raises(ValueError):
            unpack_frame(bytes(100))

    def test_round_trip_values(self):
        """Specific pixel values survive pack/unpack."""
        # Pack: pixel pairs (3, 7), (0, 15), (1, 2)
        packed = bytes([0x73, 0xF0, 0x21]) + bytes(PROTOCOL_BYTES - 3)
        frame = unpack_frame(packed)
        assert frame[0, 0] == 3
        assert frame[0, 1] == 7
        assert frame[0, 2] == 0
        assert frame[0, 3] == 15
        assert frame[0, 4] == 1
        assert frame[0, 5] == 2


# ---------------------------------------------------------------------------
# _ocr tests
# ---------------------------------------------------------------------------


def _render_text(text: str, x: int, y: int, color: int) -> np.ndarray:
    """Render text into a blank frame using the same font as the game."""
    frame = np.zeros((SCREEN_HEIGHT, SCREEN_WIDTH), dtype=np.uint8)
    cx = x
    for ch in text:
        if ch == " ":
            cx += SPACE_WIDTH
            continue
        glyph = _GLYPH_ARRAYS.get(ch.upper()) or _GLYPH_ARRAYS.get(ch)
        if glyph is None:
            continue
        for dy in range(GLYPH_H):
            for dx in range(GLYPH_W):
                if glyph[dy, dx]:
                    if cy := y + dy < SCREEN_HEIGHT and cx + dx < SCREEN_WIDTH:
                        frame[y + dy, cx + dx] = color
        cx += CHAR_ADVANCE
    return frame


def _render_text_safe(text: str, x: int, y: int, color: int) -> np.ndarray:
    """Render text into a frame, handling bounds correctly."""
    frame = np.zeros((SCREEN_HEIGHT, SCREEN_WIDTH), dtype=np.uint8)
    cx = x
    for ch in text:
        if ch == " ":
            cx += SPACE_WIDTH
            continue
        upper = ch.upper()
        glyph = _GLYPH_ARRAYS.get(upper) if upper != ch else _GLYPH_ARRAYS.get(ch)
        if glyph is None:
            glyph = _GLYPH_ARRAYS.get(upper)
        if glyph is None:
            continue
        for dy in range(GLYPH_H):
            for dx in range(GLYPH_W):
                if glyph[dy, dx]:
                    py, px = y + dy, cx + dx
                    if 0 <= py < SCREEN_HEIGHT and 0 <= px < SCREEN_WIDTH:
                        frame[py, px] = color
        cx += CHAR_ADVANCE
    return frame


def _draw_text(frame: np.ndarray, text: str, x: int, y: int, color: int) -> None:
    """Draw text into an existing frame."""
    rendered = _render_text_safe(text, x, y, color)
    mask = rendered != 0
    frame[mask] = rendered[mask]


def _draw_centered_text(frame: np.ndarray, text: str, y: int, color: int) -> None:
    """Draw centered text into an existing frame."""
    x = (SCREEN_WIDTH - measure_text(text)) // 2
    _draw_text(frame, text, x, y, color)


def _draw_double_border(frame: np.ndarray, color: int) -> None:
    """Draw the intro-screen double border."""
    frame[0, :] = color
    frame[-1, :] = color
    frame[:, 0] = color
    frame[:, -1] = color
    frame[2, 2:-2] = color
    frame[-3, 2:-2] = color
    frame[2:-2, 2] = color
    frame[2:-2, -3] = color


def _draw_sprite(
    frame: np.ndarray,
    shape: PlayerShape,
    color: int,
    x: int,
    y: int,
) -> None:
    """Draw a player sprite into an existing frame."""
    template = _RAW_TEMPLATES[shape]
    for dy in range(PLAYER_H):
        for dx in range(PLAYER_W):
            value = template[dy][dx]
            if value == 2:
                frame[y + dy, x + dx] = color
            elif value == 1:
                frame[y + dy, x + dx] = 1


def _draw_rect(
    frame: np.ndarray,
    x: int,
    y: int,
    w: int,
    h: int,
    color: int,
) -> None:
    """Draw a 1px rectangle outline into an existing frame."""
    frame[y, x:x + w] = color
    frame[y + h - 1, x:x + w] = color
    frame[y:y + h, x] = color
    frame[y:y + h, x + w - 1] = color


def _render_roster_reveal_frame() -> np.ndarray:
    """Render a synthetic roster reveal frame."""
    frame = np.zeros((SCREEN_HEIGHT, SCREEN_WIDTH), dtype=np.uint8)
    _draw_double_border(frame, 2)
    _draw_centered_text(frame, "PLAYER ROSTER", 6, 2)
    _draw_text(frame, "UNDERWORLD", 5, 17, 8)
    _draw_text(frame, "MORTAL REALM", 67, 17, 11)

    left_entries = [
        (3, PlayerShape.CIRCLE, "R.CRCL"),
        (8, PlayerShape.RING, "Y.RING"),
    ]
    right_entries = [
        (14, PlayerShape.SQUARE, "B.SQR"),
        (10, PlayerShape.TRIANGLE, "G.TRI"),
    ]

    for idx, (color, shape, label) in enumerate(left_entries):
        y = 25 + idx * 15
        _draw_sprite(frame, shape, color, 5, y)
        _draw_text(frame, label, 14, y + 1, 1)

    for idx, (color, shape, label) in enumerate(right_entries):
        y = 25 + idx * 15
        _draw_sprite(frame, shape, color, 67, y)
        _draw_text(frame, label, 76, y + 1, 1)

    _draw_centered_text(frame, "NEXT IN 7", 118, 2)
    return frame


def _render_hostage_grid_frame() -> np.ndarray:
    """Render a synthetic leader hostage-select frame with a 3-column grid."""
    frame = np.zeros((SCREEN_HEIGHT, SCREEN_WIDTH), dtype=np.uint8)
    _draw_text(frame, "R1 0:14", 2, 2, COLOR_HUD_NORMAL)
    _draw_text(frame, "SELECT 14S", 42, 2, COLOR_HUD_ALERT)

    cols = 3
    grid_w = cols * HOSTAGE_CELL_W
    grid_x = (SCREEN_WIDTH - grid_w) // 2
    entries = [
        (3, PlayerShape.CIRCLE),
        (14, PlayerShape.SQUARE),
        (8, PlayerShape.TRIANGLE),
    ]

    for index, (color, shape) in enumerate(entries):
        cell_x = grid_x + index * HOSTAGE_CELL_W
        cell_y = HOSTAGE_GRID_Y
        sprite_x = cell_x + (HOSTAGE_CELL_W - PLAYER_W) // 2
        sprite_y = cell_y + 1
        _draw_sprite(frame, shape, color, sprite_x, sprite_y)

    # Cursor on the second eligible player.
    _draw_rect(
        frame,
        grid_x + HOSTAGE_CELL_W,
        HOSTAGE_GRID_Y,
        HOSTAGE_CELL_W,
        HOSTAGE_CELL_H,
        COLOR_HUD_NORMAL,
    )

    # Green checkmark probe on the third eligible player.
    selected_cell_x = grid_x + 2 * HOSTAGE_CELL_W
    frame[HOSTAGE_GRID_Y + 1, selected_cell_x + HOSTAGE_CELL_W - 3] = (
        COLOR_HOSTAGE_CHECK
    )

    _draw_text(frame, "1/2 HOSTAGES", grid_x, HOSTAGE_GRID_Y + HOSTAGE_CELL_H + 2, 2)
    return frame


class TestPerceptionBugFixes:
    def test_speech_bubble_sprite_y_uses_renderer_offset(self):
        """Speech bubbles map back to sprite top-left with y+4."""
        frame = np.zeros((SCREEN_HEIGHT, SCREEN_WIDTH), dtype=np.uint8)
        sprite_x, sprite_y = 30, 30
        bubble_x, bubble_y = sprite_x - 3, sprite_y - 4
        _draw_sprite(frame, PlayerShape.CIRCLE, 3, sprite_x, sprite_y)
        frame[bubble_y, bubble_x:bubble_x + 3] = 2
        frame[bubble_y + 1, bubble_x:bubble_x + 3] = 2
        frame[bubble_y + 2, bubble_x + 3] = 2

        bubbles = scan_speech_bubbles(frame)

        assert len(bubbles) == 1
        assert bubbles[0].screen_x == sprite_x
        assert bubbles[0].screen_y == sprite_y

    def test_detects_phase_labels_at_x42_before_round_clock(self):
        """Summit/hostage labels at x=42 are not masked by the round clock."""
        summit = np.zeros((SCREEN_HEIGHT, SCREEN_WIDTH), dtype=np.uint8)
        _draw_text(summit, "R1 0:14", 2, 2, COLOR_HUD_NORMAL)
        _draw_text(summit, "SUMMIT 14S", 42, 2, COLOR_HUD_ALERT)
        assert detect_view(summit) == View.LEADER_SUMMIT

        leaders = np.zeros((SCREEN_HEIGHT, SCREEN_WIDTH), dtype=np.uint8)
        _draw_text(leaders, "R1 0:14", 2, 2, COLOR_HUD_NORMAL)
        _draw_text(leaders, "LEADERS MEET 14S", 42, 2, COLOR_HUD_DIM)
        assert detect_view(leaders) == View.LEADER_SUMMIT

        hostage = _render_hostage_grid_frame()
        assert detect_view(hostage) == View.HOSTAGE_SELECT

    def test_role_leader_suffix_is_stripped(self):
        """A leader star suffix is separated from the role name."""
        frame = np.zeros((SCREEN_HEIGHT, SCREEN_WIDTH), dtype=np.uint8)
        role = "CERBER*"
        role_x = SCREEN_WIDTH - 20 - 4 - measure_text(role)
        _draw_text(frame, role, role_x, 2, 3)

        result = parse_overworld(frame, view=View.PLAYING)

        assert result.role_name == "CERBER"
        assert result.role_team_color == 3
        assert result.is_leader is True

    def test_hostage_grid_parser_reads_entries_selection_and_cursor(self):
        """The hostage grid parser mirrors the centered 12x14 cell layout."""
        frame = _render_hostage_grid_frame()

        grid = parse_hostage_grid(frame)

        assert grid is not None
        assert grid.eligible_colors == [3, 14, 8]
        assert grid.eligible_shapes == [
            PlayerShape.CIRCLE,
            PlayerShape.SQUARE,
            PlayerShape.TRIANGLE,
        ]
        assert grid.selected_positions == [2]
        assert grid.selected_colors == [8]
        assert grid.cursor_index == 1
        assert grid.count_label == "1/2 HOSTAGES"

    def test_parse_frame_populates_hostage_grid_for_hostage_select(self):
        """HOSTAGE_SELECT frames expose the parsed grid on overworld output."""
        result = parse_frame(_render_hostage_grid_frame())

        assert result.view == View.HOSTAGE_SELECT
        assert result.overworld is not None
        assert result.overworld.hostage_grid is not None
        assert result.overworld.hostage_grid.eligible_colors == [3, 14, 8]


class TestOCR:
    def test_read_single_char(self):
        """Read a single character."""
        frame = _render_text_safe("A", 2, 2, 2)
        result = read_text_at(frame, 2, 2, 2)
        assert result == "A"

    def test_read_word(self):
        """Read a multi-character word."""
        frame = _render_text_safe("CHAT", 2, 2, 2)
        result = read_text_at(frame, 2, 2, 2)
        assert normalize_text(result) == "CHAT"

    def test_read_with_space(self):
        """Read text containing a space."""
        frame = _render_text_safe("R1 0:15", 2, 2, 2)
        result = read_text_at(frame, 2, 2, 2)
        # Due to O/0 ambiguity, either form is acceptable
        normalized = normalize_digits(result)
        assert "R1" in normalized
        assert ":15" in normalized or ":1" in normalized

    def test_wrong_color_returns_empty(self):
        """Reading in wrong color returns empty string."""
        frame = _render_text_safe("HELLO", 2, 2, 8)
        result = read_text_at(frame, 2, 2, 3)  # Wrong color
        assert result == ""

    def test_read_text_any_color(self):
        """read_text_any_color detects color automatically."""
        frame = _render_text_safe("TEST", 10, 10, 14)
        result = read_text_any_color(frame, 10, 10)
        assert result is not None
        text, color = result
        assert normalize_text(text) == "TEST"
        assert color == 14

    def test_empty_frame_returns_empty(self):
        """Empty frame returns empty string."""
        frame = np.zeros((SCREEN_HEIGHT, SCREEN_WIDTH), dtype=np.uint8)
        result = read_text_at(frame, 0, 0, 2)
        assert result == ""

    def test_normalize_text(self):
        """normalize_text is now a no-op (S/5 and O/0 are distinct glyphs)."""
        assert normalize_text("5ELECT") == "5ELECT"
        assert normalize_text("R00M") == "R00M"
        assert normalize_text("SELECT") == "SELECT"

    def test_normalize_digits(self):
        """normalize_digits is now a no-op (S/5 and O/0 are distinct glyphs)."""
        assert normalize_digits("10:05") == "10:05"
        assert normalize_digits("1O:OS") == "1O:OS"

    def test_s_and_5_are_distinct(self):
        """S and 5 produce different glyph patterns (not ambiguous)."""
        frame_s = _render_text_safe("S", 2, 2, 2)
        frame_5 = _render_text_safe("5", 2, 2, 2)
        # The game renders distinct glyphs for S and 5.
        assert not np.array_equal(frame_s, frame_5)

    def test_o_and_0_are_distinct(self):
        """O and 0 produce different glyph patterns (not ambiguous)."""
        frame_o = _render_text_safe("O", 2, 2, 2)
        frame_0 = _render_text_safe("0", 2, 2, 2)
        # The game renders distinct glyphs for O and 0.
        assert not np.array_equal(frame_o, frame_0)

    def test_numbers(self):
        """Read numeric text."""
        frame = _render_text_safe("128", 2, 2, 2)
        result = read_text_at(frame, 2, 2, 2)
        normalized = normalize_digits(result)
        assert normalized == "128"


# ---------------------------------------------------------------------------
# Roster reveal tests
# ---------------------------------------------------------------------------


class TestRosterReveal:
    def test_detects_roster_reveal(self):
        """Double-border roster screen is not misclassified as role reveal."""
        frame = _render_roster_reveal_frame()

        assert detect_view(frame) == View.ROSTER_REVEAL

    def test_parse_frame_extracts_roster_entries(self):
        """Roster parser extracts player color, shape, room, label, countdown."""
        frame = _render_roster_reveal_frame()

        result = parse_frame(frame)

        assert result.view == View.ROSTER_REVEAL
        assert result.roster_reveal is not None
        assert result.roster_reveal.countdown_secs == 7

        players = result.roster_reveal.players
        assert len(players) == 4
        assert [(p.color, p.shape, p.room, p.label) for p in players] == [
            (3, PlayerShape.CIRCLE, Room.UNDERWORLD, "R.CRCL"),
            (8, PlayerShape.RING, Room.UNDERWORLD, "Y.RING"),
            (14, PlayerShape.SQUARE, Room.MORTAL_REALM, "B.SQR"),
            (10, PlayerShape.TRIANGLE, Room.MORTAL_REALM, "G.TRI"),
        ]
