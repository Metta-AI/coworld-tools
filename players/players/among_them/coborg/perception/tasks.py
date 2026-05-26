"""Task-icon and radar-dot scanning. Port of
``users/james/personal_cogs/among_them/guided_bot/perception/tasks.nim``.

Two independent scans live in the module:

1. **Radar-dot scan** — collects yellow (palette index 8) pixels in the
   screen-edge periphery ring and deduplicates them by Chebyshev
   distance 1. HUD-layer, camera-independent. Implemented as
   :func:`scan_radar_dots`.

2. **Task-icon scan** — for each task-station rect, project its world
   position to screen space via the current camera offset, then probe
   a 3-bob × ``(2r+1)²`` neighbourhood around the expected icon anchor.
   Strict-match the task sprite at each probe; dedup hits with
   Chebyshev distance 1. Implemented as :func:`scan_task_icons`. Needs
   :class:`localize.LocalizerState`'s camera position to project,
   which is why this half waits for S4.3 (localize) before S4.4
   (here).

Both scans normally emit into a single :class:`TaskPercept`. The
orchestrating ``scanTasksAndRadar`` in the upstream module gates on
interstitial state, role, and localized status; that gating belongs
in the S5+ perception orchestrator (which composes interstitial
detection + localize + actor scans), not in this module.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from .data import ATLAS_TASK, RADAR_TASK_COLOR, TASK_COORDS, TRANSPARENT_INDEX
from .frame import SCREEN_HEIGHT, SCREEN_WIDTH, oob_filled_patch


# --- constants (mirror upstream tasks.nim) --------------------------------

# Pixel margin defining the screen-edge periphery ring where radar dots
# may appear. Matches ``RadarPeripheryMargin`` in upstream
# ``guided_bot/perception/tasks.nim``. With margin=1 the ring is two
# pixels deep on each edge. ``RADAR_TASK_COLOR`` (palette index of the
# yellow radar pixel) is imported from ``data.palette`` — both this
# module and ``perception.ignore`` consume it.
RADAR_PERIPHERY_MARGIN: int = 1

# Forward-compat task-icon constants. Used by the deferred S4 work; kept
# here so the public surface doesn't churn when scan_task_icons lands.
TASK_ICON_SEARCH_RADIUS: int = 3
TASK_ICON_MAX_MATCHES: int = 64
TASK_ICON_MAX_MISSES: int = 4


# --- types ----------------------------------------------------------------


@dataclass
class IconMatch:
    """One detected task-icon sprite. Reserved type for S4 (the
    task-icon scan needs localize's camera offset; see module docstring)."""

    x: int
    y: int


@dataclass
class RadarDotMatch:
    """One deduped yellow radar dot in the screen-edge periphery ring."""

    x: int
    y: int


@dataclass
class TaskPercept:
    """Structured output of one task / radar-dot scan pass. Mirrors
    upstream ``TaskPercept`` in ``tasks.nim``. Until S4 lands localize
    and the task-icon scan, ``task_icons`` stays empty."""

    task_icons: list[IconMatch] = field(default_factory=list)
    radar_dots: list[RadarDotMatch] = field(default_factory=list)


# --- periphery helper -----------------------------------------------------


def _build_periphery_mask() -> np.ndarray:
    """Build the (SCREEN_HEIGHT, SCREEN_WIDTH) bool mask that marks every
    pixel inside the radar periphery ring as True. Mirrors upstream
    ``isPeriphery``: ``x <= margin`` or ``y <= margin`` or
    ``x >= W-1-margin`` or ``y >= H-1-margin``.

    Built once at import time and held read-only — the mask is shared by
    every call to :func:`scan_radar_dots`."""
    mask = np.zeros((SCREEN_HEIGHT, SCREEN_WIDTH), dtype=bool)
    band = RADAR_PERIPHERY_MARGIN + 1  # x <= margin -> x in [0, margin], width margin+1
    mask[:band, :] = True
    mask[-band:, :] = True
    mask[:, :band] = True
    mask[:, -band:] = True
    mask.flags.writeable = False
    return mask


_PERIPHERY_MASK: np.ndarray = _build_periphery_mask()


# --- public scans ---------------------------------------------------------


def scan_radar_dots(frame: np.ndarray) -> list[RadarDotMatch]:
    """Collect deduped yellow (palette index 8) pixels in the screen-edge
    periphery ring. Mirrors ``tasks.nim::scanRadarDots``.

    Algorithm:

    1. Vectorised mask = ``(frame == RADAR_TASK_COLOR) & periphery``.
    2. ``np.where`` returns ``(ys, xs)`` in raster order, so no separate
       sort is needed (the upstream Nim version sorts defensively after
       a row-major iteration that's already sorted; we get the same
       guarantee directly from numpy).
    3. Greedy dedup via a boolean occupancy mask: each kept dot stamps
       its ``3x3`` Chebyshev-1 neighbourhood as blocked, and a candidate
       falls iff its position is already blocked. Same algorithm as the
       upstream nested loop, fewer per-candidate attribute accesses.
    """
    if frame.shape != (SCREEN_HEIGHT, SCREEN_WIDTH):
        raise ValueError(
            f"scan_radar_dots: frame shape {frame.shape} != "
            f"({SCREEN_HEIGHT}, {SCREEN_WIDTH})"
        )

    hits = (frame == RADAR_TASK_COLOR) & _PERIPHERY_MASK
    ys, xs = np.where(hits)
    blocked = np.zeros_like(hits)
    kept: list[RadarDotMatch] = []
    for y, x in zip(ys.tolist(), xs.tolist()):
        if blocked[y, x]:
            continue
        kept.append(RadarDotMatch(x=int(x), y=int(y)))
        y0, x0 = max(0, y - 1), max(0, x - 1)
        blocked[y0 : y + 2, x0 : x + 2] = True
    return kept


# Vertical-anchor offset used by the task-icon scan. The icon is drawn
# above its station, anchored at `task.y - SPRITE_SIZE - 2` in world Y.
# Mirrors upstream `mb_scan_task_icons`'s `baseY = ty - SpriteSize - 2`.
_TASK_ICON_Y_OFFSET: int = -10  # = -(SPRITE_SIZE + 2)
# 3-bob pattern: the icon visually bobs ±1 pixel each frame.
_TASK_ICON_BOBS: tuple[int, int, int] = (-1, 0, 1)


def scan_task_icons(
    atlas: np.ndarray,
    frame: np.ndarray,
    camera_x: int,
    camera_y: int,
) -> list[IconMatch]:
    """Detect task icons by probing the expected on-screen position of
    every task station's icon. Mirrors upstream
    ``tasks.scanTaskIcons`` / ``mb_scan_task_icons``.

    For each task at world rect ``(tx, ty, tw, th)``:

    - The expected screen anchor is
      ``(tx + tw//2 - SPRITE_SIZE//2 - camera_x, ty - SPRITE_SIZE - 2 - camera_y)``.
      ``th`` is unused — the icon is anchored to the top of the station,
      not its centre.
    - Probe 3-bob (±1 px in Y) × ``(2 * TASK_ICON_SEARCH_RADIUS + 1)²``
      anchors around that position. ``TASK_ICON_SEARCH_RADIUS = 3``.
    - Strict-match the task sprite at each probe (no flip, no tint, ≤4
      misses). OOB pixels count as misses per the upstream rule.
    - Dedup hits within Chebyshev distance 1 via a flat scan over the
      already-kept list (matches upstream ``addMatchDedup``).
    - Stop after :data:`TASK_ICON_MAX_MATCHES` hits.

    Callers must have a valid camera offset (i.e.
    :class:`localize.LocalizerState.localized` is True). The upstream
    convention is to skip the scan entirely on interstitial frames or
    when localization failed; this function does *not* enforce that —
    the S5+ perception orchestrator does.
    """
    sprite = atlas[ATLAS_TASK]
    opaque_mask = sprite != TRANSPARENT_INDEX
    sh, sw = sprite.shape
    kept: list[IconMatch] = []

    for tx, ty, tw, _th in TASK_COORDS:
        base_x = tx + tw // 2 - sw // 2 - camera_x
        base_y = ty + _TASK_ICON_Y_OFFSET - camera_y
        # Cheap reject: if the whole probe region is off-screen, skip.
        # The probe rect in pixel space spans roughly
        # [base_x - r, base_x + r + sw) × [base_y - bob - r, ...].
        if (
            base_x + TASK_ICON_SEARCH_RADIUS + sw < 0
            or base_x - TASK_ICON_SEARCH_RADIUS >= SCREEN_WIDTH
            or base_y + TASK_ICON_SEARCH_RADIUS + 1 + sh < 0
            or base_y - TASK_ICON_SEARCH_RADIUS - 1 >= SCREEN_HEIGHT
        ):
            continue

        for bob in _TASK_ICON_BOBS:
            expected_y = base_y + bob
            for dy in range(-TASK_ICON_SEARCH_RADIUS, TASK_ICON_SEARCH_RADIUS + 1):
                for dx in range(-TASK_ICON_SEARCH_RADIUS, TASK_ICON_SEARCH_RADIUS + 1):
                    x = base_x + dx
                    y = expected_y + dy
                    patch = oob_filled_patch(frame, x, y, (sh, sw))
                    misses = int(np.count_nonzero(opaque_mask & (patch != sprite)))
                    if misses > TASK_ICON_MAX_MISSES:
                        continue
                    # Chebyshev-1 dedup against already-kept hits.
                    duplicate = False
                    for k in kept:
                        if abs(k.x - x) <= 1 and abs(k.y - y) <= 1:
                            duplicate = True
                            break
                    if duplicate:
                        continue
                    if len(kept) >= TASK_ICON_MAX_MATCHES:
                        return kept
                    kept.append(IconMatch(x=int(x), y=int(y)))
    return kept
