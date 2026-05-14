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
    BAR_Y,
    COLOR_HOSTAGE_CHECK,
    COLOR_HUD_ALERT,
    COLOR_HUD_DIM,
    COLOR_HUD_NORMAL,
    HOSTAGE_CELL_H,
    HOSTAGE_CELL_W,
    HOSTAGE_GRID_Y,
    PLAYER_H,
    PLAYER_W,
    PLAYER_COLORS,
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


def _render_role_card_frame() -> np.ndarray:
    """Render a synthetic RoleReveal panel 1 frame."""
    frame = np.zeros((SCREEN_HEIGHT, SCREEN_WIDTH), dtype=np.uint8)
    _draw_double_border(frame, 14)
    _draw_sprite(frame, PlayerShape.TRIANGLE, PLAYER_COLORS[2], 60, 8)
    _draw_centered_text(frame, "YOU ARE", 18, COLOR_HUD_NORMAL)
    _draw_centered_text(frame, "NYMPH", 28, 14)
    _draw_centered_text(frame, "NYMPHS TEAM", 38, 14)
    _draw_centered_text(frame, "ASSIGNED TO", 48, COLOR_HUD_DIM)
    _draw_centered_text(frame, "UNDERWORLD", 56, COLOR_HUD_NORMAL)
    _draw_centered_text(frame, "10P  120x120", 66, COLOR_HUD_DIM)
    _draw_centered_text(frame, "STARTING IN 7", 106, COLOR_HUD_NORMAL)
    return frame


def _render_role_summary_frame() -> np.ndarray:
    """Render a synthetic RoleReveal panel 2 frame."""
    frame = np.zeros((SCREEN_HEIGHT, SCREEN_WIDTH), dtype=np.uint8)
    _draw_double_border(frame, COLOR_HUD_NORMAL)
    _draw_centered_text(frame, "MATCH ROLES", 8, COLOR_HUD_NORMAL)
    _draw_text(frame, "HADES PERSEPHONE", 6, 20, COLOR_HUD_DIM)
    _draw_text(frame, "CERBERUS DEMETER", 6, 28, COLOR_HUD_DIM)
    _draw_centered_text(frame, "STARTING IN 7", 118, COLOR_HUD_NORMAL)
    return frame


def _render_role_summary_with_spy_echo_frame() -> np.ndarray:
    """Render a role summary with Spy, missing roles, and echo substitutions."""
    frame = np.zeros((SCREEN_HEIGHT, SCREEN_WIDTH), dtype=np.uint8)
    _draw_double_border(frame, COLOR_HUD_NORMAL)
    _draw_centered_text(frame, "MATCH ROLES", 8, COLOR_HUD_NORMAL)
    _draw_text(frame, "HADES SPY NYMPH", 6, 20, COLOR_HUD_DIM)
    _draw_text(frame, "MISSING:", 6, 32, COLOR_HUD_ALERT)
    _draw_text(frame, "CERBERUS DEMETER", 6, 40, COLOR_HUD_DIM)
    _draw_text(frame, "ECHO ACTIVE:", 6, 52, 11)
    _draw_text(frame, "ECHO OF HADES -> HADES", 6, 60, COLOR_HUD_DIM)
    _draw_centered_text(frame, "STARTING IN 7", 118, COLOR_HUD_NORMAL)
    return frame


