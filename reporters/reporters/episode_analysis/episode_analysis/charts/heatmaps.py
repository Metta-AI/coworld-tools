"""Positional heatmap rendering: layers -> labelled PNG bytes.

The layer functions are public and each returns ``(rgba, norm, cmap)`` for
one grid, so a notebook (or another chart) can compose its own figure
instead of re-deriving the colour maths — which is how three private copies
of it came to exist in the origin project.

A heat map with no scale is decoration: :func:`render_heatmap` always draws
a title and a colorbar.

Origin: extracted from Ron Dahlgren's (swgy) ``swgy_tools.spatial.render``;
the imposter-tell diverging map became :func:`share_layer` with the base
rate a parameter, and the Croatoan geometry became caller-supplied
``landmarks``/``background``.
"""

from __future__ import annotations

import io
from typing import Any, Sequence

import matplotlib
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.colors import LogNorm, Normalize, TwoSlopeNorm

from ..heatmap import gaussian_blur
from ..palette import EDGE, INK, MUTED, PAGE, SECONDARY, world_axes

__all__ = ["density_layer", "mean_layer", "render_heatmap", "share_layer"]

Layer = tuple[np.ndarray, Any, Any]


def density_layer(grid: np.ndarray, sigma: float = 1.3) -> Layer | None:
    """Blurred log-count -> ``(rgba, norm, cmap)``; density is carried by
    alpha (fades to nothing where nothing happened). ``None`` if empty."""
    g = gaussian_blur(grid.astype(np.float64), sigma)
    vmax = float(g.max())
    if vmax <= 0:
        return None
    vmin = vmax / 1000.0  # a 3-decade log scale
    norm = LogNorm(vmin=vmin, vmax=vmax)
    cmap = matplotlib.colormaps["inferno"]
    rgba = cmap(norm(np.clip(g, vmin, vmax)))
    rgba[..., 3] = np.clip(g / vmax, 0, 1) ** 0.5
    return rgba, norm, cmap


def share_layer(a: np.ndarray, b: np.ndarray, base_rate: float = 0.5) -> Layer | None:
    """Where presence is *disproportionately* ``b``: a diverging map of
    ``b / (a + b)`` centred on ``base_rate``, so a cell reads hot only where
    ``b`` is over-represented relative to its overall share — not merely
    where a ``b`` happened to walk. Alpha follows total presence."""
    if not 0.0 < base_rate < 1.0:
        raise ValueError("base_rate must be in (0, 1)")
    total = a + b
    if not total.max():
        return None
    seen = total > total.max() / 400.0
    if not seen.any():
        return None
    share = np.zeros_like(total, dtype=np.float64)
    share[seen] = b[seen] / total[seen]
    norm = TwoSlopeNorm(vmin=0.0, vcenter=base_rate, vmax=1.0)
    cmap = matplotlib.colormaps["RdBu_r"]
    rgba = cmap(norm(share))
    rgba[..., 3] = np.where(seen, np.clip(total / total.max(), 0, 1) ** 0.4, 0.0)
    return rgba, norm, cmap


def mean_layer(
    sum_grid: np.ndarray, count_grid: np.ndarray, sigma: float = 1.1
) -> Layer | None:
    """Per-cell mean of an accumulated quantity (``sum/count``) — e.g. mean
    ticks a body went undiscovered per cell. ``None`` when nothing counted."""
    seen = count_grid > 0
    if not seen.any():
        return None
    mean = np.zeros_like(sum_grid, dtype=np.float64)
    mean[seen] = sum_grid[seen] / count_grid[seen]
    mean = gaussian_blur(mean, sigma)
    vmax = float(mean.max())
    if vmax <= 0:
        return None
    norm = Normalize(vmin=0.0, vmax=vmax)
    cmap = matplotlib.colormaps["inferno"]
    rgba = cmap(norm(mean))
    rgba[..., 3] = np.where(gaussian_blur(seen.astype(np.float64), sigma) > 0.02, 0.9, 0.0)
    return rgba, norm, cmap


def render_heatmap(
    layer: Layer,
    *,
    title: str,
    cbar_label: str,
    width: float,
    height: float,
    landmarks: Sequence[tuple[float, float, str, str]] = (),
    background: np.ndarray | str | None = None,
    y_down: bool = True,
    dpi: int = 130,
) -> bytes:
    """Render one layer to PNG bytes: basemap (optional), the rgba layer in
    world extent, landmark markers, a left-aligned title, and a colorbar.

    ``landmarks`` are ``(x, y, marker, label)`` — same-label points share a
    legend entry. World y points down by default (grid/pixel convention).
    """
    rgba, norm, cmap = layer
    fig, ax = plt.subplots(
        figsize=(12.5, 12.5 * height / max(width, 1) + 0.8), facecolor=PAGE
    )
    world_axes(ax, int(width), int(height), y_down=y_down, background=background)
    extent = [0, width, height, 0] if y_down else [0, width, 0, height]
    ax.imshow(rgba, extent=extent, interpolation="bilinear", zorder=2)

    by_label: dict[str, list[tuple[float, float, str]]] = {}
    for x, y, marker, label in landmarks:
        by_label.setdefault(label, []).append((x, y, marker))
    for label, pts in by_label.items():
        xs, ys = [p[0] for p in pts], [p[1] for p in pts]
        ax.scatter(
            xs, ys, marker=pts[0][2], s=16, facecolors="none",
            edgecolors=EDGE if label == "" else None, linewidths=0.9, zorder=4,
            label=label or None,
        )

    ax.set_xticks([])
    ax.set_yticks([])
    for s in ax.spines.values():
        s.set_visible(False)
    ax.set_title(title, color=INK, fontsize=12, loc="left", pad=10)
    if by_label:
        ax.legend(loc="lower right", frameon=False, fontsize=8, labelcolor=SECONDARY)

    sm = plt.cm.ScalarMappable(norm=norm, cmap=cmap)
    cb = fig.colorbar(sm, ax=ax, fraction=0.028, pad=0.012)
    cb.set_label(cbar_label, color=SECONDARY, fontsize=8)
    cb.ax.tick_params(colors=MUTED, labelsize=7)
    cb.outline.set_visible(False)

    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=dpi, facecolor=PAGE, bbox_inches="tight", pad_inches=0.12)
    plt.close(fig)
    return buf.getvalue()
