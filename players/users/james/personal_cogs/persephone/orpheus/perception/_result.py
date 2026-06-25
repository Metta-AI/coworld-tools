"""Reveal / GameOver view parser."""

from __future__ import annotations

import numpy as np

from ._common import COLOR_HUD_DIM, COLOR_HUD_NORMAL, SCREEN_WIDTH, TEAM_A_COLOR, TEAM_B_COLOR
from ._ocr import normalize_text, read_text_at
from .types import ResultPerception


def parse_result(frame: np.ndarray) -> ResultPerception:
    """Extract win/loss result from a reveal or game-over frame.

    Args:
        frame: (128, 128) uint8 pixel array.

    Returns:
        ResultPerception with winner and phase info.
    """
    result = ResultPerception()

    # Check if this is Reveal (has "REVEAL!" at top) or GameOver (no banner)
    top_text = read_text_at(frame, 2, 2, COLOR_HUD_NORMAL, 10)
    result.is_reveal = normalize_text(top_text).startswith("REVEAL")

    # Win text is rendered centered at y=60.
    # Scan for text in each possible winner color.
    for color, winner_name in [
        (TEAM_A_COLOR, "Shades"),
        (TEAM_B_COLOR, "Nymphs"),
        (COLOR_HUD_DIM, None),  # Draw: "NO ONE WINS!" in color 1
    ]:
        # Scan x positions for centered text
        for x in range(0, SCREEN_WIDTH - 20):
            text = read_text_at(frame, x, 60, color, 16)
            if not text:
                continue
            norm = normalize_text(text)
            if "WIN" in norm:
                result.winner = winner_name
                result.winner_color = color
                return result
            if "ONE" in norm and "WIN" in normalize_text(
                read_text_at(frame, x, 60, color, 20)
            ):
                result.winner = None  # Draw
                result.winner_color = color
                return result

    return result