def _render_round_schedule_frame() -> np.ndarray:
    """Render a synthetic RoleReveal panel 3 frame."""
    frame = np.zeros((SCREEN_HEIGHT, SCREEN_WIDTH), dtype=np.uint8)
    _draw_double_border(frame, COLOR_HUD_NORMAL)
    _draw_centered_text(frame, "ROUND SCHEDULE", 8, COLOR_HUD_NORMAL)
    _draw_text(frame, "ROUND  TIME  HOSTAGE", 10, 20, COLOR_HUD_DIM)
    _draw_text(frame, "  1      3:00     1", 10, 28, COLOR_HUD_NORMAL)
    _draw_text(frame, "  2      2:00     2", 10, 36, COLOR_HUD_NORMAL)
    _draw_text(frame, "  3      0:45     1", 10, 44, COLOR_HUD_NORMAL)
    _draw_centered_text(frame, "STARTING IN 7", 60, COLOR_HUD_NORMAL)
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

    def test_whisper_action_bar_overrides_round_clock(self):
        """Whisper menu frames still classify as whisper when header OCR is weak."""
        default_bar = np.zeros((SCREEN_HEIGHT, SCREEN_WIDTH), dtype=np.uint8)
        _draw_text(default_bar, "R1 0:14", 2, 2, COLOR_HUD_NORMAL)
        _draw_text(default_bar, "H/I:TAB L:EXIT K:ACT", 2, BAR_Y + 2, COLOR_HUD_DIM)

        menu = np.zeros((SCREEN_HEIGHT, SCREEN_WIDTH), dtype=np.uint8)
        _draw_text(menu, "R1 0:14", 2, 2, COLOR_HUD_NORMAL)
        _draw_text(menu, "(LEADER) GRANT", 2, BAR_Y + 2, COLOR_HUD_DIM)

        target_picker = np.zeros((SCREEN_HEIGHT, SCREEN_WIDTH), dtype=np.uint8)
        _draw_text(target_picker, "R1 0:14", 2, 2, COLOR_HUD_NORMAL)
        _draw_text(target_picker, "ROLE:", 2, BAR_Y + 2, COLOR_HUD_ALERT)

        assert detect_view(default_bar) == View.WHISPER
        assert detect_view(menu) == View.WHISPER
        assert detect_view(target_picker) == View.WHISPER

    def test_shout_view_title_and_bottom_bar_are_global_chat(self):
        """The shout surface also has a round clock and tab controls."""
        shout_title = np.zeros((SCREEN_HEIGHT, SCREEN_WIDTH), dtype=np.uint8)
        _draw_text(shout_title, "R1 0:14", 2, 2, COLOR_HUD_NORMAL)
        _draw_text(shout_title, "SHOUT", 42, 2, COLOR_HUD_NORMAL)
        _draw_text(
            shout_title,
            "H/I:TAB L:CLOSE K:NEXT",
            2,
            BAR_Y + 2,
            COLOR_HUD_DIM,
        )

        shout_bar = np.zeros((SCREEN_HEIGHT, SCREEN_WIDTH), dtype=np.uint8)
        _draw_text(shout_bar, "R1 0:14", 2, 2, COLOR_HUD_NORMAL)
        _draw_text(
            shout_bar,
            "H/I:TAB L:CLOSE K:NEXT",
            2,
            BAR_Y + 2,
            COLOR_HUD_DIM,
        )

        shout_conflict = np.zeros((SCREEN_HEIGHT, SCREEN_WIDTH), dtype=np.uint8)
        _draw_text(shout_conflict, "R1 0:14", 2, 2, COLOR_HUD_NORMAL)
        _draw_text(shout_conflict, "WHISP", 42, 2, COLOR_HUD_NORMAL)
        _draw_text(
            shout_conflict,
            "H/I:TAB L:CLOSE K:NEXT",
            2,
            BAR_Y + 2,
            COLOR_HUD_DIM,
        )

        assert detect_view(shout_title) == View.GLOBAL_CHAT
        assert detect_view(shout_bar) == View.GLOBAL_CHAT
        assert detect_view(shout_conflict) == View.GLOBAL_CHAT

    def test_spurious_whisp_title_does_not_override_playing_bar(self):
        """A weak title OCR hit is not enough without whisper controls."""
        frame = np.zeros((SCREEN_HEIGHT, SCREEN_WIDTH), dtype=np.uint8)
        _draw_text(frame, "R1 0:14", 2, 2, COLOR_HUD_NORMAL)
        _draw_text(frame, "WHISP", 42, 2, COLOR_HUD_NORMAL)
        _draw_text(frame, "J:NEW K:JOIN L:SHOUT", 2, BAR_Y + 2, COLOR_HUD_DIM)

        assert detect_view(frame) == View.PLAYING

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

    def test_overworld_detects_visible_nonbubble_sprite(self):
        """Plain visible sprites are exposed even without speech bubbles."""
        frame = np.zeros((SCREEN_HEIGHT, SCREEN_WIDTH), dtype=np.uint8)
        _draw_sprite(frame, PlayerShape.STAR, PLAYER_COLORS[4], 40, 40)

        result = parse_overworld(frame, view=View.PLAYING)

        assert len(result.visible_players) == 1
        player = result.visible_players[0]
        assert player.screen_x == 40
        assert player.screen_y == 40
        assert player.player_color == PLAYER_COLORS[4]
        assert player.player_shape == PlayerShape.STAR

    def test_overworld_visible_sprite_includes_role_indicator(self):
        """Visible sprite scanning attaches the role indicator when present."""
        frame = np.zeros((SCREEN_HEIGHT, SCREEN_WIDTH), dtype=np.uint8)
        _draw_sprite(frame, PlayerShape.CIRCLE, PLAYER_COLORS[0], 40, 40)
        # Hades indicator: Shades bar with center alert dots.
        frame[48:50, 41:46] = 3
        frame[48:50, 43] = 8

        result = parse_overworld(frame, view=View.PLAYING)

        assert len(result.visible_players) == 1
        indicator = result.visible_players[0].role_indicator
        assert indicator is not None
        assert indicator.team == "shades"
        assert indicator.role == "hades"

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


