#!/usr/bin/env python3
"""Python clone of the Infinite Blocks pystack bot.

The original stacker is a Nim websocket bot in
`agent-policies/policies/symbolic/bitworld/infinite-blocks/stacker`. This file
ports its global-protocol parser and placement heuristic, and keeps a
framebuffer fallback for the current BitWorld Infinite Blocks server, which only
serves `/player` frames.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import random
import sys
import time
from collections import deque
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Iterable
from urllib.parse import parse_qsl, quote, urlencode, urlsplit, urlunsplit


PLAYER_DEFAULT_PORT = 2000
ENGINE_WS_ENV = "COGAMES_ENGINE_WS_URL"
PLAYER_WEBSOCKET_PATH = "/player"
GLOBAL_WEBSOCKET_PATH = "/global"

SCREEN_WIDTH = 128
SCREEN_HEIGHT = 128
PROTOCOL_BYTES = (SCREEN_WIDTH * SCREEN_HEIGHT) // 2
CELL_PIXELS = 2
FRAME_GRID_WIDTH = SCREEN_WIDTH // CELL_PIXELS
FRAME_GRID_HEIGHT = SCREEN_HEIGHT // CELL_PIXELS
FRAME_IGNORE_TOP_CELLS = 6

GLOBAL_BOARD_WIDTH_CELLS = 250
GLOBAL_BOARD_HEIGHT_CELLS = 250
GLOBAL_BASE_TERRAIN_Y = GLOBAL_BOARD_HEIGHT_CELLS * 31 // 50
LINE_CLEAR_LENGTH = 8

MAX_DRAIN_MESSAGES = 64
DEBUG_INTERVAL = 60

BRIGHT_MIN_CHANNEL = 30
BRIGHT_MAX_CHANNEL = 70
SUPPORTED_GAP_BONUS = 1400
POCKET_FILL_BONUS = 2400
HOLE_REDUCTION_BONUS = 4500
HOLE_INCREASE_PENALTY = 5200
ROW_COMPLETION_BONUS = 24000
OUTSIDE_LANE_PENALTY = 750
BUMPINESS_PENALTY = 80
HEIGHT_PENALTY = 10

BUTTON_UP = 1 << 0
BUTTON_DOWN = 1 << 1
BUTTON_LEFT = 1 << 2
BUTTON_RIGHT = 1 << 3
BUTTON_SELECT = 1 << 4
BUTTON_A = 1 << 5
BUTTON_B = 1 << 6

TERRAIN_COLOR_INDEX = 1
BACKGROUND_COLOR_INDEX = 0
PLAYER_COLOR_INDICES = set(range(4, 16))


class PieceKind(IntEnum):
    I = 0
    O = 1
    T = 2
    L = 3
    J = 4
    S = 5
    Z = 6


@dataclass(frozen=True)
class Cell:
    x: int
    y: int


RgbaColor = tuple[int, int, int, int]


@dataclass
class SpriteImage:
    width: int = 0
    height: int = 0
    label: str = ""
    pixels: bytes = b""

    def rgba_at(self, x: int, y: int) -> RgbaColor:
        if x < 0 or y < 0 or x >= self.width or y >= self.height:
            return (0, 0, 0, 0)
        offset = (y * self.width + x) * 4
        return (
            self.pixels[offset],
            self.pixels[offset + 1],
            self.pixels[offset + 2],
            self.pixels[offset + 3],
        )


@dataclass
class GlobalObject:
    id: int
    x: int
    y: int
    z: int
    layer: int
    sprite_id: int


@dataclass
class ActivePiece:
    found: bool = False
    kind: PieceKind = PieceKind.I
    rotation: int = 0
    origin_x: int = 0
    origin_y: int = 0
    cells: list[Cell] = field(default_factory=list)


@dataclass
class Placement:
    found: bool = False
    rotation: int = 0
    x: int = 0
    y: int = 0
    score: int = 0


def read_u16(data: bytes, offset: int) -> int:
    return data[offset] | (data[offset + 1] << 8)


def read_u32(data: bytes, offset: int) -> int:
    return (
        data[offset]
        | (data[offset + 1] << 8)
        | (data[offset + 2] << 16)
        | (data[offset + 3] << 24)
    )


def read_i16(data: bytes, offset: int) -> int:
    value = read_u16(data, offset)
    if value >= 0x8000:
        return value - 0x10000
    return value


def piece_cells(kind: PieceKind, rotation: int) -> tuple[Cell, Cell, Cell, Cell]:
    rotation &= 3
    if kind == PieceKind.I:
        if rotation == 0:
            return (Cell(0, 1), Cell(1, 1), Cell(2, 1), Cell(3, 1))
        if rotation == 1:
            return (Cell(2, 0), Cell(2, 1), Cell(2, 2), Cell(2, 3))
        if rotation == 2:
            return (Cell(0, 2), Cell(1, 2), Cell(2, 2), Cell(3, 2))
        return (Cell(1, 0), Cell(1, 1), Cell(1, 2), Cell(1, 3))
    if kind == PieceKind.O:
        return (Cell(1, 0), Cell(2, 0), Cell(1, 1), Cell(2, 1))
    if kind == PieceKind.T:
        if rotation == 0:
            return (Cell(1, 0), Cell(0, 1), Cell(1, 1), Cell(2, 1))
        if rotation == 1:
            return (Cell(1, 0), Cell(1, 1), Cell(2, 1), Cell(1, 2))
        if rotation == 2:
            return (Cell(0, 1), Cell(1, 1), Cell(2, 1), Cell(1, 2))
        return (Cell(1, 0), Cell(0, 1), Cell(1, 1), Cell(1, 2))
    if kind == PieceKind.L:
        if rotation == 0:
            return (Cell(0, 0), Cell(0, 1), Cell(1, 1), Cell(2, 1))
        if rotation == 1:
            return (Cell(1, 0), Cell(2, 0), Cell(1, 1), Cell(1, 2))
        if rotation == 2:
            return (Cell(0, 1), Cell(1, 1), Cell(2, 1), Cell(2, 2))
        return (Cell(1, 0), Cell(1, 1), Cell(0, 2), Cell(1, 2))
    if kind == PieceKind.J:
        if rotation == 0:
            return (Cell(2, 0), Cell(0, 1), Cell(1, 1), Cell(2, 1))
        if rotation == 1:
            return (Cell(1, 0), Cell(1, 1), Cell(1, 2), Cell(2, 2))
        if rotation == 2:
            return (Cell(0, 1), Cell(1, 1), Cell(2, 1), Cell(0, 2))
        return (Cell(0, 0), Cell(1, 0), Cell(1, 1), Cell(1, 2))
    if kind == PieceKind.S:
        if rotation == 0:
            return (Cell(1, 0), Cell(2, 0), Cell(0, 1), Cell(1, 1))
        if rotation == 1:
            return (Cell(1, 0), Cell(1, 1), Cell(2, 1), Cell(2, 2))
        if rotation == 2:
            return (Cell(1, 1), Cell(2, 1), Cell(0, 2), Cell(1, 2))
        return (Cell(0, 0), Cell(0, 1), Cell(1, 1), Cell(1, 2))
    if rotation == 0:
        return (Cell(0, 0), Cell(1, 0), Cell(1, 1), Cell(2, 1))
    if rotation == 1:
        return (Cell(2, 0), Cell(1, 1), Cell(2, 1), Cell(1, 2))
    if rotation == 2:
        return (Cell(0, 1), Cell(1, 1), Cell(1, 2), Cell(2, 2))
    return (Cell(1, 0), Cell(0, 1), Cell(1, 1), Cell(0, 2))


def match_piece(cells: Iterable[Cell], kind: PieceKind, rotation: int) -> tuple[bool, int, int]:
    cell_list = list(cells)
    if len(cell_list) != 4:
        return False, 0, 0
    offsets = piece_cells(kind, rotation)
    min_cell_x = min(cell.x for cell in cell_list)
    min_cell_y = min(cell.y for cell in cell_list)
    min_offset_x = min(cell.x for cell in offsets)
    min_offset_y = min(cell.y for cell in offsets)
    origin_x = min_cell_x - min_offset_x
    origin_y = min_cell_y - min_offset_y
    cell_set = set(cell_list)
    for offset in offsets:
        if Cell(origin_x + offset.x, origin_y + offset.y) not in cell_set:
            return False, 0, 0
    return True, origin_x, origin_y


def infer_piece_from_cells(cells: Iterable[Cell]) -> ActivePiece:
    cell_list = list(cells)
    for kind in PieceKind:
        for rotation in range(4):
            ok, origin_x, origin_y = match_piece(cell_list, kind, rotation)
            if ok:
                return ActivePiece(
                    found=True,
                    kind=kind,
                    rotation=rotation,
                    origin_x=origin_x,
                    origin_y=origin_y,
                    cells=cell_list,
                )
    return ActivePiece()


def is_background(color: RgbaColor) -> bool:
    return color[0] <= 2 and color[1] <= 2 and color[2] <= 2


def looks_like_player_color(color: RgbaColor) -> bool:
    if color[3] != 255:
        return False
    low = min(color[0], color[1], color[2])
    high = max(color[0], color[1], color[2])
    return high >= 245 and low >= BRIGHT_MIN_CHANNEL and low <= BRIGHT_MAX_CHANNEL and high - low >= 170


def decompress_snappy(compressed: bytes) -> bytes:
    """Decode the raw Snappy payload used by BitWorld global sprites."""

    errors: list[str] = []
    try:
        import cramjam

        for decoder in (cramjam.snappy.decompress_raw, cramjam.snappy.decompress):
            try:
                return bytes(decoder(compressed))
            except Exception as exc:  # pragma: no cover - fallback path
                errors.append(str(exc))
    except Exception as exc:  # pragma: no cover - dependency missing path
        errors.append(str(exc))

    try:
        import snappy

        return snappy.decompress(compressed)
    except Exception as exc:  # pragma: no cover - optional fallback
        errors.append(str(exc))

    raise RuntimeError("Could not decode Snappy sprite payload: " + "; ".join(errors))


def input_packet(mask: int, protocol: str) -> bytes:
    if protocol == "sprite":
        return bytes([0x84, mask & 0x7F])
    return bytes([0, mask & 0x7F])


def chat_packet(text: str, protocol: str) -> bytes:
    safe = text.encode("ascii", "ignore")
    if protocol == "sprite":
        safe = safe[:0xFFFF]
        return bytes([0x81, len(safe) & 0xFF, (len(safe) >> 8) & 0xFF]) + safe
    return bytes([1]) + safe


def unpack_4bpp(packed: bytes) -> list[int]:
    pixels = [0] * (len(packed) * 2)
    for index, value in enumerate(packed):
        pixels[index * 2] = value & 0x0F
        pixels[index * 2 + 1] = (value >> 4) & 0x0F
    return pixels


def pack_4bpp(unpacked: Iterable[int]) -> bytes:
    values = list(unpacked)
    if len(values) % 2:
        values.append(0)
    packed = bytearray(len(values) // 2)
    for i in range(0, len(values), 2):
        packed[i // 2] = (values[i] & 0x0F) | ((values[i + 1] & 0x0F) << 4)
    return bytes(packed)


def is_occupied(occupied: list[bool], width: int, height: int, x: int, y: int) -> bool:
    if x < 0 or x >= width or y >= height:
        return True
    if y < 0:
        return False
    return occupied[y * width + x]


def occupied_at(occupied: list[bool], width: int, height: int, x: int, y: int) -> bool:
    if x < 0 or y < 0 or x >= width or y >= height:
        return False
    return occupied[y * width + x]


def can_place(
    occupied: list[bool],
    width: int,
    height: int,
    x: int,
    y: int,
    kind: PieceKind,
    rotation: int,
) -> bool:
    return all(
        not is_occupied(occupied, width, height, x + cell.x, y + cell.y)
        for cell in piece_cells(kind, rotation)
    )


def row_count(occupied: list[bool], width: int, row: int, lane_start: int) -> int:
    return sum(1 for x in range(lane_start, lane_start + LINE_CLEAR_LENGTH) if occupied[row * width + x])


def in_lane(x: int, lane_start: int) -> bool:
    return lane_start <= x < lane_start + LINE_CLEAR_LENGTH


def supported_gap(
    occupied: list[bool],
    width: int,
    height: int,
    lane_start: int,
    bottom_row: int,
    x: int,
    y: int,
) -> bool:
    if not in_lane(x, lane_start) or y < 0 or y > bottom_row:
        return False
    if occupied_at(occupied, width, height, x, y):
        return False
    if y == bottom_row:
        return True
    return occupied_at(occupied, width, height, x, y + 1)


def cell_gap_score(
    occupied: list[bool],
    width: int,
    height: int,
    lane_start: int,
    bottom_row: int,
    x: int,
    y: int,
) -> int:
    if not supported_gap(occupied, width, height, lane_start, bottom_row, x, y):
        return 0
    left_filled = x == lane_start or occupied_at(occupied, width, height, x - 1, y)
    right_filled = x == lane_start + LINE_CLEAR_LENGTH - 1 or occupied_at(
        occupied, width, height, x + 1, y
    )
    score = SUPPORTED_GAP_BONUS
    if left_filled and right_filled:
        score += POCKET_FILL_BONUS
    elif left_filled or right_filled:
        score += POCKET_FILL_BONUS // 2
    return score


def lane_holes(occupied: list[bool], width: int, height: int, lane_start: int, bottom_row: int) -> int:
    holes = 0
    for x in range(lane_start, lane_start + LINE_CLEAR_LENGTH):
        seen_block = False
        for y in range(bottom_row + 1):
            if occupied_at(occupied, width, height, x, y):
                seen_block = True
            elif seen_block:
                holes += 1
    return holes


def column_top(occupied: list[bool], width: int, height: int, x: int, bottom_row: int) -> int:
    for y in range(bottom_row + 1):
        if occupied_at(occupied, width, height, x, y):
            return y
    return bottom_row + 1


def aggregate_lane_height(
    occupied: list[bool], width: int, height: int, lane_start: int, bottom_row: int
) -> int:
    return sum(
        bottom_row + 1 - column_top(occupied, width, height, x, bottom_row)
        for x in range(lane_start, lane_start + LINE_CLEAR_LENGTH)
    )


def lane_bumpiness(occupied: list[bool], width: int, height: int, lane_start: int, bottom_row: int) -> int:
    previous = bottom_row + 1 - column_top(occupied, width, height, lane_start, bottom_row)
    total = 0
    for x in range(lane_start + 1, lane_start + LINE_CLEAR_LENGTH):
        current = bottom_row + 1 - column_top(occupied, width, height, x, bottom_row)
        total += abs(current - previous)
        previous = current
    return total


def row_potential(
    occupied: list[bool],
    width: int,
    height: int,
    lane_start: int,
    bottom_row: int,
    row: int,
) -> int:
    if row < 0 or row > bottom_row:
        return -(10**12)
    filled = row_count(occupied, width, row, lane_start)
    if filled >= LINE_CLEAR_LENGTH:
        return -(10**12)
    score = 0
    for x in range(lane_start, lane_start + LINE_CLEAR_LENGTH):
        if supported_gap(occupied, width, height, lane_start, bottom_row, x, row):
            score += 350
    score += filled * 120
    score -= abs(bottom_row - row) * 3
    return score


def target_hole_row(occupied: list[bool], width: int, height: int, lane_start: int, bottom_row: int) -> int:
    best_score = -(10**12)
    best_row = bottom_row
    for y in range(bottom_row, -1, -1):
        score = row_potential(occupied, width, height, lane_start, bottom_row, y)
        if score > best_score:
            best_score = score
            best_row = y
    return best_row


def placed_cells(x: int, y: int, kind: PieceKind, rotation: int) -> list[Cell]:
    return [Cell(x + cell.x, y + cell.y) for cell in piece_cells(kind, rotation)]


def score_placement(
    occupied: list[bool],
    width: int,
    height: int,
    lane_start: int,
    bottom_row: int,
    active: ActivePiece,
    placement: Placement,
    target_row: int,
) -> int:
    test = occupied.copy()
    before_holes = lane_holes(occupied, width, height, lane_start, bottom_row)
    before_bumpiness = lane_bumpiness(occupied, width, height, lane_start, bottom_row)
    before_height = aggregate_lane_height(occupied, width, height, lane_start, bottom_row)
    score = 0
    cells = placed_cells(placement.x, placement.y, active.kind, placement.rotation)

    for cell in cells:
        if 0 <= cell.x < width and 0 <= cell.y < height:
            test[cell.y * width + cell.x] = True
            if in_lane(cell.x, lane_start):
                score += 300
                score += cell_gap_score(occupied, width, height, lane_start, bottom_row, cell.x, cell.y)
            else:
                score -= OUTSIDE_LANE_PENALTY
            score -= abs(cell.y - target_row) * 6
            score += cell.y // 2

    seen_rows: set[int] = set()
    for cell in cells:
        if cell.y < 0 or cell.y >= height - 1 or cell.y in seen_rows:
            continue
        seen_rows.add(cell.y)
        before = row_count(occupied, width, cell.y, lane_start)
        after = row_count(test, width, cell.y, lane_start)
        if after >= LINE_CLEAR_LENGTH:
            score += ROW_COMPLETION_BONUS
        if cell.y == target_row:
            score += (after - before) * 800
        score += (after - before) * 950
        score += after * 80

    after_holes = lane_holes(test, width, height, lane_start, bottom_row)
    after_bumpiness = lane_bumpiness(test, width, height, lane_start, bottom_row)
    after_height = aggregate_lane_height(test, width, height, lane_start, bottom_row)
    if after_holes <= before_holes:
        score += (before_holes - after_holes) * HOLE_REDUCTION_BONUS
    else:
        score -= (after_holes - before_holes) * HOLE_INCREASE_PENALTY
    if after_bumpiness <= before_bumpiness:
        score += (before_bumpiness - after_bumpiness) * BUMPINESS_PENALTY
    else:
        score -= (after_bumpiness - before_bumpiness) * BUMPINESS_PENALTY
    score -= max(0, after_height - before_height) * HEIGHT_PENALTY
    return score


def choose_placement(
    occupied: list[bool],
    width: int,
    height: int,
    lane_start: int,
    bottom_row: int,
    active: ActivePiece,
) -> tuple[Placement, int]:
    if not active.found:
        return Placement(), bottom_row
    target_row = target_hole_row(occupied, width, height, lane_start, bottom_row)
    best = Placement()
    x_min = max(0, lane_start - 6)
    x_max = min(width - 1, lane_start + LINE_CLEAR_LENGTH + 4)
    for rotation in range(4):
        for x in range(x_min, x_max + 1):
            y = max(0, active.origin_y)
            if not can_place(occupied, width, height, x, y, active.kind, rotation):
                continue
            while can_place(occupied, width, height, x, y + 1, active.kind, rotation):
                y += 1
            candidate = Placement(found=True, rotation=rotation, x=x, y=y)
            candidate.score = score_placement(
                occupied, width, height, lane_start, bottom_row, active, candidate, target_row
            )
            if not best.found or candidate.score > best.score:
                best = candidate
    return best, target_row


def mask_summary(mask: int) -> str:
    parts = []
    if mask & BUTTON_UP:
        parts.append("U")
    if mask & BUTTON_DOWN:
        parts.append("D")
    if mask & BUTTON_LEFT:
        parts.append("L")
    if mask & BUTTON_RIGHT:
        parts.append("R")
    if mask & BUTTON_SELECT:
        parts.append("S")
    if mask & BUTTON_A:
        parts.append("A")
    if mask & BUTTON_B:
        parts.append("B")
    return "".join(parts) or "."


@dataclass
class GlobalPystack:
    rng: random.Random = field(default_factory=random.Random)
    frame_tick: int = 0
    map: SpriteImage = field(default_factory=SpriteImage)
    player_frame: SpriteImage = field(default_factory=SpriteImage)
    sprites: dict[int, SpriteImage] = field(default_factory=dict)
    objects: dict[int, GlobalObject] = field(default_factory=dict)
    own_color: RgbaColor | None = None
    last_mask: int = 0xFF
    target: Placement = field(default_factory=Placement)
    target_row: int = GLOBAL_BASE_TERRAIN_Y - 1
    intent: str = "starting"

    def rebuild_global_map(self) -> None:
        if self.map.width <= 0 or self.map.height <= 0:
            return
        pixels = bytearray(self.map.width * self.map.height * 4)
        for offset in range(3, len(pixels), 4):
            pixels[offset] = 255

        items = sorted(self.objects.values(), key=lambda item: (item.z, item.y, item.id))
        for item in items:
            sprite = self.sprites.get(item.sprite_id)
            if sprite is None:
                continue
            for sy in range(sprite.height):
                dst_y = item.y + sy
                if dst_y < 0 or dst_y >= self.map.height:
                    continue
                for sx in range(sprite.width):
                    dst_x = item.x + sx
                    if dst_x < 0 or dst_x >= self.map.width:
                        continue
                    src = (sy * sprite.width + sx) * 4
                    if sprite.pixels[src + 3] == 0:
                        continue
                    dst = (dst_y * self.map.width + dst_x) * 4
                    pixels[dst : dst + 4] = sprite.pixels[src : src + 4]

        self.map.pixels = bytes(pixels)

    def update_own_color(self) -> None:
        if self.own_color is not None or not self.player_frame.pixels:
            return
        counts: dict[RgbaColor, int] = {}
        pixels = self.player_frame.pixels
        for offset in range(0, len(pixels) - 3, 4):
            color = (pixels[offset], pixels[offset + 1], pixels[offset + 2], pixels[offset + 3])
            if looks_like_player_color(color):
                counts[color] = counts.get(color, 0) + 1
        if not counts:
            return
        color, count = max(counts.items(), key=lambda item: item[1])
        if count >= 4:
            self.own_color = color
            print(f"pystack color rgb={color[0]},{color[1]},{color[2]}", flush=True)

    def apply_sprite_packet(self, packet: bytes, player_frame: bool) -> bool:
        offset = 0
        changed = False
        while offset < len(packet):
            message_type = packet[offset]
            offset += 1
            if message_type == 0x01:
                if offset + 10 > len(packet):
                    return False
                sprite_id = read_u16(packet, offset)
                width = read_u16(packet, offset + 2)
                height = read_u16(packet, offset + 4)
                compressed_len = read_u32(packet, offset + 6)
                offset += 10
                if compressed_len < 0 or offset + compressed_len + 2 > len(packet):
                    return False
                compressed = packet[offset : offset + compressed_len]
                offset += compressed_len
                label_len = read_u16(packet, offset)
                offset += 2
                if offset + label_len > len(packet):
                    return False
                label = packet[offset : offset + label_len].decode("utf-8", "replace")
                offset += label_len
                raw_pixels = decompress_snappy(compressed)
                if len(raw_pixels) != width * height * 4:
                    return False
                image = SpriteImage(width=width, height=height, label=label, pixels=raw_pixels)
                if player_frame:
                    self.player_frame = image
                    self.update_own_color()
                else:
                    self.sprites[sprite_id] = image
                changed = True
            elif message_type == 0x02:
                if offset + 11 > len(packet):
                    return False
                item = GlobalObject(
                    id=read_u16(packet, offset),
                    x=read_i16(packet, offset + 2),
                    y=read_i16(packet, offset + 4),
                    z=read_i16(packet, offset + 6),
                    layer=packet[offset + 8],
                    sprite_id=read_u16(packet, offset + 9),
                )
                offset += 11
                if not player_frame:
                    self.objects[item.id] = item
                    changed = True
            elif message_type == 0x03:
                if offset + 2 > len(packet):
                    return False
                object_id = read_u16(packet, offset)
                offset += 2
                if not player_frame:
                    self.objects.pop(object_id, None)
                    changed = True
            elif message_type == 0x04:
                if not player_frame:
                    self.objects.clear()
                    changed = True
            elif message_type == 0x05:
                if offset + 5 > len(packet):
                    return False
                if not player_frame:
                    self.map.width = read_u16(packet, offset + 1)
                    self.map.height = read_u16(packet, offset + 3)
                    changed = True
                offset += 5
            elif message_type == 0x06:
                if offset + 3 > len(packet):
                    return False
                offset += 3
            else:
                return False

        if changed and not player_frame:
            self.rebuild_global_map()
        return True

    def find_own_cells(self) -> list[Cell]:
        if self.own_color is None or not self.map.pixels:
            return []
        cells: list[Cell] = []
        for y in range(self.map.height):
            for x in range(self.map.width):
                if self.map.rgba_at(x, y) == self.own_color:
                    cells.append(Cell(x, y))
        return cells

    def active_piece(self) -> ActivePiece:
        own_cells = self.find_own_cells()
        if len(own_cells) < 4 or self.map.width <= 0 or self.map.height <= 0:
            return ActivePiece()
        own = set(own_cells)
        visited: set[Cell] = set()
        best_component: list[Cell] = []
        best_min_y = 10**12
        for cell in own_cells:
            if cell in visited:
                continue
            component = flood_component(cell, own, self.map.width, self.map.height, visited)
            min_y = min(item.y for item in component)
            if len(component) >= 4 and min_y < best_min_y:
                best_min_y = min_y
                best_component = component
        if len(best_component) < 4:
            return ActivePiece()
        best_component.sort(key=lambda item: (item.y, item.x))
        return infer_piece_from_cells(best_component[:4])

    def occupied_map(self, active: ActivePiece) -> list[bool]:
        occupied = [False] * (self.map.width * self.map.height)
        for y in range(self.map.height):
            for x in range(self.map.width):
                occupied[y * self.map.width + x] = not is_background(self.map.rgba_at(x, y))
        for cell in active.cells:
            if 0 <= cell.x < self.map.width and 0 <= cell.y < self.map.height:
                occupied[cell.y * self.map.width + cell.x] = False
        return occupied

    def decide_mask(self) -> int:
        if self.own_color is None or not self.map.pixels:
            self.intent = "waiting"
            return BUTTON_DOWN

        active = self.active_piece()
        if not active.found:
            self.intent = "finding piece"
            return BUTTON_DOWN

        occupied = self.occupied_map(active)
        lane_start = self.map.width // 2 - LINE_CLEAR_LENGTH // 2
        bottom_row = min(GLOBAL_BASE_TERRAIN_Y - 1, self.map.height - 2)
        placement, self.target_row = choose_placement(
            occupied, self.map.width, self.map.height, lane_start, bottom_row, active
        )
        self.target = placement
        return steering_mask(self, active, placement)


@dataclass
class FramePystack:
    frame_tick: int = 0
    last_mask: int = 0xFF
    target: Placement = field(default_factory=Placement)
    target_row: int = FRAME_GRID_HEIGHT - 2
    intent: str = "starting"
    own_color_index: int | None = None

    def grid_from_frame(self, packed: bytes) -> list[int]:
        pixels = unpack_4bpp(packed)
        grid = [0] * (FRAME_GRID_WIDTH * FRAME_GRID_HEIGHT)
        for gy in range(FRAME_GRID_HEIGHT):
            for gx in range(FRAME_GRID_WIDTH):
                counts: dict[int, int] = {}
                for py in range(CELL_PIXELS):
                    for px in range(CELL_PIXELS):
                        sx = gx * CELL_PIXELS + px
                        sy = gy * CELL_PIXELS + py
                        value = pixels[sy * SCREEN_WIDTH + sx] & 0x0F
                        counts[value] = counts.get(value, 0) + 1
                grid[gy * FRAME_GRID_WIDTH + gx] = max(counts.items(), key=lambda item: item[1])[0]
        return grid

    def active_piece(self, grid: list[int]) -> ActivePiece:
        candidates: set[Cell] = set()
        for y in range(FRAME_IGNORE_TOP_CELLS, FRAME_GRID_HEIGHT):
            for x in range(FRAME_GRID_WIDTH):
                color = grid[y * FRAME_GRID_WIDTH + x]
                if color not in PLAYER_COLOR_INDICES:
                    continue
                if self.own_color_index is not None and color != self.own_color_index:
                    continue
                candidates.add(Cell(x, y))

        visited: set[Cell] = set()
        best_component: list[Cell] = []
        best_min_y = 10**12
        best_color = self.own_color_index
        for cell in list(candidates):
            if cell in visited:
                continue
            color = grid[cell.y * FRAME_GRID_WIDTH + cell.x]
            component = flood_component(cell, candidates, FRAME_GRID_WIDTH, FRAME_GRID_HEIGHT, visited)
            min_y = min(item.y for item in component)
            if len(component) >= 4 and min_y < best_min_y:
                best_min_y = min_y
                best_component = component
                best_color = color

        if len(best_component) < 4:
            if self.own_color_index is not None:
                self.own_color_index = None
                return self.active_piece(grid)
            return ActivePiece()

        if self.own_color_index is None and best_color in PLAYER_COLOR_INDICES:
            self.own_color_index = best_color
        best_component.sort(key=lambda item: (item.y, item.x))
        return infer_piece_from_cells(best_component[:4])

    def bottom_row(self, grid: list[int]) -> int:
        for y in range(FRAME_IGNORE_TOP_CELLS, FRAME_GRID_HEIGHT):
            terrain_count = sum(
                1 for x in range(FRAME_GRID_WIDTH) if grid[y * FRAME_GRID_WIDTH + x] == TERRAIN_COLOR_INDEX
            )
            if terrain_count >= FRAME_GRID_WIDTH * 3 // 4:
                return max(0, y - 1)
        return FRAME_GRID_HEIGHT - 2

    def occupied_map(self, grid: list[int], active: ActivePiece) -> list[bool]:
        occupied = [False] * (FRAME_GRID_WIDTH * FRAME_GRID_HEIGHT)
        active_cells = set(active.cells)
        for y in range(FRAME_GRID_HEIGHT):
            for x in range(FRAME_GRID_WIDTH):
                if y < FRAME_IGNORE_TOP_CELLS:
                    continue
                if Cell(x, y) in active_cells:
                    continue
                color = grid[y * FRAME_GRID_WIDTH + x]
                occupied[y * FRAME_GRID_WIDTH + x] = color != BACKGROUND_COLOR_INDEX
        return occupied

    def decide_mask(self, packed: bytes) -> int:
        if len(packed) != PROTOCOL_BYTES:
            self.intent = "waiting for framebuffer"
            return BUTTON_DOWN

        grid = self.grid_from_frame(packed)
        active = self.active_piece(grid)
        if not active.found:
            self.intent = "finding piece"
            return BUTTON_DOWN

        occupied = self.occupied_map(grid, active)
        lane_start = FRAME_GRID_WIDTH // 2 - LINE_CLEAR_LENGTH // 2
        bottom_row = self.bottom_row(grid)
        placement, self.target_row = choose_placement(
            occupied, FRAME_GRID_WIDTH, FRAME_GRID_HEIGHT, lane_start, bottom_row, active
        )
        self.target = placement
        return steering_mask(self, active, placement)


def flood_component(
    start: Cell,
    candidates: set[Cell],
    width: int,
    height: int,
    visited: set[Cell],
) -> list[Cell]:
    queue: deque[Cell] = deque([start])
    visited.add(start)
    component: list[Cell] = []
    while queue:
        current = queue.popleft()
        component.append(current)
        for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
            nxt = Cell(current.x + dx, current.y + dy)
            if nxt.x < 0 or nxt.y < 0 or nxt.x >= width or nxt.y >= height:
                continue
            if nxt not in candidates or nxt in visited:
                continue
            visited.add(nxt)
            queue.append(nxt)
    return component


def steering_mask(bot: GlobalPystack | FramePystack, active: ActivePiece, placement: Placement) -> int:
    if not placement.found:
        bot.intent = "dropping"
        return BUTTON_DOWN
    if active.rotation != placement.rotation:
        bot.intent = "rotate"
        if (bot.last_mask & BUTTON_A) == 0:
            return BUTTON_A
        return 0
    if active.origin_x < placement.x:
        bot.intent = "right"
        return BUTTON_RIGHT
    if active.origin_x > placement.x:
        bot.intent = "left"
        return BUTTON_LEFT
    bot.intent = f"fill row {bot.target_row}"
    mask = BUTTON_DOWN
    if active.origin_y >= placement.y - 1:
        mask |= BUTTON_SELECT
    return mask


def echo_debug(bot: GlobalPystack | FramePystack, mask: int, debug_interval: int) -> None:
    if debug_interval <= 0 or bot.frame_tick % debug_interval != 0:
        return
    print(
        "step="
        f"{bot.frame_tick} keys={mask_summary(mask)} intent={bot.intent} "
        f"targetRow={bot.target_row} target={bot.target.x},{bot.target.y} "
        f"rot={bot.target.rotation} score={bot.target.score}",
        flush=True,
    )


def set_query_param(query: str, key: str, value: str) -> str:
    if not value:
        return query
    pairs = parse_qsl(query, keep_blank_values=True)
    replaced = False
    output: list[tuple[str, str]] = []
    for pair_key, pair_value in pairs:
        if pair_key == key:
            output.append((key, value))
            replaced = True
        else:
            output.append((pair_key, pair_value))
    if not replaced:
        output.append((key, value))
    return urlencode(output, quote_via=quote)


def ensure_player_path(url: str) -> str:
    parsed = urlsplit(url)
    if parsed.path:
        if parsed.path.endswith("/sprite_player"):
            return urlunsplit((parsed.scheme, parsed.netloc, PLAYER_WEBSOCKET_PATH, parsed.query, parsed.fragment))
        return url
    return urlunsplit((parsed.scheme, parsed.netloc, PLAYER_WEBSOCKET_PATH, parsed.query, parsed.fragment))


def normalize_player_url(url: str, name: str, slot: int, token: str) -> str:
    normalized = ensure_player_path(url)
    parsed = urlsplit(normalized)
    query = parsed.query
    player_name = name or "pystack"
    query = set_query_param(query, "name", player_name)
    if slot >= 0:
        query = set_query_param(query, "slot", str(slot))
    query = set_query_param(query, "token", token)
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, query, parsed.fragment))


def sprite_url(host: str, port: int, name: str, slot: int, token: str) -> str:
    return normalize_player_url(f"ws://{host}:{port}{PLAYER_WEBSOCKET_PATH}", name, slot, token)


def global_url(host: str, port: int) -> str:
    return f"ws://{host}:{port}{GLOBAL_WEBSOCKET_PATH}"


def derive_global_url(player_url: str) -> str:
    parsed = urlsplit(player_url)
    return urlunsplit((parsed.scheme, parsed.netloc, GLOBAL_WEBSOCKET_PATH, "", ""))


async def receive_global_updates(ws, bot: GlobalPystack, player_frame: bool, timeout: float | None) -> bool:
    try:
        if timeout is None:
            first = await ws.recv()
        else:
            first = await asyncio.wait_for(ws.recv(), timeout=timeout)
    except asyncio.TimeoutError:
        return False

    changed = False
    if isinstance(first, bytes):
        changed = bot.apply_sprite_packet(first, player_frame)

    drained = 0
    while drained < MAX_DRAIN_MESSAGES:
        try:
            message = await asyncio.wait_for(ws.recv(), timeout=0.001)
        except asyncio.TimeoutError:
            break
        if isinstance(message, bytes) and bot.apply_sprite_packet(message, player_frame):
            changed = True
        drained += 1
    return changed


async def run_global_mode(
    websockets,
    player_url: str,
    map_url: str,
    max_steps: int,
    debug_interval: int,
) -> None:
    bot = GlobalPystack(random.Random(time.time_ns() ^ os.getpid()))
    async with websockets.connect(player_url, ping_interval=None) as player_ws:
        async with websockets.connect(map_url, ping_interval=None) as global_ws:
            await player_ws.send(chat_packet("pystack online", "sprite"))
            await receive_global_updates(player_ws, bot, True, None)
            await receive_global_updates(global_ws, bot, False, None)
            last_sent_mask = 0xFF
            while True:
                if not await receive_global_updates(global_ws, bot, False, None):
                    continue
                bot.frame_tick += 1
                await receive_global_updates(player_ws, bot, True, 0.001)
                next_mask = bot.decide_mask()
                echo_debug(bot, next_mask, debug_interval)
                bot.last_mask = next_mask
                if next_mask != last_sent_mask:
                    await player_ws.send(input_packet(next_mask, "sprite"))
                    last_sent_mask = next_mask
                if max_steps > 0 and bot.frame_tick >= max_steps:
                    return


async def run_framebuffer_mode(
    websockets,
    player_url: str,
    max_steps: int,
    debug_interval: int,
) -> None:
    bot = FramePystack()
    async with websockets.connect(player_url, ping_interval=None) as player_ws:
        await player_ws.send(chat_packet("pystack online", "framebuffer"))
        last_sent_mask = 0xFF
        while True:
            message = await player_ws.recv()
            if not isinstance(message, bytes):
                continue
            if len(message) != PROTOCOL_BYTES:
                continue
            bot.frame_tick += 1
            next_mask = bot.decide_mask(message)
            echo_debug(bot, next_mask, debug_interval)
            bot.last_mask = next_mask
            if next_mask != last_sent_mask:
                await player_ws.send(input_packet(next_mask, "framebuffer"))
                last_sent_mask = next_mask
            if max_steps > 0 and bot.frame_tick >= max_steps:
                return


async def run_bot(args: argparse.Namespace) -> None:
    try:
        import websockets
    except ImportError as exc:
        raise SystemExit("Missing dependency: install requirements.txt or build the Docker image") from exc

    player_url_value = (
        normalize_player_url(args.url, args.name, args.slot, args.token)
        if args.url
        else sprite_url(args.address, args.port, args.name, args.slot, args.token)
    )
    map_url_value = args.global_url or (derive_global_url(player_url_value) if args.url else global_url(args.address, args.port))

    while True:
        try:
            if args.mode == "global":
                await run_global_mode(websockets, player_url_value, map_url_value, args.max_steps, args.debug_interval)
                return
            if args.mode == "framebuffer":
                await run_framebuffer_mode(websockets, player_url_value, args.max_steps, args.debug_interval)
                return

            try:
                async with websockets.connect(map_url_value, open_timeout=2, ping_interval=None):
                    pass
                await run_global_mode(websockets, player_url_value, map_url_value, args.max_steps, args.debug_interval)
            except Exception as exc:
                print(f"pystack falling back to framebuffer protocol: {exc}", flush=True)
                await run_framebuffer_mode(websockets, player_url_value, args.max_steps, args.debug_interval)
            return
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            if args.max_steps > 0:
                raise
            print(f"pystack reconnecting: {exc}", flush=True)
            await asyncio.sleep(0.25)


def normalize_cli_args(argv: list[str]) -> list[str]:
    """Accept the BitWorld/Nim runner's argv shape in Python argparse."""

    normalized: list[str] = []
    for index, arg in enumerate(argv):
        if index == 0 and arg.rsplit("/", 1)[-1] in {"pystack", "pystack.py"}:
            continue
        if arg.startswith("--"):
            body = arg[2:]
            colon_index = body.find(":")
            equals_index = body.find("=")
            if colon_index > 0 and (equals_index < 0 or colon_index < equals_index):
                normalized.append(f"--{body[:colon_index]}={body[colon_index + 1:]}")
                continue
        normalized.append(arg)
    return normalized


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Python Infinite Blocks pystack bot")
    parser.add_argument("--address", default="localhost")
    parser.add_argument("--port", type=int, default=PLAYER_DEFAULT_PORT)
    parser.add_argument("--name", default="")
    parser.add_argument("--url", "--player-url", "--socket", dest="url", default=os.getenv(ENGINE_WS_ENV, ""))
    parser.add_argument("--global-url", default="")
    parser.add_argument("--token", default="")
    parser.add_argument("--slot", type=int, default=-1)
    parser.add_argument("--max-steps", type=int, default=0)
    parser.add_argument("--debug-interval", type=int, default=DEBUG_INTERVAL)
    parser.add_argument(
        "--mode",
        choices=("auto", "global", "framebuffer"),
        default="auto",
        help="auto tries the optional /global protocol, then falls back to /player frames",
    )
    return parser.parse_args(normalize_cli_args(argv))


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    try:
        asyncio.run(run_bot(args))
    except KeyboardInterrupt:
        return 130
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
