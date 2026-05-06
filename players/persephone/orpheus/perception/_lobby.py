"""Lobby view parser."""

from __future__ import annotations

import numpy as np

from ._common import COLOR_HUD_ALERT, COLOR_HUD_NORMAL
from ._ocr import normalize_digits, read_text_at
from .types import LobbyPerception


def parse_lobby(frame: np.ndarray) -> LobbyPerception:
    """Extract lobby information from a lobby-phase frame.

    Args:
        frame: (128, 128) uint8 pixel array.

    Returns:
        LobbyPerception with player count, max, and countdown.
    """
    result = LobbyPerception()

    # Top bar text at (2, 2) in color 2: "{count}/{max} PLAYERS"
    text = read_text_at(frame, 2, 2, COLOR_HUD_NORMAL, 20)
    text_d = normalize_digits(text)

    # Parse "N/M"
    if "/" in text_d:
        parts = text_d.split("/", 1)
        try:
            result.player_count = int(parts[0].strip())
        except ValueError:
            pass
        # Second part might be "10 PLAYERS" -- take just the digits
        rest = parts[1].strip()
        digits = ""
        for ch in rest:
            if ch.isdigit():
                digits += ch
            else:
                break
        if digits:
            try:
                result.max_players = int(digits)
            except ValueError:
                pass

    # Countdown text at (80, 2) in color 8: "START {secs}"
    countdown_text = read_text_at(frame, 80, 2, COLOR_HUD_ALERT, 10)
    countdown_d = normalize_digits(countdown_text)
    if countdown_d.startswith("START"):
        digits = countdown_d[5:].strip()
        num = ""
        for ch in digits:
            if ch.isdigit():
                num += ch
            else:
                break
        if num:
            try:
                result.countdown_secs = int(num)
            except ValueError:
                pass

    return result
