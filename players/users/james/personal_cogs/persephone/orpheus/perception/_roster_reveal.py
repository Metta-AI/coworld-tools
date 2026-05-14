"""Roster reveal screen parser."""

from __future__ import annotations

import re

import numpy as np

from ._common import (
    COLOR_HUD_ALERT,
    COLOR_HUD_DIM,
    COLOR_HUD_NORMAL,
    PLAYER_COLORS,
    PLAYER_H,
    PLAYER_W,
    ROOM_A_NAME,
    ROOM_B_NAME,
    SCREEN_HEIGHT,
    SCREEN_WIDTH,
)
from ._ocr import GLYPH_H, normalize_text, read_text_at
from ._sprites import detect_sprite_shape, read_sprite
from .types import Room, RosterEntry, RosterRevealPerception


_COLOR_ROOM_B_HEADER = 11
_LEFT_COLUMN_X = 5
_RIGHT_COLUMN_X = 67
_HEADER_Y = 17
_FIRST_ENTRY_Y = 25
_ENTRY_STRIDE = 15
_LABEL_X_OFFSET = 9
_COUNTDOWN_Y_MIN = SCREEN_HEIGHT - 14
_COUNTDOWN_Y_MAX = SCREEN_HEIGHT - 6


def parse_roster_reveal(frame: np.ndarray) -> RosterRevealPerception:
    """Extract player room assignments from the roster reveal screen.

    Args:
        frame: (128, 128) uint8 pixel array.

    Returns:
        RosterRevealPerception with detected player entries and countdown.
    """
    result = RosterRevealPerception()

    headers_match = _headers_match(frame)
    result.players.extend(_scan_column(frame, _LEFT_COLUMN_X, Room.UNDERWORLD))
    result.players.extend(_scan_column(frame, _RIGHT_COLUMN_X, Room.MORTAL_REALM))

    if headers_match or result.players:
        result.countdown_secs = _read_countdown(frame)

    return result


def _headers_match(frame: np.ndarray) -> bool:
    """Read the static room headers and confirm the roster layout."""
    underworld = read_text_at(
        frame,
        _LEFT_COLUMN_X,
        _HEADER_Y,
        COLOR_HUD_ALERT,
        max_chars=len(ROOM_A_NAME) + 2,
    )
    mortal = read_text_at(
        frame,
        _RIGHT_COLUMN_X,
        _HEADER_Y,
        _COLOR_ROOM_B_HEADER,
        max_chars=len(ROOM_B_NAME) + 2,
    )

    underworld_norm = normalize_text(underworld).upper().replace(" ", "")
    mortal_norm = normalize_text(mortal).upper().replace(" ", "")
    return "UNDERWORLD" in underworld_norm and "MORTALREALM" in mortal_norm


def _scan_column(frame: np.ndarray, x: int, room: Room) -> list[RosterEntry]:
    """Scan one roster column for player sprites and labels."""
    entries: list[RosterEntry] = []

    for y in range(_FIRST_ENTRY_Y, SCREEN_HEIGHT - 2 * PLAYER_H, _ENTRY_STRIDE):
        color, shape = read_sprite(frame, x, y)
        if shape is None:
            shape = detect_sprite_shape(frame, x, y)
        if color is None:
            color = _read_dominant_player_color(frame, x, y)

        if color is None and shape is None:
            break
        if color is None:
            continue

        label = _read_label(frame, x + _LABEL_X_OFFSET, y + 1)
        entries.append(RosterEntry(color=color, shape=shape, room=room, label=label))

    return entries


def _read_dominant_player_color(frame: np.ndarray, x: int, y: int) -> int | None:
    """Read fill color from a sprite region when the center pixel is not fill."""
    if x < 0 or y < 0 or x + PLAYER_W > SCREEN_WIDTH or y + PLAYER_H > SCREEN_HEIGHT:
        return None

    region = frame[y : y + PLAYER_H, x : x + PLAYER_W]
    best_color: int | None = None
    best_count = 0

    for color in PLAYER_COLORS:
        count = int(np.count_nonzero(region == color))
        if count > best_count:
            best_color = color
            best_count = count

    return best_color if best_count > 0 else None


def _read_label(frame: np.ndarray, x: int, y: int) -> str | None:
    """Read the compact color/shape label beside a roster sprite."""
    text = read_text_at(frame, x, y, COLOR_HUD_DIM, max_chars=8)
    label = normalize_text(text).strip()
    return label or None


def _read_countdown(frame: np.ndarray) -> int | None:
    """Read the bottom 'NEXT IN {secs}' countdown."""
    for y in range(_COUNTDOWN_Y_MIN, _COUNTDOWN_Y_MAX + 1):
        if y < 0 or y + GLYPH_H > SCREEN_HEIGHT:
            continue
        for x in range(4, SCREEN_WIDTH - 6):
            text = read_text_at(frame, x, y, COLOR_HUD_NORMAL, max_chars=16)
            norm = normalize_text(text).strip().upper()
            if "NEXT" not in norm or "IN" not in norm:
                continue
            match = re.search(r"(\d+)\s*$", norm)
            if match:
                return int(match.group(1))
    return None