class TestRoleReveal:
    def test_parse_frame_classifies_role_card_panel(self):
        """Panel 1 is detected from the YOU ARE role-card anchor."""
        result = parse_frame(_render_role_card_frame())

        assert result.view == View.ROLE_REVEAL
        assert result.role_reveal is not None
        assert result.role_reveal.panel_index == 1
        assert result.role_reveal.role == "Nymph"
        assert result.role_reveal.team == "Nymphs"
        assert result.role_reveal.room == "Underworld"
        assert result.role_reveal.self_color == PLAYER_COLORS[2]
        assert result.role_reveal.self_shape == PlayerShape.TRIANGLE
        assert result.role_reveal.player_count == 10
        assert result.role_reveal.room_size == 120

    def test_role_card_self_color_prefers_exact_player_fill_over_shadow_alias(self):
        """Player colors that are also shadow colors still decode exactly."""
        frame = _render_role_card_frame()
        frame[8:8 + PLAYER_H, 60:60 + PLAYER_W] = 0
        _draw_sprite(frame, PlayerShape.CROSS, 9, 60, 8)

        result = parse_frame(frame)

        assert result.role_reveal is not None
        assert result.role_reveal.self_color == 9
        assert result.role_reveal.self_shape == PlayerShape.CROSS

    def test_parse_frame_classifies_role_summary_panel(self):
        """Panel 2 is detected from the MATCH ROLES summary header."""
        result = parse_frame(_render_role_summary_frame())

        assert result.view == View.ROLE_REVEAL
        assert result.role_reveal is not None
        assert result.role_reveal.panel_index == 2
        assert result.role_reveal.role is None
        assert result.role_reveal.room is None
        assert result.role_reveal.match_roles == [
            "Hades",
            "Persephone",
            "Cerberus",
            "Demeter",
        ]
        assert result.role_reveal.spy_in_game_config is False

    def test_parse_frame_parses_role_summary_spy_missing_and_echo(self):
        """Panel 2 exposes Spy presence, missing roles, and echo substitutions."""
        result = parse_frame(_render_role_summary_with_spy_echo_frame())

        assert result.view == View.ROLE_REVEAL
        assert result.role_reveal is not None
        assert result.role_reveal.panel_index == 2
        assert result.role_reveal.match_roles == ["Hades", "Spy", "Nymph"]
        assert result.role_reveal.missing_roles == ["Cerberus", "Demeter"]
        assert result.role_reveal.echo_substitutions == [
            ("Echo of Hades", "Hades")
        ]
        assert result.role_reveal.spy_in_game_config is True

    def test_parse_frame_classifies_round_schedule_panel(self):
        """Panel 3 is detected from the ROUND schedule headers."""
        result = parse_frame(_render_round_schedule_frame())

        assert result.view == View.ROLE_REVEAL
        assert result.role_reveal is not None
        assert result.role_reveal.panel_index == 3
        assert result.role_reveal.role is None
        assert result.role_reveal.room is None
        assert result.role_reveal.round_schedule == [(180, 1), (120, 2), (45, 1)]


# ---------------------------------------------------------------------------
# Chatroom message OCR (system messages)
# ---------------------------------------------------------------------------
#
# The bitworld renderer (rendering/renderer.ts) stacks whisper messages from
# the BOTTOM of the message area:
#
#   msgArea: x=0, y=10, w=128, h=108  (msgAreaBot = 118)
#   for showCount messages: y_top_first = msgAreaBot - showCount*lineH
#   each subsequent message is at y += lineH (lineH = 7)
#
# So one message lands at y=111, two messages at y=104 and y=111, etc.
# System messages are drawn in COLOR_HUD_ALERT (8) and most begin with a
# leading sender sprite (`pref(pi)` = "\x01<pi>" in sim.ts), which advances
# cx by PLAYER_W=7 before the text. With the rendered " " also = 4 px, the
# actual text starts at x=2 + PLAYER_W + SPACE_WIDTH = 13 even though the
# drawChatMsg call passes x=2.

from orpheus.perception._chatroom import parse_chatroom


_WHISPER_MSG_AREA_TOP = 10
_WHISPER_MSG_AREA_BOT = BAR_Y - 1  # 118
_WHISPER_LINE_H = 7
_TEXT_X_AFTER_LEADING_SPRITE = 2 + PLAYER_W + SPACE_WIDTH  # 13


def _row_y(slot_from_bottom: int) -> int:
    """Renderer's top-y for the slot-th message from the bottom (1 = bottom)."""
    return _WHISPER_MSG_AREA_BOT - slot_from_bottom * _WHISPER_LINE_H


