"""Persistent traversability map for Orpheus spatial reasoning."""

from __future__ import annotations

from enum import IntEnum

import numpy as np

from orpheus.perception._common import (
    BAR_Y,
    MINIMAP_X,
    MINIMAP_Y,
    MINIMAP_SIZE,
    PLAYER_H,
    PLAYER_W,
    SCREEN_WIDTH,
    TOP_BAR_H,
)
from orpheus.types import Room

WALL_COLOR = 5
ROOM_A_FLOOR_COLORS = (12, 6)
ROOM_B_FLOOR_COLORS = (9, 10)


class CellState(IntEnum):
    """Static traversability state for a single occupancy-grid cell."""

    UNKNOWN = 0
    FREE = 1
    WALL = 2


class OccupancyGrid:
    """2:1 room occupancy grid with viewport/minimap provenance tracking."""

    def __init__(self, room_size: tuple[int, int], resolution: int = 2):
        if resolution <= 0:
            raise ValueError("resolution must be positive")

        self.room_size = room_size
        self.resolution = resolution
        room_w, room_h = room_size
        self.grid_w = (room_w + resolution - 1) // resolution
        self.grid_h = (room_h + resolution - 1) // resolution
        self.cells = np.zeros((self.grid_h, self.grid_w), dtype=np.uint8)
        self.viewport_confirmed = np.zeros(
            (self.grid_h, self.grid_w),
            dtype=bool,
        )
        self._mark_borders()

    def _mark_borders(self) -> None:
        if self.grid_w == 0 or self.grid_h == 0:
            return

        self.cells[0, :] = CellState.WALL
        self.cells[self.grid_h - 1, :] = CellState.WALL
        self.cells[:, 0] = CellState.WALL
        self.cells[:, self.grid_w - 1] = CellState.WALL
        self.viewport_confirmed[0, :] = True
        self.viewport_confirmed[self.grid_h - 1, :] = True
        self.viewport_confirmed[:, 0] = True
        self.viewport_confirmed[:, self.grid_w - 1] = True

    def world_to_grid(self, x: int, y: int) -> tuple[int, int]:
        """Convert world-pixel coordinates to grid coordinates."""
        return x // self.resolution, y // self.resolution

    def grid_to_world(self, gx: int, gy: int) -> tuple[int, int]:
        """Convert grid coordinates to top-left world-pixel coordinates."""
        return gx * self.resolution, gy * self.resolution

    def is_inside(self, gx: int, gy: int) -> bool:
        """Return whether a grid coordinate falls inside the room grid."""
        return 0 <= gx < self.grid_w and 0 <= gy < self.grid_h

    def get(self, gx: int, gy: int) -> CellState:
        """Return a cell state, treating out-of-bounds as impassable wall."""
        if not self.is_inside(gx, gy):
            return CellState.WALL
        return CellState(self.cells[gy, gx])

    def is_wall(self, gx: int, gy: int) -> bool:
        return self.get(gx, gy) == CellState.WALL

    def is_free(self, gx: int, gy: int) -> bool:
        return self.get(gx, gy) == CellState.FREE

    def is_unknown(self, gx: int, gy: int) -> bool:
        return self.get(gx, gy) == CellState.UNKNOWN

    def mark_wall(
        self,
        gx: int,
        gy: int,
        viewport_confirmed: bool = False,
    ) -> None:
        """Mark one grid cell as wall, respecting provenance rules."""
        self._mark_cell(gx, gy, CellState.WALL, viewport_confirmed)

    def mark_free(
        self,
        gx: int,
        gy: int,
        viewport_confirmed: bool = False,
    ) -> None:
        """Mark one grid cell as free, respecting provenance rules."""
        self._mark_cell(gx, gy, CellState.FREE, viewport_confirmed)

    def _mark_cell(
        self,
        gx: int,
        gy: int,
        state: CellState,
        viewport_confirmed: bool,
    ) -> None:
        if not self.is_inside(gx, gy):
            return

        if viewport_confirmed:
            self.cells[gy, gx] = state
            self.viewport_confirmed[gy, gx] = True
            return

        if (
            self.cells[gy, gx] == CellState.UNKNOWN
            and not self.viewport_confirmed[gy, gx]
        ):
            self.cells[gy, gx] = state

    def mark_wall_region(
        self,
        gx: int,
        gy: int,
        w: int,
        h: int,
        viewport_confirmed: bool = False,
    ) -> None:
        """Mark a rectangular grid region as wall."""
        self._mark_region(gx, gy, w, h, CellState.WALL, viewport_confirmed)

    def mark_free_region(
        self,
        gx: int,
        gy: int,
        w: int,
        h: int,
        viewport_confirmed: bool = False,
    ) -> None:
        """Mark a rectangular grid region as free."""
        self._mark_region(gx, gy, w, h, CellState.FREE, viewport_confirmed)

    def _mark_region(
        self,
        gx: int,
        gy: int,
        w: int,
        h: int,
        state: CellState,
        viewport_confirmed: bool,
    ) -> None:
        if w <= 0 or h <= 0:
            return

        x0 = max(gx, 0)
        y0 = max(gy, 0)
        x1 = min(gx + w, self.grid_w)
        y1 = min(gy + h, self.grid_h)
        if x0 >= x1 or y0 >= y1:
            return

        cells_slice = self.cells[y0:y1, x0:x1]
        confirmed_slice = self.viewport_confirmed[y0:y1, x0:x1]
        if viewport_confirmed:
            cells_slice[:, :] = state
            confirmed_slice[:, :] = True
            return

        mask = (cells_slice == CellState.UNKNOWN) & (~confirmed_slice)
        cells_slice[mask] = state

    def update_from_viewport(
        self,
        self_position: tuple[int, int],
        frame: np.ndarray,
        room_id: Room | None,
        palette: dict | None = None,
    ) -> None:
        """Update static terrain from the directly visible viewport pixels."""
        del palette

        room_w, room_h = self.room_size
        self_x, self_y = self_position
        camera_x = _clamp(self_x - 64, 0, room_w - SCREEN_WIDTH)
        camera_y = _clamp(self_y - 64, -TOP_BAR_H, room_h - BAR_Y)
        floor_colors = _floor_colors(room_id)

        wall_gx: list[np.ndarray] = []
        wall_gy: list[np.ndarray] = []
        free_gx: list[np.ndarray] = []
        free_gy: list[np.ndarray] = []

        for screen_y in range(TOP_BAR_H, BAR_Y):
            world_y = camera_y + screen_y
            if world_y < 0 or world_y >= room_h:
                continue

            segments = [(0, SCREEN_WIDTH)]
            if MINIMAP_Y <= screen_y < MINIMAP_Y + MINIMAP_SIZE:
                segments = [(0, MINIMAP_X)]

            for start_x, end_x in segments:
                segment = frame[screen_y, start_x:end_x]
                if segment.size == 0:
                    continue

                wall_offsets = np.where(segment == WALL_COLOR)[0]
                if wall_offsets.size:
                    gxs = self._pixel_offsets_to_grid_x(
                        wall_offsets,
                        start_x,
                        camera_x,
                        room_w,
                    )
                    if gxs.size:
                        wall_gx.append(gxs)
                        wall_gy.append(
                            np.full(gxs.shape, world_y // self.resolution)
                        )

                floor_offsets = np.where(np.isin(segment, floor_colors))[0]
                if floor_offsets.size:
                    gxs = self._pixel_offsets_to_grid_x(
                        floor_offsets,
                        start_x,
                        camera_x,
                        room_w,
                    )
                    if gxs.size:
                        free_gx.append(gxs)
                        free_gy.append(
                            np.full(gxs.shape, world_y // self.resolution)
                        )

        self._mark_confirmed_pixels(free_gx, free_gy, CellState.FREE)
        self._mark_confirmed_pixels(wall_gx, wall_gy, CellState.WALL)

    def _pixel_offsets_to_grid_x(
        self,
        offsets: np.ndarray,
        start_x: int,
        camera_x: int,
        room_w: int,
    ) -> np.ndarray:
        world_x = camera_x + start_x + offsets
        valid = (world_x >= 0) & (world_x < room_w)
        if not np.any(valid):
            return np.array([], dtype=np.int64)
        return (world_x[valid] // self.resolution).astype(np.int64)

    def _mark_confirmed_pixels(
        self,
        gx_parts: list[np.ndarray],
        gy_parts: list[np.ndarray],
        state: CellState,
    ) -> None:
        if not gx_parts:
            return

        gxs = np.concatenate(gx_parts)
        gys = np.concatenate(gy_parts)
        inside = (
            (gxs >= 0)
            & (gxs < self.grid_w)
            & (gys >= 0)
            & (gys < self.grid_h)
        )
        if not np.any(inside):
            return

        coords = np.unique(np.column_stack((gys[inside], gxs[inside])), axis=0)
        self.cells[coords[:, 0], coords[:, 1]] = state
        self.viewport_confirmed[coords[:, 0], coords[:, 1]] = True

    def update_from_minimap(
        self,
        minimap_dots: list,
        room_size: tuple[int, int],
        self_color: int | None = None,
    ) -> None:
        """Update approximate obstacle cells from minimap color-5 dots."""
        del room_size, self_color

        for dot in minimap_dots:
            if dot.is_self or dot.color != WALL_COLOR:
                continue

            gx, gy = self.world_to_grid(dot.world_x, dot.world_y)
            self.mark_wall_region(gx - 2, gy - 2, 4, 4)

    def update_from_movement(self, self_position: tuple[int, int]) -> None:
        """Mark the player's current 7x7 footprint as traversable."""
        self_x, self_y = self_position
        top_left_x = self_x - PLAYER_W // 2
        top_left_y = self_y - PLAYER_H // 2
        gx, gy = self.world_to_grid(top_left_x, top_left_y)
        self.mark_free_region(gx, gy, 4, 4, viewport_confirmed=True)


def _floor_colors(room_id: Room | None) -> tuple[int, ...]:
    if room_id == Room.UNDERWORLD:
        return ROOM_A_FLOOR_COLORS
    if room_id == Room.MORTAL_REALM:
        return ROOM_B_FLOOR_COLORS
    return ROOM_A_FLOOR_COLORS + ROOM_B_FLOOR_COLORS


def _clamp(value: int, lower: int, upper: int) -> int:
    return max(min(value, upper), lower)


__all__ = [
    "WALL_COLOR",
    "ROOM_A_FLOOR_COLORS",
    "ROOM_B_FLOOR_COLORS",
    "CellState",
    "OccupancyGrid",
]
