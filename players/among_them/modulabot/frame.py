"""Frame-buffer helpers + the dynamic-pixel ignore mask.

Port of ``frame.nim``. Two jobs:

1. Unpack the 4-bit packed frame the BitWorld websocket sends into one
   byte per palette index. (Cogames already hands us unpacked frames in
   a ``(frame_stack, 128, 128) uint8`` array, so this module's unpack
   function is mostly here for tests and any direct websocket path we
   add later.)
2. Provide :func:`ignore_frame_pixel`, the predicate the localizer's
   map-scoring loop uses to skip "dynamic" screen pixels (player, other
   crewmates, bodies, ghosts, task icons, radar dots, HUD icons).

Everything downstream of the perception layer should call
:func:`ignore_frame_pixel` instead of re-implementing its seven sub-checks.

Shape convention: every frame passed in is a ``(128, 128) uint8`` array
— the single most recent frame from the observation stack. Upstream
callers take care of picking the last frame.
"""

from __future__ import annotations

import numpy as np

from .data import (
    SCREEN_HEIGHT,
    SCREEN_WIDTH,
    SPRITE_SIZE,
    Sprite,
    Sprites,
    TRANSPARENT_INDEX,
)
from .geometry import PLAYER_SCREEN_X, PLAYER_SCREEN_Y
from .state import (
    BodySighting,
    Bot,
    Perception,
    PlayerSighting,
    Role,
)

#: Palette index used for offscreen-task radar dots. Yellow in the
#: bitworld palette. Masked out of map-fit scoring.
RADAR_TASK_COLOR = 8

#: Half-extent (in screen pixels) of the centred player-sprite mask.
#: Pixels within this radius of screen centre are excluded from map-fit
#: scoring without requiring a sprite-shape match.
PLAYER_IGNORE_RADIUS = 9

KILL_ICON_X = 1
KILL_ICON_Y = SCREEN_HEIGHT - SPRITE_SIZE - 1


# ---------------------------------------------------------------------------
# Pixel unpacking
# ---------------------------------------------------------------------------


def unpack4bpp(packed: np.ndarray) -> np.ndarray:
    """Expand a 1-D packed 4-bit frame into a ``(128, 128) uint8`` frame.

    Accepts ``packed.shape == (PACKED_FRAME_BYTES,)`` i.e. 8192 bytes.
    """
    if packed.ndim != 1:
        packed = packed.reshape(-1)
    pixels = np.empty(packed.shape[0] * 2, dtype=np.uint8)
    pixels[0::2] = packed & 0x0F
    pixels[1::2] = packed >> 4
    return pixels.reshape(SCREEN_HEIGHT, SCREEN_WIDTH)


# ---------------------------------------------------------------------------
# Sprite coverage primitive
# ---------------------------------------------------------------------------


def sprite_covers(
    sprite: Sprite, anchor_x: int, anchor_y: int, sx: int, sy: int, flip_h: bool = False
) -> bool:
    """True when ``(sx, sy)`` falls inside the non-transparent footprint of ``sprite``.

    Matches ``spriteCovers`` in ``frame.nim``. Every ignore predicate in
    this module is implemented as a loop over the relevant match list
    calling this function.
    """
    ix = sx - anchor_x
    iy = sy - anchor_y
    if ix < 0 or iy < 0 or ix >= sprite.width or iy >= sprite.height:
        return False
    src_x = sprite.width - 1 - ix if flip_h else ix
    return bool(sprite.pixels[iy, src_x] != TRANSPARENT_INDEX)


# ---------------------------------------------------------------------------
# Per-source ignore predicates
# ---------------------------------------------------------------------------


def _covers_any(matches, sprite: Sprite, sx: int, sy: int, flip_attr: str | None = None) -> bool:
    for m in matches:
        flip_h = bool(getattr(m, flip_attr)) if flip_attr else False
        if sprite_covers(sprite, m.x, m.y, sx, sy, flip_h):
            return True
    return False


