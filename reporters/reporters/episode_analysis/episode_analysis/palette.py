"""The shared visual language: a CVD-validated dark palette + axes helpers.

The color constants are plain strings (no imports), so chart-free consumers
— e.g. drawing with ``episode_analysis.imaging`` — can use them without
matplotlib. The two matplotlib helpers (:func:`basemap`, :func:`world_axes`)
import it lazily and raise an actionable error when the ``[charts]`` extra
is missing.

**The categorical palette was validated as a set** (worst adjacent
color-vision-deficiency dE 20.7 on the ``SURFACE`` dark step). Adding a
fifth hue means re-running a CVD validator, not eyeballing it.

Origin: extracted from Ron Dahlgren's (swgy) crewrift tooling
(``swgy_tools.plotstyle``); the vendored Croatoan basemap became a
caller-supplied image, and the semantic names were generalized (the origin's
"imposter/antagonist" amber reads as ``ACCENT`` here — meanings stay shared
across charts on purpose: a red cross means the same thing everywhere).
"""

from __future__ import annotations

from typing import Any

import numpy as np

__all__ = [
    "ACCENT",
    "EDGE",
    "GRID",
    "INK",
    "MUTED",
    "PAGE",
    "PRIMARY",
    "SECONDARY",
    "NEGATIVE",
    "POSITIVE",
    "STATION_MARK",
    "PORTAL_MARK",
    "SURFACE",
    "basemap",
    "world_axes",
]

# Chrome
PAGE = "#0d0d0d"
SURFACE = "#1a1a19"
INK = "#ffffff"
SECONDARY = "#c3c2b7"
MUTED = "#898781"
GRID = "#2c2c2a"

# Categorical, validated as a set on SURFACE. Keep meanings shared across
# charts: the same red is "something bad happened" in a timeline and on a map.
PRIMARY = "#3987e5"  # blue   -- the protagonist track / main series
POSITIVE = "#199e70"  # aqua  -- a good/secondary state
NEGATIVE = "#d03b3b"  # red   -- deaths, failures (status: critical)
ACCENT = "#c98500"  # amber  -- spans, antagonist track, highlights

# Markers drawn over a basemap, whose luminance varies per pixel: a dark edge
# keeps them legible on a bright corridor. Not decoration -- the mitigation.
EDGE = "#0b0b0b"

# Map-landmark markers, shared by every renderer that draws a map. One
# source of truth: two hand-picked near-identical values once diverged and
# the mismatch read as a slip.
STATION_MARK = "#3cd2eb"  # cyan squares  -- objective/task stations
PORTAL_MARK = "#ff50eb"  # magenta diamonds -- teleporters/vents


def _plt() -> Any:
    try:
        import matplotlib

        matplotlib.use("Agg")  # headless: render to buffers, never a window
        import matplotlib.pyplot as plt
    except ImportError as exc:  # pragma: no cover - exercised only without extra
        raise ImportError(
            "matplotlib is required for episode_analysis chart helpers; "
            "install the extra: pip install 'episode-analysis[charts]'"
        ) from exc
    return plt


def basemap(image: np.ndarray | str | None, dim: float = 0.55) -> np.ndarray | None:
    """Desaturate + dim a map image so chart overlays read on top of it.

    ``image`` is an ``(H, W, 3+)`` array or a path readable by matplotlib;
    ``None`` passes through (no basemap). ``dim`` is pinned low by default:
    the palette was validated against a dark surface, and markers lose
    contrast on a bright map.
    """
    if image is None:
        return None
    plt = _plt()
    img = plt.imread(image) if isinstance(image, str) else np.asarray(image)
    img = img[:, :, :3].astype(np.float32)
    if img.max() > 1.0:
        img /= 255.0
    gray = img @ np.array([0.299, 0.587, 0.114], np.float32)
    return np.repeat(gray[:, :, None], 3, axis=2) * dim


def world_axes(
    ax: Any,
    width: int,
    height: int,
    *,
    y_down: bool = True,
    background: np.ndarray | str | None = None,
    dim: float = 0.55,
) -> None:
    """Set up ``ax`` in world coordinates, optionally over a dimmed basemap.

    Grid/tile/pixel worlds usually have **y pointing down**; ``y_down=True``
    inverts the y-limits so charts match the game's own orientation.
    """
    bg = basemap(background, dim)
    if bg is not None:
        ax.imshow(bg, extent=[0, width, height, 0], interpolation="bilinear", zorder=0)
    ax.set_xlim(0, width)
    ax.set_ylim((height, 0) if y_down else (0, height))
    ax.set_facecolor(SURFACE)
