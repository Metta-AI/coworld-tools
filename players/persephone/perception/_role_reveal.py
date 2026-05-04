"""Role reveal screen parser."""

from __future__ import annotations

import re

import numpy as np

from ._common import (
    COLOR_HUD_DIM,
    COLOR_HUD_NORMAL,
    ROLE_NAMES,
    ROOM_A_NAME,
    ROOM_B_NAME,
    SCREEN_WIDTH,
    TEAM_A_NAME,
    TEAM_B_NAME,
)
from ._ocr import normalize_digits, normalize_text, read_text_at
from .types import RoleRevealPerception


_ROLE_NAMES_UPPER = [r.upper() for r in ROLE_NAMES]
_TEAM_NAMES_UPPER = [TEAM_A_NAME.upper(), TEAM_B_NAME.upper()]
_ROOM_NAMES_UPPER = [ROOM_A_NAME.upper(), ROOM_B_NAME.upper()]


def parse_role_reveal(frame: np.ndarray) -> RoleRevealPerception:
    """Extract role, team, room, and game info from the role reveal screen.

    Args:
        frame: (128, 128) uint8 pixel array.

    Returns:
        RoleRevealPerception with all detected fields.
    """
    result = RoleRevealPerception()

    # Border color is the team color
    border_color = int(frame[0, 0])
    result.team_color = border_color

    # Team assignment from border color
    if border_color == 3:
        result.team = TEAM_A_NAME
    elif border_color == 14:
        result.team = TEAM_B_NAME

    # Scan for role name at y=18 in border color (centered)
    role_text = _scan_centered(frame, 18, border_color)
    if role_text:
        result.role = _match_role_name(role_text)

    # Scan for room name at y=46 in color 2 (centered)
    room_text = _scan_centered(frame, 46, COLOR_HUD_NORMAL)
    if room_text:
        result.room = _match_room_name(room_text)

    # Scan for info line at y=56 in color 1: "{n}P  {w}x{h}"
    info_text = _scan_centered(frame, 56, COLOR_HUD_DIM)
    if info_text:
        digits = normalize_digits(info_text)
        m = re.match(r"(\d+)P\s+(\d+)[Xx](\d+)", digits)
        if m:
            result.player_count = int(m.group(1))
            result.room_size = int(m.group(2))

    # Scan for countdown at y ~100 in color 2: "STARTING IN {n}"
    for y in range(96, 110):
        countdown_text = _scan_centered(frame, y, COLOR_HUD_NORMAL)
        if countdown_text and "IN" in normalize_text(countdown_text):
            digits = normalize_digits(countdown_text)
            m = re.search(r"(\d+)$", digits.strip())
            if m:
                result.countdown_secs = int(m.group(1))
            break

    return result


def _scan_centered(frame: np.ndarray, y: int, color: int) -> str | None:
    """Scan for centered text at a given y position.

    Tries multiple x offsets to find where the text starts.
    """
    for x in range(0, SCREEN_WIDTH - 10, 2):
        text = read_text_at(frame, x, y, color, 20)
        if text and len(text.strip()) >= 2:
            return text.strip()
    return None


def _match_role_name(text: str) -> str | None:
    """Match OCR'd text against known role names."""
    norm = normalize_text(text).upper().replace(" ", "")
    for i, upper in enumerate(_ROLE_NAMES_UPPER):
        if norm.startswith(upper.replace(" ", "")):
            return ROLE_NAMES[i]
    return text  # Return raw if no match (better than None)


def _match_room_name(text: str) -> str | None:
    """Match OCR'd text against known room names."""
    norm = normalize_text(text).upper().replace(" ", "")
    if "UNDERWORLD" in norm:
        return ROOM_A_NAME
    if "MORTAL" in norm:
        return ROOM_B_NAME
    return text
