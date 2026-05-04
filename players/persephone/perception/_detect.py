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
from ._ocr import normalize_text, read_text_at
from .types import View


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
            return View.ROLE_REVEAL  # Black interior = intro screen
        else:
            return View.INFO_SCREEN  # Non-black interior = info view

    # Step 2: Read text at (2, 2) in color 2 (normal HUD color)
    hud_text_2 = read_text_at(frame, 2, 2, COLOR_HUD_NORMAL, 20)
    hud_norm_2 = normalize_text(hud_text_2)

    # Chatroom: "CHAT" at (2, 2) in color 2
    if hud_norm_2.startswith("CHAT"):
        return View.CHATROOM

    # Step 3: Check bottom bar for "WAITING" (chatroom entry pending)
    bar_text_8 = read_text_at(frame, 2, BAR_Y + 2, COLOR_HUD_ALERT, 10)
    bar_norm_8 = normalize_text(bar_text_8)
    if bar_norm_8.startswith("WAITING"):
        return View.WAITING_ENTRY

    # Step 4: Continue with text at (2, 2) in color 2
    # Playing: "R{n} M:SS"
    if hud_norm_2 and hud_norm_2[0] == "R" and ":" in hud_norm_2:
        return View.PLAYING

    # Lobby: "{count}/{max}" pattern
    if hud_text_2 and re.match(r"[0-9OSos]+/[0-9OSos]+", hud_text_2):
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

    # Step 6: Check for non-leader hostage select ("PICK" in dim text)
    hud_text_1 = read_text_at(frame, 2, 2, COLOR_HUD_DIM, 20)
    hud_norm_1 = normalize_text(hud_text_1)
    if "PICK" in hud_norm_1:
        return View.HOSTAGE_SELECT

    # Step 7: Global chat detection ("{RoomName} CHAT")
    # The text at (2,2) in color 2 would be e.g. "Underworld CHAT"
    if hud_norm_2.endswith("CHAT") and len(hud_norm_2) > 4:
        return View.GLOBAL_CHAT

    # Step 8: Game over (win text at y=60, no REVEAL banner)
    # Scan for win text in team colors or draw color at y=60
    for color in [3, 14, 1]:  # TeamA, TeamB, draw
        win_text = read_text_at(frame, 0, 60, color, 20)
        if win_text and ("WIN" in normalize_text(win_text) or "ONE" in normalize_text(win_text)):
            return View.GAME_OVER

    # Step 9: Fallback
    return View.UNKNOWN
