"""Camera / world coordinate math. Port of the localize-relevant subset
of ``users/james/personal_cogs/among_them/guided_bot/perception/geometry.nim``.

Two coordinate systems are in play:

- **World** coordinates: pixel positions inside the 952x534 map.
  Tasks, rooms, vents, the emergency button, and the home point all
  live in world coordinates.
- **Screen** coordinates: 128x128 with the player sprite's visual centre
  near (64, 64). The camera ``(cx, cy)`` is the world offset of the
  screen's top-left pixel.

The player's collision-box centre is offset from the camera origin by
``PLAYER_WORLD_OFF_(X|Y)`` because the drawn sprite anchor is shifted
from its hit-box centre.

All functions here are pure: no module state, no allocation. They're
hot in :func:`localize.update_location`'s local-refit path and in
downstream consumers that convert between camera and world coordinates.
"""

from __future__ import annotations

from .data import (
    BUTTON_H,
    BUTTON_W,
    BUTTON_X,
    BUTTON_Y,
    MAP_HEIGHT,
    MAP_WIDTH,
    SPRITE_DRAW_OFF_X,
    SPRITE_DRAW_OFF_Y,
    SPRITE_SIZE,
)
from .frame import SCREEN_HEIGHT, SCREEN_WIDTH

# --- Player sprite anchor (screen) + collision-box offset (world) ---------

# Screen-space anchor of the player sprite (the renderer centres the
# player and scrolls the map under them). Distinct from
# `ignore.PLAYER_SPRITE_ANCHOR_*`, which names the *drawn* sprite anchor
# used to seed the ignore-mask exclusion zone.
PLAYER_SCREEN_X = SCREEN_WIDTH // 2  # 64
PLAYER_SCREEN_Y = SCREEN_HEIGHT // 2  # 64

# World-space offset from the camera origin to the player's inferred
# collision-box centre. `PlayerWorldOffX = SpriteDrawOffX + PlayerScreenX
# - SpriteSize // 2`, verbatim from upstream geometry.nim. With the
# constants we have: 2 + 64 - 6 = 60 (X), 8 + 64 - 6 = 66 (Y).
PLAYER_WORLD_OFF_X = SPRITE_DRAW_OFF_X + PLAYER_SCREEN_X - (SPRITE_SIZE // 2)
PLAYER_WORLD_OFF_Y = SPRITE_DRAW_OFF_Y + PLAYER_SCREEN_Y - (SPRITE_SIZE // 2)


# --- Camera bounds --------------------------------------------------------


def min_camera_x() -> int:
    return -SCREEN_WIDTH // 2 - SPRITE_SIZE


def max_camera_x() -> int:
    return MAP_WIDTH - SCREEN_WIDTH // 2 + SPRITE_SIZE


def min_camera_y() -> int:
    return -SCREEN_HEIGHT // 2 - SPRITE_SIZE


def max_camera_y() -> int:
    return MAP_HEIGHT - SCREEN_HEIGHT // 2 + SPRITE_SIZE


def camera_width() -> int:
    return max_camera_x() - min_camera_x() + 1


def camera_height() -> int:
    return max_camera_y() - min_camera_y() + 1


# --- World ↔ camera helpers ----------------------------------------------


def _clamp(v: int, lo: int, hi: int) -> int:
    return lo if v < lo else hi if v > hi else v


def button_camera_x() -> int:
    """Initial camera X centred on the emergency button. Clamped to the
    camera range so off-edge buttons don't push the seed out of bounds."""
    target = BUTTON_X + BUTTON_W // 2 - PLAYER_WORLD_OFF_X
    return _clamp(target, min_camera_x(), max_camera_x())


def button_camera_y() -> int:
    target = BUTTON_Y + BUTTON_H // 2 - PLAYER_WORLD_OFF_Y
    return _clamp(target, min_camera_y(), max_camera_y())


def camera_x_for_world(world_x: int) -> int:
    """Camera X that puts world ``world_x`` on the player."""
    return _clamp(world_x - PLAYER_WORLD_OFF_X, min_camera_x(), max_camera_x())


def camera_y_for_world(world_y: int) -> int:
    return _clamp(world_y - PLAYER_WORLD_OFF_Y, min_camera_y(), max_camera_y())


def in_map(world_x: int, world_y: int) -> bool:
    return 0 <= world_x < MAP_WIDTH and 0 <= world_y < MAP_HEIGHT


def camera_can_hold_player(cx: int, cy: int) -> bool:
    """True when the camera puts the player's inferred world position
    inside the map rectangle. Used by localize to filter impossible
    candidates the patch-vote step would otherwise score."""
    return in_map(cx + PLAYER_WORLD_OFF_X, cy + PLAYER_WORLD_OFF_Y)


def player_world_x(camera_x: int) -> int:
    return camera_x + PLAYER_WORLD_OFF_X


def player_world_y(camera_y: int) -> int:
    return camera_y + PLAYER_WORLD_OFF_Y
