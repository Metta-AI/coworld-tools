"""Game-agnostic episode analysis + visualization primitives.

For reporter/diagnoser authors. Two input surfaces, one analysis layer:

- :mod:`.mettascope` — decode any MettaGrid game's ``replay.json`` (the
  shared delta-field encoding) into per-tick series and canonical event rows.
- :mod:`.eventlog` — query the canonical ``(ts, player, key, value)`` event
  log every reporter emits (:class:`EventLog`).
- :mod:`.heatmap` — positional occupancy grids + blur (numpy).
- :mod:`.stats` — paired A/B statistics (t-CI, bootstrap, win rate) and
  rank-AUC two-group separation.
- :mod:`.routing` — exact optimal-open-tour comparison over an injected
  cost function (Held-Karp).
- :mod:`.imaging` — dependency-free PNG drawing/encoding.
- :mod:`.palette` — the CVD-validated dark palette (+ lazy matplotlib axes
  helpers).
- ``episode_analysis.charts`` — matplotlib chart builders (heatmap renders,
  swimlane timelines, trajectory plots); requires the ``[charts]`` extra.

Core dependencies: numpy + pyarrow only. matplotlib is confined to
``charts``/the palette helpers behind ``episode-analysis[charts]``.

Origin: extracted and generalized from Ron Dahlgren's (swgy) analysis
tooling (sm-policies replay audits; swgy-crewrift swgy-tools). Each module's
docstring carries its provenance.
"""

from .eventlog import EventLog, EventRow
from .heatmap import accumulate_by_group, bin_positions, gaussian_blur, total_grid
from .mettascope import (
    agent_objects,
    is_delta,
    load_replay,
    materialize,
    max_steps_of,
    objects_of_type,
    to_event_rows,
    value_at,
)
from .routing import TourComparison, optimal_open_tour, pairwise_costs, path_cost
from .stats import RankAUC, mean_ci, paired_stats, rank_auc, verdict

__all__ = [
    "EventLog",
    "EventRow",
    "RankAUC",
    "TourComparison",
    "accumulate_by_group",
    "agent_objects",
    "bin_positions",
    "gaussian_blur",
    "is_delta",
    "load_replay",
    "materialize",
    "max_steps_of",
    "mean_ci",
    "objects_of_type",
    "optimal_open_tour",
    "paired_stats",
    "pairwise_costs",
    "path_cost",
    "rank_auc",
    "to_event_rows",
    "total_grid",
    "value_at",
    "verdict",
]
