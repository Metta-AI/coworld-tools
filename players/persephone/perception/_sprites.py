"""Sprite utilities: read player colors from sprite regions."""

from __future__ import annotations

import numpy as np

from ._common import PLAYER_H, PLAYER_W, SCREEN_HEIGHT, SCREEN_WIDTH


def read_sprite_color(frame: np.ndarray, x: int, y: int) -> int | None:
    """Read the dominant fill color of a 7x7 sprite at (x, y).

    Reads the center pixel (x+3, y+3) which is always a fill pixel
    for all 12 player shapes. Returns None if out of bounds or black.
    """
    cx = x + PLAYER_W // 2  # x + 3
    cy = y + PLAYER_H // 2  # y + 3
    if cx < 0 or cy < 0 or cx >= SCREEN_WIDTH or cy >= SCREEN_HEIGHT:
        return None
    c = int(frame[cy, cx])
    if c == 0 or c == 1:  # Black or dark border
        return None
    return c


def scan_sprite_row(
    frame: np.ndarray,
    start_x: int,
    y: int,
    stride: int,
    max_slots: int = 12,
) -> list[int]:
    """Scan a horizontal row of sprites and return their colors.

    Used for chatroom occupant sprites, hostage grid, etc.

    Args:
        frame: (128, 128) pixel array.
        start_x: X position of the first sprite.
        y: Y position of all sprites.
        stride: Pixel distance between sprite starts.
        max_slots: Maximum sprites to check.

    Returns:
        List of player colors, stopping at the first empty slot.
    """
    colors: list[int] = []
    for slot in range(max_slots):
        sx = start_x + slot * stride
        if sx + PLAYER_W > SCREEN_WIDTH:
            break
        c = read_sprite_color(frame, sx, y)
        if c is None:
            break  # First empty slot = end of occupants
        colors.append(c)
    return colors
