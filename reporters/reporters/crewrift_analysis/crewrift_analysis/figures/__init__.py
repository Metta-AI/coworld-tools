"""The four CrewRift figures (requires the ``[charts]`` extra).

- :mod:`.contrast_table` — which behavioral axes distinguish imposters
  from crew, across a directory of episodes.
- :mod:`.vote_ladder` — who voted for whom, per meeting, on role-shaded
  lanes.
- :mod:`.missed_blend` — one player's chances to look like crew on the
  map: near a station with nobody watching.
- :mod:`.fog_of_war` — what one observer actually saw, per Playing phase.

Everything renders headless (Agg) and returns PNG **bytes**; the two map
figures also expose ``build_* -> Figure`` for introspection.
"""

from __future__ import annotations

try:
    import matplotlib

    matplotlib.use("Agg")  # headless: render to buffers, never a window
except ImportError as exc:  # pragma: no cover - exercised only without extra
    raise ImportError(
        "crewrift_analysis.figures requires matplotlib; "
        "install the extra: pip install 'crewrift-analysis[charts]'"
    ) from exc

from .contrast_table import contrast_footnotes, contrast_rows, render_contrast_table
from .fog_of_war import build_fog_of_war, render_fog_of_war
from .missed_blend import BlendWindow, build_missed_blend, missed_blend_windows, render_missed_blend
from .vote_ladder import ladder_inputs, render_vote_ladder

__all__ = [
    "BlendWindow",
    "build_fog_of_war",
    "build_missed_blend",
    "contrast_footnotes",
    "contrast_rows",
    "ladder_inputs",
    "missed_blend_windows",
    "render_contrast_table",
    "render_fog_of_war",
    "render_missed_blend",
    "render_vote_ladder",
]
