"""Matplotlib chart builders (requires the ``[charts]`` extra).

- :mod:`.heatmaps` — colour-mapped positional layers over an optional
  basemap, with title + colorbar, rendered to PNG bytes.
- :mod:`.timeline` — swimlane timelines (:class:`Lane`/:class:`Marker`/
  :class:`Band`): one row per episode *or* per player, tick-exact markers
  with anti-clutter stagger, span bands, caret cropping.
- :mod:`.trajectory` — movement trails (arrows where they moved, ``+``
  where they stood) and scalar-coloured path ribbons.

Everything renders headless (Agg) and returns PNG **bytes** — reporters
write into zips, not paths. Charts are not promised byte-identical across
matplotlib versions; pin matplotlib in each reporter image.

Origin: extracted and generalized from Ron Dahlgren's (swgy) crewrift
renderers (``swgy_tools.spatial.render``/``killplot``, ``tasks.render``,
``route.ribbon``).
"""

from __future__ import annotations

try:
    import matplotlib

    matplotlib.use("Agg")  # headless: render to buffers, never a window
except ImportError as exc:  # pragma: no cover - exercised only without extra
    raise ImportError(
        "episode_analysis.charts requires matplotlib; "
        "install the extra: pip install 'episode-analysis[charts]'"
    ) from exc

from .heatmaps import density_layer, mean_layer, render_heatmap, share_layer
from .timeline import Band, Lane, Marker, render_swimlanes
from .trajectory import colored_path, draw_track, sample_track

__all__ = [
    "Band",
    "Lane",
    "Marker",
    "colored_path",
    "density_layer",
    "draw_track",
    "mean_layer",
    "render_heatmap",
    "render_swimlanes",
    "sample_track",
    "share_layer",
]
