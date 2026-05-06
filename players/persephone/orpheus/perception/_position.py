"""Position estimation from minimap self-dot and floor grid dots.

Ported from upstream bots/bot_utils.ts:readPosition.
"""

from __future__ import annotations

import numpy as np

from ._common import (
    BAR_Y,
    BOTTOM_BAR_H,
    COLOR_SELF_DOT,
    DEFAULT_ROOM_SIZE,
    FLOOR_DOT_GRID,
    FLOOR_DOT_OFFSET,
    MINIMAP_SIZE,
    MINIMAP_X,
    MINIMAP_Y,
    PLAYER_H,
    PLAYER_W,
    ROOM_A_ALT,
    ROOM_A_FLOOR,
    ROOM_B_ALT,
    ROOM_B_FLOOR,
    SCREEN_HEIGHT,
    SCREEN_WIDTH,
    TOP_BAR_H,
)
from .types import Position, Room


_HALF_W = SCREEN_WIDTH // 2
_PLAYER_CENTER_SCREEN_Y = 64


def detect_room(frame: np.ndarray) -> Room | None:
    """Detect which room the player is in from floor colors near screen center.

    Samples a 13x13 area at screen center (between HUD bars) and counts
    floor-colored pixels for each room.
    """
    cx = _HALF_W
    cy = (SCREEN_HEIGHT + TOP_BAR_H - BOTTOM_BAR_H) // 2
    a_count = 0
    b_count = 0

    for dy in range(-6, 7):
        for dx in range(-6, 7):
            sx = cx + dx
            sy = cy + dy
            if sx < 0 or sy < TOP_BAR_H or sx >= SCREEN_WIDTH or sy >= BAR_Y:
                continue
            c = int(frame[sy, sx])
            if c == ROOM_A_FLOOR or c == ROOM_A_ALT:
                a_count += 1
            if c == ROOM_B_FLOOR or c == ROOM_B_ALT:
                b_count += 1

    if a_count > b_count and a_count >= 5:
        return Room.UNDERWORLD
    if b_count > a_count and b_count >= 5:
        return Room.MORTAL_REALM
    return None


def estimate_position(
    frame: np.ndarray,
    room: Room | None = None,
    room_size: int = DEFAULT_ROOM_SIZE,
) -> Position | None:
    """Estimate the player's world position from the frame.

    Combines the minimap self-dot (coarse position) with floor grid dot
    alignment (fine position) to produce a sub-cell-accurate estimate.

    Args:
        frame: (128, 128) uint8 pixel array.
        room: Current room. If None, auto-detected from floor colors.
        room_size: Room dimensions in world pixels.

    Returns:
        Position with room and world coordinates, or None if detection fails.
    """
    if room is None:
        room = detect_room(frame)
    if room is None:
        return None

    # Step 1: Coarse position from minimap self-dot
    coarse = _read_minimap_self_dot(frame, room_size)
    if coarse is None:
        return None

    # Step 2: Fine position from floor grid dots
    alt_color = ROOM_A_ALT if room == Room.UNDERWORLD else ROOM_B_ALT
    dot = _find_floor_dot(frame, alt_color)

    if dot is None:
        # Fallback: use coarse position only
        return Position(
            room=room,
            x=coarse[0] - PLAYER_W // 2,
            y=coarse[1] - PLAYER_H // 2,
        )

    # Step 3: Compute exact camera offset from floor dot alignment
    max_cam_x = max(0, room_size - SCREEN_WIDTH)
    max_cam_y = max(-TOP_BAR_H, room_size - SCREEN_HEIGHT + BOTTOM_BAR_H)

    approx_cam_x = _clamp(coarse[0] - _HALF_W, 0, max_cam_x)
    approx_cam_y = _clamp(coarse[1] - _PLAYER_CENTER_SCREEN_Y, -TOP_BAR_H, max_cam_y)

    dot_world_x_approx = approx_cam_x + dot[0]
    dot_world_y_approx = approx_cam_y + dot[1]

    tile_nx = round((dot_world_x_approx - FLOOR_DOT_OFFSET) / FLOOR_DOT_GRID)
    tile_ny = round((dot_world_y_approx - FLOOR_DOT_OFFSET) / FLOOR_DOT_GRID)

    exact_cam_x = tile_nx * FLOOR_DOT_GRID + FLOOR_DOT_OFFSET - dot[0]
    exact_cam_y = tile_ny * FLOOR_DOT_GRID + FLOOR_DOT_OFFSET - dot[1]

    # Derive player position from camera (player is at screen center when not at edges)
    if 0 < exact_cam_x < max_cam_x:
        pcx = exact_cam_x + _HALF_W
    else:
        pcx = coarse[0]

    if -TOP_BAR_H < exact_cam_y < max_cam_y:
        pcy = exact_cam_y + _PLAYER_CENTER_SCREEN_Y
    else:
        pcy = coarse[1]

    return Position(
        room=room,
        x=pcx - PLAYER_W // 2,
        y=pcy - PLAYER_H // 2,
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _read_minimap_self_dot(
    frame: np.ndarray, room_size: int,
) -> tuple[int, int] | None:
    """Find the self dot (color 2) on the minimap and return world coords."""
    cell_w = room_size / MINIMAP_SIZE
    cell_h = room_size / MINIMAP_SIZE
    dot_mx = -1
    dot_my = -1

    # Scan entire minimap; take the LAST color-2 pixel found
    # (self is drawn last, overwrites others)
    for my in range(MINIMAP_SIZE):
        for mx in range(MINIMAP_SIZE):
            px = MINIMAP_X + mx
            py = MINIMAP_Y + my
            if px >= SCREEN_WIDTH or py >= SCREEN_HEIGHT:
                continue
            if frame[py, px] == COLOR_SELF_DOT:
                dot_mx = mx
                dot_my = my

    if dot_mx < 0:
        return None

    world_x = int(dot_mx * cell_w + cell_w / 2)
    world_y = int(dot_my * cell_h + cell_h / 2)
    return (world_x, world_y)


def _find_floor_dot(frame: np.ndarray, alt_color: int) -> tuple[int, int] | None:
    """Find the closest 2x2 floor grid dot to screen center.

    Returns (screen_x, screen_y) of the dot, or None if not found.
    """
    bot_limit = BAR_Y
    cx = _HALF_W
    cy = (TOP_BAR_H + bot_limit) // 2
    best_dist = float("inf")
    best_sx = -1
    best_sy = -1

    for sy in range(TOP_BAR_H, bot_limit - 1):
        for sx in range(0, SCREEN_WIDTH - 1):
            # Skip minimap area
            if sx >= MINIMAP_X - 1 and sy <= MINIMAP_Y + MINIMAP_SIZE + 1:
                continue
            # Check for 2x2 block of alt_color
            if (
                frame[sy, sx] == alt_color
                and frame[sy, sx + 1] == alt_color
                and frame[sy + 1, sx] == alt_color
                and frame[sy + 1, sx + 1] == alt_color
            ):
                d = (sx - cx) ** 2 + (sy - cy) ** 2
                if d < best_dist:
                    best_dist = d
                    best_sx = sx
                    best_sy = sy

    if best_sx < 0:
        return None
    return (best_sx, best_sy)


def _clamp(v: int, lo: int, hi: int) -> int:
    return max(lo, min(hi, v))
