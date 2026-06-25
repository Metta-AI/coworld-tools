"""Dynamic-pixel ignore-mask construction. Port of
``users/james/personal_cogs/among_them/guided_bot/perception/ignore.nim``.

Camera localization (S4.3) scores the frame against the static map
pixel-for-pixel. Anything on screen that *isn't* map — the player's
own sprite, other crewmates, bodies, ghosts, task icons, radar
dots, HUD icons — has to be masked out or it inflates the error
count and sends the localizer off-target. This module builds that
mask.

The mask is a `(SCREEN_HEIGHT, SCREEN_WIDTH)` bool ndarray;
``True`` = "ignore this pixel during map matching." Several
``stamp_*`` helpers accumulate ORs into a caller-provided mask;
:func:`build_phase_1_0_ignore_mask` is the high-level entry that
allocates a fresh mask and runs the always-on stamps for the
phase-1.0 (pre-localize) state.

In-place mutation of the mask via numpy boolean slice assignment
is intentional — it's the idiomatic numpy accumulator pattern.
This is distinct from the out-parameter mutation that was
removed from ``actors.py``: there the mutation was bookkeeping
spread across a dataclass; here it's accumulator ORs over a
single ndarray.

Per S4 dependency order, this module ships before localize lands.
Per-actor exclusions (the upstream phase-1.3 step that stamps
crewmate / body / ghost sprite rects + nameplates) are also
included here so the localize port can call them directly when
it lands; they're already exercised on the fixtures via the
existing actor matches.
"""

from __future__ import annotations

import numpy as np

from .data import RADAR_TASK_COLOR
from .frame import SCREEN_HEIGHT, SCREEN_WIDTH


# --- player-render anchor + ignore-zone half-extent -----------------------

# Half-extent (in screen pixels) of the centred player-sprite exclusion
# zone. Matches upstream `ignore.nim::PlayerIgnoreRadius`.
PLAYER_IGNORE_RADIUS: int = 9

# Screen coordinates where the player's sprite is *rendered* (used to
# anchor the ignore-mask exclusion zone). Distinct from a geometry
# module's player-collision-box centre — the two are off by one in X and
# four in Y because the drawn sprite anchor is offset from the hit-box
# centre. Mirrors upstream `ignore.nim::PlayerSpriteAnchorX/Y`.
PLAYER_SPRITE_ANCHOR_X: int = (SCREEN_WIDTH // 2) - 1   # = 63
PLAYER_SPRITE_ANCHOR_Y: int = (SCREEN_HEIGHT // 2) - 4  # = 60


# --- nameplate geometry ---------------------------------------------------

# The Among Them server renders each player's name above its sprite using
# the PICO-8 font (~5 px tall, ~4 px per glyph + 1 px spacing). Nameplates
# are centred horizontally on the sprite and drawn a few pixels above the
# sprite's top edge. Generous margins so variable-length names and
# slight vertical jitter are covered.
NAMEPLATE_HEIGHT: int = 7      # px above sprite top to cover text + gap
NAMEPLATE_HALF_WIDTH: int = 40  # px to each side of sprite centre — covers ~20 chars


# --- stamps (mutate the caller's mask in place) ---------------------------


def stamp_player_centre_zone(mask: np.ndarray) -> None:
    """Stamp the always-on player-sprite exclusion zone — a
    ``(2*PLAYER_IGNORE_RADIUS + 1)``-square block centred on the
    player's rendered position. Clamped to the screen rectangle."""
    y0 = max(0, PLAYER_SPRITE_ANCHOR_Y - PLAYER_IGNORE_RADIUS)
    y1 = min(SCREEN_HEIGHT, PLAYER_SPRITE_ANCHOR_Y + PLAYER_IGNORE_RADIUS + 1)
    x0 = max(0, PLAYER_SPRITE_ANCHOR_X - PLAYER_IGNORE_RADIUS)
    x1 = min(SCREEN_WIDTH, PLAYER_SPRITE_ANCHOR_X + PLAYER_IGNORE_RADIUS + 1)
    mask[y0:y1, x0:x1] = True


def stamp_radar_pixels(mask: np.ndarray, frame: np.ndarray) -> None:
    """Stamp every pixel whose palette value is :data:`RADAR_TASK_COLOR`.
    Whole-frame scan; vectorised as one boolean broadcast OR."""
    mask |= frame == RADAR_TASK_COLOR


def stamp_sprite_rect(mask: np.ndarray, x: int, y: int, w: int, h: int) -> None:
    """Stamp a rectangular sprite bounding box into ``mask``. Used by the
    phase-1.3 actor-exclusion step to mask out detected crewmate / body /
    ghost sprites so a subsequent localize pass isn't confused by them.

    Coordinates are clamped to the screen; off-screen rects are no-ops.
    """
    y0 = max(0, y)
    y1 = min(SCREEN_HEIGHT, y + h)
    x0 = max(0, x)
    x1 = min(SCREEN_WIDTH, x + w)
    if y0 < y1 and x0 < x1:
        mask[y0:y1, x0:x1] = True


def stamp_nameplate_rect(
    mask: np.ndarray, sprite_x: int, sprite_y: int, sprite_w: int
) -> None:
    """Stamp a nameplate exclusion zone above a detected actor sprite.
    Centred horizontally on the sprite; extends
    :data:`NAMEPLATE_HEIGHT` pixels upward (text + 1 px gap)."""
    cx = sprite_x + sprite_w // 2
    x0 = max(0, cx - NAMEPLATE_HALF_WIDTH)
    x1 = min(SCREEN_WIDTH, cx + NAMEPLATE_HALF_WIDTH + 1)
    y0 = max(0, sprite_y - NAMEPLATE_HEIGHT)
    y1 = max(0, sprite_y)  # ends one pixel above the sprite's top edge
    if y0 < y1 and x0 < x1:
        mask[y0:y1, x0:x1] = True


# --- high-level entry points ----------------------------------------------


def build_phase_1_0_ignore_mask(frame: np.ndarray) -> np.ndarray:
    """Compose the phase-1.0 ignore mask for one frame. Pre-localize:
    only the always-on stamps run (player-centre zone + radar pixels).

    Deliberately missing until the matching scans land:

    - Other crewmates / bodies / ghosts (use :func:`stamp_sprite_rect`
      + :func:`stamp_nameplate_rect` once the actor matches are known).
    - Task-icon rectangles (S4.4).
    - Kill-button / ghost HUD icons (post-S4).

    Callers that need the full mask should compose it themselves from
    the public stamp helpers; this function is the pre-localize cheap
    gate, not the final mask.
    """
    mask = np.zeros((SCREEN_HEIGHT, SCREEN_WIDTH), dtype=bool)
    stamp_player_centre_zone(mask)
    stamp_radar_pixels(mask, frame)
    return mask
