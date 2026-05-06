"""View detection: determine which game view is displayed in a frame.

Detection order resolves ambiguities between views that share visual
elements (e.g., role reveal vs info screen both have colored borders).
"""

from __future__ import annotations

import re

import numpy as np

from ._common import (
    BAR_Y,
    COLOR_HUD_ALERT,
    COLOR_HUD_DIM,
    COLOR_HUD_NORMAL,
    SCREEN_HEIGHT,
    SCREEN_WIDTH,
)
from ._ocr import GLYPH_H, normalize_text, read_text_at
from .types import View


_COLOR_ROOM_B_HEADER = 11


def detect_view(frame: np.ndarray) -> View:
    """Determine which view/phase is displayed in a frame.

    Args:
        frame: (128, 128) uint8 array of palette indices.

    Returns:
        The detected View enum value.
    """
    # Step 1: Check for double border (role reveal / info screen)
    border0 = int(frame[0, 0])
    border2 = int(frame[2, 2])

    if border0 != 0 and border0 == border2:
        inner = int(frame[4, 4])
        if inner == 0:
            if border0 == COLOR_HUD_NORMAL:
                if _row_contains_any(frame, 6, COLOR_HUD_NORMAL, ("PLAYER", "ROSTER")):
                    return View.ROSTER_REVEAL
                if _has_roster_column_headers(frame):
                    return View.ROSTER_REVEAL
            return View.ROLE_REVEAL  # Black interior = intro screen
        else:
            return View.INFO_SCREEN  # Non-black interior = info view

    # Step 2: Read text at (2, 2) in color 2 (normal HUD color)
    hud_text_2 = read_text_at(frame, 2, 2, COLOR_HUD_NORMAL, 20)
    hud_norm_2 = normalize_text(hud_text_2)

    # Whisper: "WHISP" at (2, 2) in color 2
    # Whispers are private chatrooms between two players.
    if hud_norm_2.startswith("WHISP"):
        return View.WHISPER

    # Info screen shared mode: "KNOWN PLAYERS" header
    if hud_norm_2.startswith("KNOWN"):
        return View.INFO_SCREEN

    # Step 3: Check bottom bar for "WAITING" (chatroom entry pending)
    bar_text_8 = read_text_at(frame, 2, BAR_Y + 2, COLOR_HUD_ALERT, 10)
    bar_norm_8 = normalize_text(bar_text_8)
    if bar_norm_8.startswith("WAITING"):
        return View.WAITING_ENTRY

    # Step 4: Continue with text at (2, 2) in color 2
    # Playing: "R{n} M:SS"
    if hud_norm_2 and hud_norm_2[0] == "R" and ":" in hud_norm_2:
        return View.PLAYING

    # Lobby: "{count}/{max}" pattern (digits and /)
    if hud_text_2 and re.match(r"\d+/\d+", hud_text_2):
        return View.LOBBY

    # Reveal: "REVEAL!"
    if hud_norm_2.startswith("REVEAL"):
        return View.REVEAL

    # Step 5: Read text at (2, 2) in color 8 (alert color)
    hud_text_8 = read_text_at(frame, 2, 2, COLOR_HUD_ALERT, 12)
    hud_norm_8 = normalize_text(hud_text_8)

    if hud_norm_8.startswith("SELECT"):
        return View.HOSTAGE_SELECT
    if hud_norm_8.startswith("EXCHANGING"):
        return View.HOSTAGE_EXCHANGE

    # Step 5b: Hostage exchange (centered "HOSTAGE EXCHANGE" at y=14, color 8)
    # The exchange screen renders this title centered, not at x=2.
    for x in range(20, 50):
        exchange_text = read_text_at(frame, x, 14, COLOR_HUD_ALERT, 20)
        if exchange_text and "HOSTAGE" in exchange_text:
            return View.HOSTAGE_EXCHANGE

    # Step 6: Check for non-leader hostage select ("PICK" in dim text)
    hud_text_1 = read_text_at(frame, 2, 2, COLOR_HUD_DIM, 20)
    hud_norm_1 = normalize_text(hud_text_1)
    if "PICK" in hud_norm_1:
        return View.HOSTAGE_SELECT

    # Step 7: Global chat detection ("{RoomName} CHAT" or "{RoomName} SHOUT")
    # The text at (2,2) in color 2 would be e.g. "Underworld CHAT" or
    # "Underworld SHOUT" depending on game version/config.
    if len(hud_norm_2) > 4 and (
        hud_norm_2.endswith("CHAT") or hud_norm_2.endswith("SHOUT")
    ):
        return View.GLOBAL_CHAT

    # Step 7.5: Leader summit ("LEADERS MEET" in dim text)
    if hud_norm_1.startswith("LEADERS"):
        return View.LEADER_SUMMIT

    # Step 8: Game over (win text at y=60, centered)
    # Text may be centered anywhere on the row, so scan multiple x offsets.
    for color in [3, 14, 1]:  # TeamA, TeamB, draw
        for x_start in [0, 20, 30, 40, 50]:
            win_text = read_text_at(frame, x_start, 60, color, 20)
            if win_text and ("WIN" in win_text or "ONE" in win_text):
                return View.GAME_OVER

    # Step 9: Fallback
    return View.UNKNOWN


def _has_roster_column_headers(frame: np.ndarray) -> bool:
    """Return True if the intro roster room headers are visible."""
    has_underworld = _row_contains_any(
        frame,
        17,
        COLOR_HUD_ALERT,
        ("UNDERWORLD", "UNDER"),
        max_chars=12,
    )
    has_mortal = _row_contains_any(
        frame,
        17,
        _COLOR_ROOM_B_HEADER,
        ("MORTAL", "REALM"),
        max_chars=14,
    )
    return has_underworld and has_mortal


def _row_contains_any(
    frame: np.ndarray,
    y: int,
    color: int,
    needles: tuple[str, ...],
    max_chars: int = 16,
) -> bool:
    """Scan a text row for any expected OCR substring."""
    if y < 0 or y + GLYPH_H > SCREEN_HEIGHT:
        return False

    upper_needles = tuple(n.upper() for n in needles)
    for x in range(4, SCREEN_WIDTH - 6):
        text = read_text_at(frame, x, y, color, max_chars)
        if not text:
            continue
        norm = normalize_text(text).strip().upper()
        if any(needle in norm for needle in upper_needles):
            return True
    return False
