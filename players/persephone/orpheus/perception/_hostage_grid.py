"""Hostage selection grid parser."""

from __future__ import annotations

import numpy as np

from ._common import (
    COLOR_HOSTAGE_CHECK,
    COLOR_HUD_NORMAL,
    HOSTAGE_CELL_H,
    HOSTAGE_CELL_W,
    HOSTAGE_GRID_Y,
    HOSTAGE_MAX_COLS,
    PLAYER_H,
    PLAYER_W,
    SCREEN_HEIGHT,
    SCREEN_WIDTH,
)
from ._ocr import normalize_text, read_text_at
from ._sprites import detect_sprite_shape
from .types import HostageGrid, PlayerShape


def parse_hostage_grid(frame: np.ndarray) -> HostageGrid | None:
    """Parse the leader's hostage selection grid.

    The grid is centered horizontally, starts at y=11, uses 12x14 cells,
    and has at most four columns by three rows. This mirrors the upstream
    TypeScript parser's column-count probe and cell scan.
    """
    for cols in range(HOSTAGE_MAX_COLS, 0, -1):
        grid_w = cols * HOSTAGE_CELL_W
        grid_x = (SCREEN_WIDTH - grid_w) // 2

        test_x = grid_x + (HOSTAGE_CELL_W - PLAYER_W) // 2 + PLAYER_W // 2
        test_y = HOSTAGE_GRID_Y + 1 + PLAYER_H // 2
        if not _is_in_bounds(test_x, test_y):
            continue

        probe = int(frame[test_y, test_x])
        if probe == 0 or probe == 1:
            continue

        grid = _scan_grid(frame, grid_x, cols)
        if not grid.eligible_colors:
            return None
        grid.count_label = _read_count_label(frame, grid_x, cols)
        return grid

    return None


def _scan_grid(frame: np.ndarray, grid_x: int, cols: int) -> HostageGrid:
    grid = HostageGrid(cursor_index=0)

    for row in range(3):
        for col in range(cols):
            cell_x = grid_x + col * HOSTAGE_CELL_W
            cell_y = HOSTAGE_GRID_Y + row * HOSTAGE_CELL_H
            sprite_x = cell_x + (HOSTAGE_CELL_W - PLAYER_W) // 2
            sprite_y = cell_y + 1

            if sprite_y + PLAYER_H >= SCREEN_HEIGHT:
                break

            color, shape = _read_grid_sprite(frame, sprite_x, sprite_y)
            if color is None:
                continue

            position = len(grid.eligible_colors)
            grid.eligible_colors.append(color)
            grid.eligible_shapes.append(shape)

            check_x = cell_x + HOSTAGE_CELL_W - 3
            check_y = cell_y + 1
            if _is_in_bounds(check_x, check_y):
                if int(frame[check_y, check_x]) == COLOR_HOSTAGE_CHECK:
                    grid.selected_positions.append(position)
                    grid.selected_colors.append(color)

            if _is_in_bounds(cell_x, cell_y):
                if int(frame[cell_y, cell_x]) == COLOR_HUD_NORMAL:
                    grid.cursor_index = position

    return grid


def _read_grid_sprite(
    frame: np.ndarray,
    x: int,
    y: int,
) -> tuple[int | None, PlayerShape | None]:
    """Return the sprite color and shape at a hostage-grid sprite origin."""
    if x < 0 or y < 0 or x + PLAYER_W > SCREEN_WIDTH or y + PLAYER_H > SCREEN_HEIGHT:
        return (None, None)

    shape = detect_sprite_shape(frame, x, y)
    if shape is None:
        return (None, None)

    region = frame[y : y + PLAYER_H, x : x + PLAYER_W]
    color = _dominant_sprite_color(region)
    if color is None:
        return (None, shape)
    return (color, shape)


def _dominant_sprite_color(region: np.ndarray) -> int | None:
    """Read the dominant non-background sprite fill color from a 7x7 region."""
    flat = region.ravel()
    candidates = flat[(flat != 0) & (flat != 1)]
    if candidates.size == 0:
        return None

    counts = np.bincount(candidates, minlength=16)
    color = int(np.argmax(counts))
    if counts[color] == 0:
        return None
    return color


def _read_count_label(frame: np.ndarray, grid_x: int, cols: int) -> str | None:
    """Read the optional ``N/M HOSTAGES`` label under the grid."""
    grid_w = cols * HOSTAGE_CELL_W
    rows = _infer_rows(frame, grid_x, cols)
    label_y = HOSTAGE_GRID_Y + rows * HOSTAGE_CELL_H + 2
    if label_y + 5 > SCREEN_HEIGHT:
        return None

    for x in range(max(0, grid_x - 20), min(SCREEN_WIDTH - 3, grid_x + grid_w + 1)):
        text = read_text_at(frame, x, label_y, COLOR_HUD_NORMAL, 15).strip()
        if not text:
            continue
        norm = normalize_text(text).upper()
        if "HOSTAGE" in norm or "/" in norm:
            return text
    return None


def _infer_rows(frame: np.ndarray, grid_x: int, cols: int) -> int:
    """Infer how many grid rows contain sprites."""
    rows = 0
    for row in range(3):
        found = False
        for col in range(cols):
            cell_x = grid_x + col * HOSTAGE_CELL_W
            cell_y = HOSTAGE_GRID_Y + row * HOSTAGE_CELL_H
            sprite_x = cell_x + (HOSTAGE_CELL_W - PLAYER_W) // 2
            sprite_y = cell_y + 1
            if _read_grid_sprite(frame, sprite_x, sprite_y)[0] is not None:
                found = True
                break
        if found:
            rows = row + 1
    return max(rows, 1)


def _is_in_bounds(x: int, y: int) -> bool:
    return 0 <= x < SCREEN_WIDTH and 0 <= y < SCREEN_HEIGHT
