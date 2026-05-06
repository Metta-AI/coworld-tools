"""Minimap scanner: extract player dots from the 20x20 minimap region."""

from __future__ import annotations

import numpy as np

from ._common import (
    COLOR_SELF_DOT,
    DEFAULT_ROOM_SIZE,
    MINIMAP_EXCLUDE_ROOM_A,
    MINIMAP_EXCLUDE_ROOM_B,
    MINIMAP_SIZE,
    MINIMAP_X,
    MINIMAP_Y,
    PLAYER_H,
    PLAYER_W,
    SCREEN_HEIGHT,
    SCREEN_WIDTH,
)
from .types import MinimapDot, Room


def scan_minimap(
    frame: np.ndarray,
    room: Room | None,
    room_size: int = DEFAULT_ROOM_SIZE,
) -> list[MinimapDot]:
    """Scan the minimap region and return all detected player dots.

    Args:
        frame: (128, 128) uint8 pixel array.
        room: Current room (determines which floor color to exclude).
        room_size: Room dimensions for world-coordinate estimation.

    Returns:
        List of MinimapDot instances for each non-background pixel.
    """
    if room is None:
        exclude = MINIMAP_EXCLUDE_ROOM_A | MINIMAP_EXCLUDE_ROOM_B
    elif room == Room.UNDERWORLD:
        exclude = MINIMAP_EXCLUDE_ROOM_A
    else:
        exclude = MINIMAP_EXCLUDE_ROOM_B

    cell_w = room_size / MINIMAP_SIZE
    cell_h = room_size / MINIMAP_SIZE
    dots: list[MinimapDot] = []

    for my in range(MINIMAP_SIZE):
        for mx in range(MINIMAP_SIZE):
            px = MINIMAP_X + mx
            py = MINIMAP_Y + my
            if px >= SCREEN_WIDTH or py >= SCREEN_HEIGHT:
                continue
            c = int(frame[py, px])
            if c in exclude:
                continue
            dots.append(MinimapDot(
                color=c,
                minimap_x=mx,
                minimap_y=my,
                world_x=int(mx * cell_w + cell_w / 2),
                world_y=int(my * cell_h + cell_h / 2),
                is_self=(c == COLOR_SELF_DOT),
            ))

    return dots
