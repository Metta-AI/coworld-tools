# episode-analysis — shared analysis + viz primitives for reporter authors

A pip-installable sibling of `reporter_sdk`: where `reporter_sdk` owns the
*contract* (bundle IO, output zips, the canonical event-log schema), this
package owns *analysis* — turning replays and event logs into series, grids,
statistics, and charts. Any reporter's Docker build can `COPY` it exactly
like `reporter_sdk` (same build-context plane).

Core deps: numpy + pyarrow. matplotlib only via the `[charts]` extra.

## The layering

```
game-specific reporter / diagnoser         (keys, geometry, verdict prose)
        │  picks key names, supplies maps/cost functions
episode_analysis                           (this package — game-agnostic)
        │  reads
canonical event log (ts, player, key, value)   ← reporter_sdk owns the schema
MettaScope replay.json                         ← mettascope.py decodes it
```

- **`mettascope`** — the shared delta-field decoder for every
  MettaGrid-based game's `replay.json` (`load_replay` sniffs zlib vs plain;
  `is_delta` / `value_at` / `materialize`; `to_event_rows` derives canonical
  event rows). Previously re-implemented privately by each consumer (the
  sm-policies replay audits, `cogs_vs_clips_summarizer`'s `_changes`) — this
  is the shared home.
- **`eventlog`** — `EventLog.from_parquet(...)` / `.from_rows(...)` with
  key-parameterized accessors (`positions()`, `numeric_series()`, `spans()`).
- **`heatmap`** — `bin_positions` / `accumulate_by_group` / `gaussian_blur`
  (data only; rendering is in `charts`).
- **`stats`** — `paired_stats` (t-CI + seeded bootstrap + win rate),
  `verdict`, `mean_ci`.
- **`routing`** — `optimal_open_tour` (exact Held-Karp), `pairwise_costs`
  over an injected `cost_fn`, `TourComparison` (actual vs optimal order).
- **`imaging`** — dependency-free PNG encode + Bresenham line/disc/ring
  (raster artifacts without a plotting stack).
- **`palette`** — the CVD-validated dark palette (constants are import-free)
  + lazy matplotlib `world_axes`/`basemap` helpers.
- **`charts/`** *(requires `episode-analysis[charts]`)* — heatmap renders,
  swimlane timelines, trajectory plots. See `charts/__init__.py`.

## Recommended event-log key registry

The canonical schema fixes *columns*, not keys. Cross-game tooling only
works if reporters converge on payload shapes, so this package documents (and
defaults to) the following registry — every accessor/chart takes key names as
parameters, and unknown keys are never an error:

| key | player | payload | meaning |
|-----|--------|---------|---------|
| `position` | slot | `{"x": n, "y": n}` | position at `ts` (emit on change) |
| `reward` | slot | `{"delta": f, "total": f}` | reward change |
| `death` | slot | `{}` | the player died at `ts` |
| `episode` | `-1` | `{"max_steps": n, "num_agents": n}` | one row at ts 0 |
| *span-shaped* | `-1` | `{"start": t0, "end": t1, ...}` | phases, meetings, rounds |

`mettascope.to_event_rows` is the normative producer for MettaGrid games
(`location_order="xy"|"rc"` — MettaGrid stores `location` as a 2-list whose
axis order is game-defined; verify against a non-square map before trusting
heatmap orientation).

## Determinism posture

Event-log Parquet stays byte-deterministic (produce it with
`reporter_sdk.write_events_parquet` + `stable_json`). Chart PNGs are *not*
promised byte-identical across matplotlib/font versions — the reporter
contract prefers but does not require determinism; pin matplotlib in each
reporter's requirements.txt.

## Origin

Extracted and generalized from Ron Dahlgren's (swgy) analysis tooling:
sm-policies `replay_audit*.py` (the delta decoder) and `aggregate_paired.py`
(mean/CI), swgy-crewrift's `swgy_tools` (`imaging`, `plotstyle`,
`spatial`/`tasks` event parsing and heatmaps, `route/tour` Held-Karp,
`navbench` paired stats). Game-specific pathology detectors (hub-camping,
zombie confinement), the Croatoan basemap, and re-simulation drivers stayed
with their games — a worked example of layering a detector on this package
lives in the origin's `replay_audit2.py` if you need the pattern.