def ignore_task_icon_pixel(bot: Bot, sprites: Sprites, sx: int, sy: int) -> bool:
    # Task icons don't carry a flipH; iterate directly.
    for m in bot.percep.visible_task_icons:
        if sprite_covers(sprites.task, m.x, m.y, sx, sy):
            return True
    return False


def ignore_crewmate_pixel(bot: Bot, sprites: Sprites, sx: int, sy: int) -> bool:
    for cm in bot.percep.players:
        if cm.is_self:
            continue
        if sprite_covers(sprites.player, cm.x, cm.y, sx, sy, flip_h=False):
            return True
    return False


def ignore_body_pixel(bot: Bot, sprites: Sprites, sx: int, sy: int) -> bool:
    for b in bot.percep.bodies:
        if sprite_covers(sprites.body, b.x, b.y, sx, sy):
            return True
    return False


def ignore_kill_icon_pixel(bot: Bot, sprites: Sprites, sx: int, sy: int) -> bool:
    if bot.role != Role.IMPOSTER:
        return False
    return sprite_covers(sprites.kill_button, KILL_ICON_X, KILL_ICON_Y, sx, sy)


def ignore_ghost_icon_pixel(bot: Bot, sprites: Sprites, sx: int, sy: int) -> bool:
    if not bot.is_ghost and getattr(bot, "ghost_icon_frames", 0) == 0:
        return False
    return sprite_covers(sprites.ghost_icon, KILL_ICON_X, KILL_ICON_Y, sx, sy)


def ignore_frame_pixel(bot: Bot, sprites: Sprites, frame_color: int, sx: int, sy: int) -> bool:
    """True for dynamic screen pixels the localizer should skip.

    Cheap checks come first (frame colour, HUD icons that happen at a
    fixed position) before the expensive list-iterating match checks.
    Do not reorder.
    """
    if frame_color == RADAR_TASK_COLOR:
        return True
    if ignore_kill_icon_pixel(bot, sprites, sx, sy):
        return True
    if ignore_ghost_icon_pixel(bot, sprites, sx, sy):
        return True
    if ignore_body_pixel(bot, sprites, sx, sy):
        return True
    if ignore_task_icon_pixel(bot, sprites, sx, sy):
        return True
    if ignore_crewmate_pixel(bot, sprites, sx, sy):
        return True
    # Player sprite mask around screen centre.
    return (
        abs(sx - PLAYER_SCREEN_X) <= PLAYER_IGNORE_RADIUS
        and abs(sy - PLAYER_SCREEN_Y) <= PLAYER_IGNORE_RADIUS
    )


# ---------------------------------------------------------------------------
# Vectorised per-frame ignore mask
# ---------------------------------------------------------------------------


def _stamp_sprite_mask(
    mask: np.ndarray,
    sprite: Sprite,
    anchor_x: int,
    anchor_y: int,
    flip_h: bool = False,
) -> None:
    """Set ``mask[y, x] = True`` for every non-transparent sprite pixel.

    Handles partial off-screen sprites (anchor can be negative or near
    the frame edge). Used to build the localizer's dynamic-pixel
    exclusion mask in one pass per sprite instance.
    """
    sh, sw = sprite.height, sprite.width
    pixels = sprite.pixels[:, ::-1] if flip_h else sprite.pixels

    y0 = max(anchor_y, 0)
    x0 = max(anchor_x, 0)
    y1 = min(anchor_y + sh, SCREEN_HEIGHT)
    x1 = min(anchor_x + sw, SCREEN_WIDTH)
    if y1 <= y0 or x1 <= x0:
        return

    sy0 = y0 - anchor_y
    sx0 = x0 - anchor_x
    sy1 = sy0 + (y1 - y0)
    sx1 = sx0 + (x1 - x0)
    opaque = pixels[sy0:sy1, sx0:sx1] != TRANSPARENT_INDEX
    mask[y0:y1, x0:x1] |= opaque