class TestChatroomMessages:
    def test_parse_messages_finds_system_message_at_bottom_row(self):
        """A single system message is rendered at y=111. OCR must find it."""
        frame = np.zeros((SCREEN_HEIGHT, SCREEN_WIDTH), dtype=np.uint8)
        # Draw "OFFERED ROLE" at the bottom-most slot, after the sender-sprite
        # gap, in the alert color the renderer uses.
        _draw_text(
            frame,
            "OFFERED ROLE",
            _TEXT_X_AFTER_LEADING_SPRITE,
            _row_y(1),
            COLOR_HUD_ALERT,
        )

        result = parse_chatroom(frame)

        assert len(result.messages) == 1
        msg = result.messages[0]
        assert msg.is_system is True
        assert "OFFERED ROLE" in msg.text.upper()
        assert msg.y_position == _row_y(1)

    def test_parse_messages_finds_two_stacked_system_messages_chronologically(
        self,
    ):
        """Two messages render at y=104 (older) and y=111 (newer); OCR returns
        them in chronological order (oldest first)."""
        frame = np.zeros((SCREEN_HEIGHT, SCREEN_WIDTH), dtype=np.uint8)
        # Two messages stacked: showCount=2 -> y starts at msgAreaBot - 2*lineH
        # = 104, then increments by lineH to 111.
        _draw_text(frame, "GRANTED", _TEXT_X_AFTER_LEADING_SPRITE, _row_y(2), COLOR_HUD_ALERT)
        _draw_text(frame, "OFFERED COLOR", _TEXT_X_AFTER_LEADING_SPRITE, _row_y(1), COLOR_HUD_ALERT)

        result = parse_chatroom(frame)

        texts = [m.text.upper() for m in result.messages]
        assert any("GRANTED" in t for t in texts), texts
        assert any("OFFERED COLOR" in t for t in texts), texts
        # Chronological order: older (y=104) first, newer (y=111) second.
        granted_idx = next(i for i, t in enumerate(texts) if "GRANTED" in t)
        offered_idx = next(i for i, t in enumerate(texts) if "OFFERED COLOR" in t)
        assert granted_idx < offered_idx

    def test_parse_messages_handles_message_with_no_leading_sprite(self):
        """A few sysmsg templates ("ROLE XCHG: ...", "LEADER SUMMIT") have no
        leading sender sprite, so text begins at x=2 directly. Render this in
        the second-from-bottom slot so it doesn't collide with the pending
        entry detection region (which is exclusive of LEADER SUMMIT in the
        real game anyway -- the renderer fillRect-clears the bang row when
        a pending entry is shown)."""
        frame = np.zeros((SCREEN_HEIGHT, SCREEN_WIDTH), dtype=np.uint8)
        _draw_text(frame, "LEADER SUMMIT", 2, _row_y(2), COLOR_HUD_ALERT)

        result = parse_chatroom(frame)

        assert len(result.messages) >= 1
        assert any("LEADER SUMMIT" in m.text.upper() for m in result.messages)

    def test_parse_messages_skips_pending_entry_indicator_row(self):
        """When pending_entry is shown, the bottom slot at y=111 is the
        "WANTS IN" indicator (already extracted by _parse_pending_entry).
        OCR must not also append it as a chat message."""
        frame = np.zeros((SCREEN_HEIGHT, SCREEN_WIDTH), dtype=np.uint8)
        # Plant the pending-entry alert flag (color 8 in the indicator strip
        # at y=BAR_Y-9..BAR_Y-3, x=2..4) so _parse_pending_entry sets
        # has_pending_entry=True.
        for y in range(BAR_Y - 9, BAR_Y - 3):
            for x in range(2, 5):
                frame[y, x] = COLOR_HUD_ALERT
        # The pending indicator overlays the bottom row text "WANTS IN".
        _draw_text(frame, "WANTS IN", _TEXT_X_AFTER_LEADING_SPRITE, _row_y(1), COLOR_HUD_ALERT)
        # And there's an actual older system message above it.
        _draw_text(frame, "GRANTED", _TEXT_X_AFTER_LEADING_SPRITE, _row_y(2), COLOR_HUD_ALERT)

        result = parse_chatroom(frame)

        assert result.has_pending_entry is True
        texts = [m.text.upper() for m in result.messages]
        assert any("GRANTED" in t for t in texts), texts
        # WANTS IN belongs to the indicator, not the message log.
        assert not any("WANTS IN" in t for t in texts), texts

    def test_parse_messages_returns_empty_when_message_area_blank(self):
        """An empty whisper view (no chat yet) produces no messages."""
        frame = np.zeros((SCREEN_HEIGHT, SCREEN_WIDTH), dtype=np.uint8)

        result = parse_chatroom(frame)

        assert result.messages == []
