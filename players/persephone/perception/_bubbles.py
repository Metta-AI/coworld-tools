"""Speech bubble detection in the overworld view."""

from __future__ import annotations

import numpy as np

from ._common import (
    BAR_Y,
    COLOR_BUBBLE,
    MINIMAP_X,
    PLAYER_H,
    PLAYER_W,
    SCREEN_HEIGHT,
    SCREEN_WIDTH,
    TOP_BAR_H,
)
from .types import SpeechBubble


def scan_speech_bubbles(frame: np.ndarray) -> list[SpeechBubble]:
    """Detect speech bubbles in the overworld game area.

    The bubble pattern (color 2) relative to the bubble's top-left:
        row y:   2 2 2 !2
        row y+1: 2 2 2 !2
        row y+2: !2 !2 !2 2

    The player sprite's top-left is at (bubble_x + 3, bubble_y + 3).

    Args:
        frame: (128, 128) pixel array.

    Returns:
        List of SpeechBubble instances with sprite positions and colors.
    """
    results: list[SpeechBubble] = []
    c = COLOR_BUBBLE

    # Only scan the game world area (avoid HUD and minimap)
    y_max = BAR_Y - PLAYER_H - 5  # Don't scan too close to bottom
    x_max = MINIMAP_X - 4  # Avoid minimap region

    for y in range(TOP_BAR_H, min(y_max, SCREEN_HEIGHT - 5)):
        for x in range(0, min(x_max, SCREEN_WIDTH - 4)):
            # Check bubble pattern
            if frame[y, x] != c:
                continue
            if frame[y, x + 1] != c:
                continue
            if frame[y, x + 2] != c:
                continue
            if frame[y, x + 3] == c:
                continue  # 4th pixel must NOT be the bubble color
            if frame[y + 1, x] != c:
                continue
            if frame[y + 1, x + 1] != c:
                continue
            if frame[y + 1, x + 2] != c:
                continue
            if frame[y + 1, x + 3] == c:
                continue
            # Row y+2: first 3 must NOT be bubble color, 4th must be
            if frame[y + 2, x] == c:
                continue
            if frame[y + 2, x + 1] == c:
                continue
            if frame[y + 2, x + 2] == c:
                continue
            if frame[y + 2, x + 3] != c:
                continue

            # Match! Player sprite top-left is at (x+3, y+3)
            sprite_x = x + 3
            sprite_y = y + 3

            # Read player color from sprite center
            cx = sprite_x + PLAYER_W // 2
            cy = sprite_y + PLAYER_H // 2
            if cx < SCREEN_WIDTH and cy < SCREEN_HEIGHT:
                player_color = int(frame[cy, cx])
                if player_color != 0 and player_color != 1:
                    results.append(SpeechBubble(
                        screen_x=sprite_x,
                        screen_y=sprite_y,
                        player_color=player_color,
                    ))

    return results
