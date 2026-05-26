"""Task-icon and radar-dot scanning. Partial port of
``users/james/personal_cogs/among_them/guided_bot/perception/tasks.nim``.

Two independent scans live in the upstream module:

1. **Radar-dot scan** — collects yellow (palette index 8) pixels in the
   screen-edge periphery ring and deduplicates them by Chebyshev distance
   1. HUD-layer, camera-independent. Ports here as :func:`scan_radar_dots`.

2. **Task-icon scan** — wraps the upstream Nim kernel
   ``mb_scan_task_icons`` which sweeps a small neighbourhood around each
   task station's expected on-screen position. Needs the current camera
   offset (``camX``, ``camY``) so the station's world-space anchor can be
   projected to screen space. **Deferred to S4 alongside localize per
   PLAN.md section 12 item 5.** :func:`scan_task_icons` is reserved as a
   stub here so S4 fills it in without churning the public surface.

Both scans normally emit into a single :class:`TaskPercept`. The
orchestrating ``scanTasksAndRadar`` in the upstream module gates on
interstitial state and the live role; that gating is part of the S4
top-level perception orchestrator (which itself needs the interstitial
detector), so it isn't reproduced here.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from .frame import SCREEN_HEIGHT, SCREEN_WIDTH


# --- constants (mirror upstream tasks.nim + ignore.nim) -------------------

# Palette index of radar-dot hits (yellow). Matches ``RadarTaskColor``
# in upstream ``guided_bot/perception/ignore.nim``.
RADAR_TASK_COLOR: int = 8

# Pixel margin defining the screen-edge periphery ring where radar dots
# may appear. Matches ``RadarPeripheryMargin`` in upstream
# ``guided_bot/perception/tasks.nim``. With margin=1 the ring is two
# pixels deep on each edge.
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


def scan_task_icons(*_args: object, **_kwargs: object) -> list[IconMatch]:
    """Reserved for S4. The upstream task-icon scan wraps
    ``mb_scan_task_icons`` and requires a localized camera offset which
    only lands in S4 (PLAN.md section 12 item 5). Calling this in S3 is
    a programmer error."""
    raise NotImplementedError(
        "scan_task_icons is deferred to S4 alongside perception/localize.py"
    )
