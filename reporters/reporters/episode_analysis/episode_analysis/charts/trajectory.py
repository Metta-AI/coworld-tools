"""Movement-trail plots: sampled tracks with honest gaps, scalar ribbons.

Two techniques from the origin's kill-cam and route-ribbon renderers
(``swgy_tools.spatial.killplot``, ``route.ribbon``), generalized:

- :func:`sample_track` + :func:`draw_track` — a player's trail over a
  window: arrows where they moved, a ``+`` (sized by dwell) where they stood
  still. A hole in the tick series is **not** drawn across — positions
  sampled only during play mean a teleport/meeting gap, and inventing a
  route across it is the same lie as joining two waypoints with a straight
  line.
- :func:`colored_path` — a polyline coloured by a per-point scalar
  (visibility, speed, threat) via a ``LineCollection``.

The game-specific witness/line-of-sight overlays of the origin did not port
(they need engine raycast data); compose them on top in game code.
"""

from __future__ import annotations

from typing import Any, Sequence

import numpy as np
from matplotlib.collections import LineCollection

from ..palette import EDGE

__all__ = ["colored_path", "draw_track", "sample_track"]


def sample_track(
    track: dict[int, tuple[float, float]], end_tick: int, window_ticks: int, step: int
) -> list[tuple[int, float, float]]:
    """``[(tick, x, y)]`` for one player over the window ending at
    ``end_tick``. ``step`` must be a multiple of the data's sampling stride
    or every sample misses."""
    start = max(0, end_tick - window_ticks)
    out: list[tuple[int, float, float]] = []
    t = start + (end_tick - start) % step
    while t <= end_tick:
        if t in track:
            x, y = track[t]
            out.append((t, x, y))
        t += step
    return out


def draw_track(
    ax: Any,
    samples: list[tuple[int, float, float]],
    color: str,
    step: int,
    arrow_length: float = 10.0,
) -> None:
    """Draw one trail: arrows where they moved, ``+`` where they stood still.

    A jump of more than ``step`` ticks between samples is a hole (teleport,
    meeting, missing data) and is deliberately not drawn across.
    """
    if not samples:
        return
    n, i = len(samples), 0
    while i < n - 1:
        t, x, y = samples[i]
        nt, nx, ny = samples[i + 1]

        if nt - t > step:
            i += 1
            continue

        dx, dy = nx - x, ny - y
        if dx == 0 and dy == 0:  # collapse a stationary run into one +
            run = 1
            while i + run < n - 1:
                _, rx, ry = samples[i + run]
                _, rnx, rny = samples[i + run + 1]
                if (rnx - rx, rny - ry) != (0, 0):
                    break
                run += 1
            ax.scatter(
                [x],
                [y],
                marker="P",
                c=color,
                s=min(70 + 28 * run, 460),
                zorder=4,
                edgecolors=EDGE,
                linewidths=0.5,
            )
            i += run
        else:
            norm = (dx * dx + dy * dy) ** 0.5
            ax.annotate(
                "",
                xy=(x + dx / norm * arrow_length, y + dy / norm * arrow_length),
                xytext=(x, y),
                arrowprops={
                    "arrowstyle": "-|>",
                    "color": color,
                    "lw": 1.6,
                    "shrinkA": 0,
                    "shrinkB": 0,
                },
                zorder=4,
            )
            i += 1


def colored_path(
    ax: Any,
    points: Sequence[tuple[float, float]],
    scalar: Sequence[float],
    cmap: str = "viridis",
    norm: Any = None,
    linewidth: float = 2.4,
) -> LineCollection:
    """Draw a polyline coloured per segment by ``scalar`` (one value per
    point; segments take the mean of their endpoints). Returns the
    ``LineCollection`` so the caller can attach a colorbar."""
    if len(points) != len(scalar):
        raise ValueError(f"points ({len(points)}) and scalar ({len(scalar)}) lengths differ")
    pts = np.asarray(points, dtype=float).reshape(-1, 1, 2)
    segments = np.concatenate([pts[:-1], pts[1:]], axis=1)
    values = np.asarray(scalar, dtype=float)
    seg_values = (values[:-1] + values[1:]) / 2.0
    lc = LineCollection(segments, cmap=cmap, norm=norm, capstyle="round")
    lc.set_array(seg_values)
    lc.set_linewidth(linewidth)
    ax.add_collection(lc)
    return lc
