"""Coordinate and camera math.

Pure functions. Port of ``geometry.nim``. No side effects; every proc is
a simple arithmetic helper.

Two coordinate systems are in play:

- **World** coordinates: pixel positions inside the 952×534 map. This is
  what tasks, rooms, vents, the emergency button, and the ``home`` point
  live in.
- **Screen** coordinates: 128×128 with the player sprite's visual centre
  at :data:`PLAYER_SCREEN_X` / :data:`PLAYER_SCREEN_Y`. The camera X/Y
  is the world offset of the screen's top-left pixel.

The player's collision box is drawn at a small offset from the screen
centre (:data:`PLAYER_WORLD_OFF_X` / ``Y``), so inferring world-position
from a locked camera is ``camera + PLAYER_WORLD_OFF``.
"""

from __future__ import annotations

from .data import (
    MAP_HEIGHT,
    MAP_WIDTH,
    SCREEN_HEIGHT,
    SCREEN_WIDTH,
    SPRITE_DRAW_OFF_X,
    SPRITE_DRAW_OFF_Y,
    SPRITE_SIZE,
    GameMap,
    Rect,
    TaskStation,
)
from .state import Perception

PLAYER_SCREEN_X = SCREEN_WIDTH // 2
PLAYER_SCREEN_Y = SCREEN_HEIGHT // 2
PLAYER_WORLD_OFF_X = SPRITE_DRAW_OFF_X + PLAYER_SCREEN_X - SPRITE_SIZE // 2
PLAYER_WORLD_OFF_Y = SPRITE_DRAW_OFF_Y + PLAYER_SCREEN_Y - SPRITE_SIZE // 2


def min_camera_x() -> int:
    """Smallest centred camera X (half-screen + sprite overhang)."""
    return -SCREEN_WIDTH // 2 - SPRITE_SIZE


def max_camera_x() -> int:
    return MAP_WIDTH - SCREEN_WIDTH // 2 + SPRITE_SIZE


def min_camera_y() -> int:
    return -SCREEN_HEIGHT // 2 - SPRITE_SIZE


def max_camera_y() -> int:
    return MAP_HEIGHT - SCREEN_HEIGHT // 2 + SPRITE_SIZE


def camera_index(x: int, y: int) -> int:
    """Linear index into the localizer's vote/hash table for one camera offset."""
    return (y - min_camera_y()) * (max_camera_x() - min_camera_x() + 1) + (x - min_camera_x())


def camera_index_x(idx: int) -> int:
    return min_camera_x() + idx % (max_camera_x() - min_camera_x() + 1)


def camera_index_y(idx: int) -> int:
    return min_camera_y() + idx // (max_camera_x() - min_camera_x() + 1)


def button_camera_x(game_map: GameMap) -> int:
    """Initial camera X guess centred on the emergency button."""
    b = game_map.button
    return max(min_camera_x(), min(max_camera_x(), b.x + b.w // 2 - PLAYER_WORLD_OFF_X))


def button_camera_y(game_map: GameMap) -> int:
    b = game_map.button
    return max(min_camera_y(), min(max_camera_y(), b.y + b.h // 2 - PLAYER_WORLD_OFF_Y))


def camera_x_for_world(x: int) -> int:
    """Camera X that centres one world X on the player."""
    return max(min_camera_x(), min(max_camera_x(), x - PLAYER_WORLD_OFF_X))


def camera_y_for_world(y: int) -> int:
    return max(min_camera_y(), min(max_camera_y(), y - PLAYER_WORLD_OFF_Y))


def in_map(x: int, y: int) -> bool:
    """True when a world pixel is inside the map rectangle."""
    return 0 <= x < MAP_WIDTH and 0 <= y < MAP_HEIGHT


def camera_can_hold_player(cx: int, cy: int) -> bool:
    """True when this camera puts the player's world position inside the map."""
    return in_map(cx + PLAYER_WORLD_OFF_X, cy + PLAYER_WORLD_OFF_Y)


def player_world_x(p: Perception) -> int:
    """Inferred player collision X."""
    return p.camera_x + PLAYER_WORLD_OFF_X


def player_world_y(p: Perception) -> int:
    return p.camera_y + PLAYER_WORLD_OFF_Y


def room_name_at(game_map: GameMap, x: int, y: int) -> str:
    for room in game_map.rooms:
        if room.x <= x < room.x + room.w and room.y <= y < room.y + room.h:
            return room.name
    return "unknown"


def room_name(p: Perception, game_map: GameMap) -> str:
    """Room containing the inferred player position, or ``'unknown'``."""
    if not p.localized:
        return "unknown"
    return room_name_at(game_map, player_world_x(p), player_world_y(p))


def task_center(task: TaskStation) -> tuple[int, int]:
    return (task.cx, task.cy)


def visible_crewmate_world(p: Perception, cx: int, cy: int) -> tuple[int, int]:
    """Convert a screen-coord sprite anchor to world coordinates."""
    return (p.camera_x + cx + SPRITE_DRAW_OFF_X, p.camera_y + cy + SPRITE_DRAW_OFF_Y)


def visible_body_world(p: Perception, bx: int, by: int) -> tuple[int, int]:
    return (p.camera_x + bx + SPRITE_DRAW_OFF_X, p.camera_y + by + SPRITE_DRAW_OFF_Y)


def central_room_center(game_map: GameMap) -> tuple[int, int]:
    """Reference point for the central (button) room."""
    b = game_map.button
    return (b.x + b.w // 2, b.y + b.h // 2)


def central_room_name(game_map: GameMap) -> str:
    cx, cy = central_room_center(game_map)
    return room_name_at(game_map, cx, cy)


def in_central_room(p: Perception, game_map: GameMap) -> bool:
    if not p.localized:
        return False
    central = central_room_name(game_map)
    return central != "unknown" and room_name(p, game_map) == central


def heuristic(ax: int, ay: int, bx: int, by: int) -> int:
    """Manhattan distance — used by A* and by distance-comparison sorting."""
    return abs(ax - bx) + abs(ay - by)


__all__ = [
    "PLAYER_SCREEN_X",
    "PLAYER_SCREEN_Y",
    "PLAYER_WORLD_OFF_X",
    "PLAYER_WORLD_OFF_Y",
    "min_camera_x",
    "max_camera_x",
    "min_camera_y",
    "max_camera_y",
    "camera_index",
    "camera_index_x",
    "camera_index_y",
    "button_camera_x",
    "button_camera_y",
    "camera_x_for_world",
    "camera_y_for_world",
    "in_map",
    "camera_can_hold_player",
    "player_world_x",
    "player_world_y",
    "room_name_at",
    "room_name",
    "task_center",
    "visible_crewmate_world",
    "visible_body_world",
    "central_room_center",
    "central_room_name",
    "in_central_room",
    "heuristic",
]
