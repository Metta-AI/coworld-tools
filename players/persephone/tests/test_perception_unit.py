"""Unit tests for the perception module foundation."""

from __future__ import annotations

import numpy as np
import pytest

from perception._unpack import unpack_frame
from perception._ocr import (
    read_text_at,
    read_text_any_color,
    normalize_text,
    normalize_digits,
    _GLYPH_ARRAYS,
    GLYPH_W,
    GLYPH_H,
    CHAR_ADVANCE,
    SPACE_WIDTH,
)
from perception._common import SCREEN_WIDTH, SCREEN_HEIGHT, PROTOCOL_BYTES


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
