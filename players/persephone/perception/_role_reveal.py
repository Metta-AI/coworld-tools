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
from ._ocr import read_text_at
from .types import RoleRevealPerception


_ROLE_NAMES_UPPER = [r.upper() for r in ROLE_NAMES]
_TEAM_NAMES_UPPER = [TEAM_A_NAME.upper(), TEAM_B_NAME.upper()]
_ROOM_NAMES_UPPER = [ROOM_A_NAME.upper(), ROOM_B_NAME.upper()]


def parse_role_reveal(frame: np.ndarray) -> RoleRevealPerception:
    """Extract role, team, room, and game info from the role reveal screen.

    Uses "YOU ARE" as a y-position anchor, then extracts fields at
    known offsets relative to that anchor. This matches the game's
    sequential top-to-bottom text rendering.

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

    # Find "YOU ARE" anchor to establish base y position.
    # The TS renderer places it at varying y depending on content.
    base_y = _find_anchor(frame)
    if base_y is None:
        return result

    # Role name: baseY + 10, in team color (border_color)
    role_text = _scan_centered(frame, base_y + 10, border_color)
    if role_text:
        result.role = _match_role_name(role_text)

    # Room name: baseY + 32..42, in color 2
    for offset in [38, 36, 34, 40, 42, 32]:
        room_text = _scan_centered(frame, base_y + offset, COLOR_HUD_NORMAL)
        if room_text:
            matched = _match_room_name(room_text)
            if matched:
                result.room = matched
                break

    # Info line: baseY + 44..52, in color 1: "{n}P  {w}x{h}"
    # The player count and room size may be separated by a gap wider than
    # the OCR's space detection. Scan for each part independently.
    for offset in [48, 46, 44, 50, 52]:
        y = base_y + offset
        if y < 0 or y + 5 > 128:
            continue
        for x in range(0, SCREEN_WIDTH - 10):
            text = read_text_at(frame, x, y, COLOR_HUD_DIM, 20)
            if not text:
                continue
            # Try full pattern first (works if gap is narrow)
            m = re.match(r"(\d+)P\s+(\d+)[Xx](\d+)", text)
            if m:
                result.player_count = int(m.group(1))
                result.room_size = int(m.group(2))
                break
            # Try just player count: "{n}P"
            m = re.match(r"(\d+)P$", text.strip())
            if m and result.player_count is None:
                result.player_count = int(m.group(1))
                continue
            # Try just room size: "{w}X{h}" or "{w}x{h}"
            m = re.match(r"(\d+)[Xx](\d+)", text.strip())
            if m and result.room_size is None:
                result.room_size = int(m.group(1))
                break
        if result.player_count is not None or result.room_size is not None:
            break

    # Countdown: scan lower region for "STARTING IN {n}" in color 2
    for y in range(base_y + 80, base_y + 100):
        if y >= 128:
            break
        countdown_text = _scan_centered(frame, y, COLOR_HUD_NORMAL)
        if countdown_text and "IN" in countdown_text:
            m = re.search(r"(\d+)$", countdown_text.strip())
            if m:
                result.countdown_secs = int(m.group(1))
            break

    return result


def _find_anchor(frame: np.ndarray) -> int | None:
    """Find the y position of the 'YOU ARE' anchor text.

    Tries multiple candidate y values. Returns the y where 'YOU ARE'
    is found in color 2, or None if not found.
    """
    for base_y in [18, 8, 12, 14, 16, 20, 22]:
        text = _scan_centered(frame, base_y, COLOR_HUD_NORMAL)
        if text and "YOU" in text.upper() and "ARE" in text.upper():
            return base_y
    return None


def _scan_centered(frame: np.ndarray, y: int, color: int) -> str | None:
    """Scan for centered text at a given y position.

    Scans x from 0 to SCREEN_WIDTH in steps of 1 to avoid missing text
    that starts at odd pixel offsets. Requires at least 3 characters to
    filter out noise from stray pixels.
    """
    if y < 0 or y + 5 > 128:
        return None
    for x in range(0, SCREEN_WIDTH - 6):
        text = read_text_at(frame, x, y, color, 20)
        if text and len(text.strip()) >= 3:
            return text.strip()
    return None


def _match_role_name(text: str) -> str | None:
    """Match OCR'd text against known role names."""
    norm = text.upper().replace(" ", "")
    for i, upper in enumerate(_ROLE_NAMES_UPPER):
        if norm.startswith(upper.replace(" ", "")):
            return ROLE_NAMES[i]
    return text  # Return raw if no match (better than None)


def _match_room_name(text: str) -> str | None:
    """Match OCR'd text against known room names."""
    norm = text.upper().replace(" ", "")
    if "UNDERWORLD" in norm:
        return ROOM_A_NAME
    if "MORTAL" in norm:
        return ROOM_B_NAME
    return None
