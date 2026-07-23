"""Matplotlib chart builders (requires the ``[charts]`` extra).

- :mod:`.heatmaps` — colour-mapped positional layers over an optional
  basemap, with title + colorbar, rendered to PNG bytes.
- :mod:`.timeline` — swimlane timelines (:class:`Lane`/:class:`Marker`/
  :class:`Band`): one row per episode *or* per player, tick-exact markers
  with anti-clutter stagger, span bands, caret cropping.
- :mod:`.trajectory` — movement trails (arrows where they moved, ``+``
  where they stood) and scalar-coloured path ribbons.
- :mod:`.contrast` — two-group contrast table (:class:`ContrastRow`): a
  typographic figure ranking axes by rank-AUC separation.
- :mod:`.ladder` — lane-arrow ladders (:class:`LadderActor`/
  :class:`LadderArrow`/:class:`LadderPanel`): per-round panels of
  category-shaded lanes with curved chooser-to-target arrows.

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

from .contrast import ContrastRow, draw_contrast_table, render_contrast_table
from .heatmaps import density_layer, mean_layer, render_heatmap, share_layer
from .ladder import LadderActor, LadderArrow, LadderPanel, draw_ladder_panel, render_lane_ladder
from .timeline import Band, Lane, Marker, render_swimlanes
from .trajectory import colored_path, draw_track, sample_track

__all__ = [
    "Band",
    "ContrastRow",
    "LadderActor",
    "LadderArrow",
    "LadderPanel",
    "Lane",
    "Marker",
    "colored_path",
    "density_layer",
    "draw_contrast_table",
    "draw_ladder_panel",
    "draw_track",
    "mean_layer",
    "render_contrast_table",
    "render_heatmap",
    "render_lane_ladder",
    "render_swimlanes",
    "sample_track",
    "share_layer",
]
