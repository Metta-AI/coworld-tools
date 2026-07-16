"""Positional heatmap grids: bin samples, accumulate by group, blur.

numpy only — the *data* half of heatmapping. Rendering (colormaps, alpha,
diverging share maps) lives in ``episode_analysis.charts.heatmaps`` behind
the ``[charts]`` extra, so chart-free consumers can still bin and compare
occupancy grids.

Origin: extracted from Ron Dahlgren's (swgy) crewrift spatial tooling
(``swgy_tools.spatial.build``'s occupancy accumulation and ``render``'s
separable Gaussian blur); the corpus CSV/npz pipeline did not port —
reporters are single-episode, and a corpus is just a sum of grids.
"""

from __future__ import annotations

from typing import Iterable, Mapping

import numpy as np

__all__ = ["accumulate_by_group", "bin_positions", "gaussian_blur"]


def bin_positions(
    samples: Iterable[tuple[float, float]],
    width: float,
    height: float,
    cell: float = 1.0,
) -> np.ndarray:
    """Count ``(x, y)`` samples into a ``(grid_h, grid_w)`` occupancy grid.

    ``cell`` is the bin edge length in world units (1.0 = one bin per grid
    cell — the natural choice for tile worlds; larger for pixel worlds).
    Out-of-bounds samples clamp to the border bin.
    """
    if cell <= 0:
        raise ValueError("cell must be positive")
    gw = max(1, int(np.ceil(width / cell)))
    gh = max(1, int(np.ceil(height / cell)))
    grid = np.zeros((gh, gw), dtype=np.int64)
    for x, y in samples:
        cx = min(max(int(x // cell), 0), gw - 1)
        cy = min(max(int(y // cell), 0), gh - 1)
        grid[cy, cx] += 1
    return grid


def accumulate_by_group(
    samples: Iterable[tuple[float, float, object]],
    width: float,
    height: float,
    cell: float = 1.0,
) -> dict[object, np.ndarray]:
    """Bin ``(x, y, group)`` samples into one grid per group (e.g. per
    player, per team, per policy). Returns ``{group: grid}``."""
    grids: dict[object, np.ndarray] = {}
    by_group: dict[object, list[tuple[float, float]]] = {}
    for x, y, g in samples:
        by_group.setdefault(g, []).append((x, y))
    for g, pts in by_group.items():
        grids[g] = bin_positions(pts, width, height, cell)
    return grids


def total_grid(grids: Mapping[object, np.ndarray]) -> np.ndarray:
    """Sum a group dict into one combined grid (empty dict -> 1x1 zeros)."""
    it = iter(grids.values())
    first = next(it, None)
    if first is None:
        return np.zeros((1, 1), dtype=np.int64)
    out = first.copy()
    for g in it:
        out += g
    return out


def gaussian_blur(g: np.ndarray, sigma: float) -> np.ndarray:
    """Separable Gaussian blur. No scipy — the kernel is six lines and this
    is the only use."""
    if sigma <= 0:
        return g
    radius = max(1, int(3 * sigma))
    x = np.arange(-radius, radius + 1, dtype=np.float64)
    k = np.exp(-(x**2) / (2 * sigma * sigma))
    k /= k.sum()
    out = np.apply_along_axis(lambda m: np.convolve(m, k, mode="same"), 0, g.astype(np.float64))
    return np.apply_along_axis(lambda m: np.convolve(m, k, mode="same"), 1, out)