def compute_ignore_mask(bot: Bot, sprites: Sprites, frame: np.ndarray) -> np.ndarray:
    """Return a ``(128, 128) bool`` mask of screen pixels to skip when scoring.

    Vectorised equivalent of running :func:`ignore_frame_pixel` for
    every ``(sx, sy)`` coordinate — used by :mod:`modulabot.localize`
    to compute map-fit scores without counting player-sprite,
    crewmate, body, ghost, task-icon, HUD-icon, or radar-dot pixels as
    errors.

    The mask is computed from the perception state currently on ``bot``
    (crewmate / body / ghost matches produced by the most recent
    :func:`modulabot.actors.scan_all` call), so callers should run the
    scanners before calling this. For the very first localisation on a
    round the scan will be empty and the mask will only cover the
    static centre-player zone + radar colour pixels; that's fine — the
    patch-hash global search tolerates small numbers of dynamic-pixel
    errors via its miss budget.
    """
    mask = np.zeros((SCREEN_HEIGHT, SCREEN_WIDTH), dtype=bool)

    # Radar colour is a single vectorised frame-compare.
    mask |= frame == RADAR_TASK_COLOR

    # Centred player-sprite exclusion zone (always present).
    y_lo = max(0, PLAYER_SCREEN_Y - PLAYER_IGNORE_RADIUS)
    y_hi = min(SCREEN_HEIGHT, PLAYER_SCREEN_Y + PLAYER_IGNORE_RADIUS + 1)
    x_lo = max(0, PLAYER_SCREEN_X - PLAYER_IGNORE_RADIUS)
    x_hi = min(SCREEN_WIDTH, PLAYER_SCREEN_X + PLAYER_IGNORE_RADIUS + 1)
    mask[y_lo:y_hi, x_lo:x_hi] = True

    # HUD icons (only stamped when the bot believes the icon is there).
    if bot.role == Role.IMPOSTER:
        _stamp_sprite_mask(mask, sprites.kill_button, KILL_ICON_X, KILL_ICON_Y)
    if bot.is_ghost or getattr(bot, "ghost_icon_frames", 0) > 0:
        _stamp_sprite_mask(mask, sprites.ghost_icon, KILL_ICON_X, KILL_ICON_Y)

    # Non-self players (state-obs derived sightings).
    for cm in bot.percep.players:
        if cm.is_self:
            continue
        _stamp_sprite_mask(mask, sprites.player, cm.x, cm.y)

    # Pixel-mode crewmate / body / ghost scans.
    for match in bot.percep.visible_crewmates:
        _stamp_sprite_mask(mask, sprites.player, match.x, match.y, flip_h=match.flip_h)
    for match in bot.percep.visible_bodies:
        _stamp_sprite_mask(mask, sprites.body, match.x, match.y)
    for match in bot.percep.visible_ghosts:
        _stamp_sprite_mask(mask, sprites.ghost, match.x, match.y, flip_h=match.flip_h)

    # Task icons.
    for match in bot.percep.visible_task_icons:
        _stamp_sprite_mask(mask, sprites.task, match.x, match.y)
    for body in bot.percep.bodies:
        _stamp_sprite_mask(mask, sprites.body, body.x, body.y)

    return mask


# ---------------------------------------------------------------------------
# Interstitial detection (cheap black-pixel check)
# ---------------------------------------------------------------------------

#: Minimum percentage of black pixels for a frame to be classified as an
#: interstitial (voting / role reveal / game over screen).
INTERSTITIAL_BLACK_PERCENT = 30


def looks_like_interstitial(frame: np.ndarray) -> bool:
    """True when the frame has more than :data:`INTERSTITIAL_BLACK_PERCENT` black pixels."""
    return int(np.count_nonzero(frame == 0)) * 100 >= INTERSTITIAL_BLACK_PERCENT * frame.size


__all__ = [
    "RADAR_TASK_COLOR",
    "PLAYER_IGNORE_RADIUS",
    "KILL_ICON_X",
    "KILL_ICON_Y",
    "INTERSTITIAL_BLACK_PERCENT",
    "unpack4bpp",
    "sprite_covers",
    "ignore_frame_pixel",
    "ignore_task_icon_pixel",
    "ignore_crewmate_pixel",
    "ignore_body_pixel",
    "ignore_kill_icon_pixel",
    "ignore_ghost_icon_pixel",
    "compute_ignore_mask",
    "looks_like_interstitial",
]
