# mettagrid-replay-atlas

An **engine-generic** reporter: one image serves every MettaGrid-based game
(most of `games/games/`). It exists both as a useful default report and as
the normative end-to-end example of the shared
[`episode_analysis`](../../episode_analysis/README.md) library:

```
episode bundle (results.json + replay.json)
  → episode_analysis.mettascope        decode delta fields, derive event rows
  → reporter_sdk.write_events_parquet  events.parquet (canonical schema)
  → episode_analysis.heatmap + charts  occupancy heatmap, per-agent timeline
  → episode_analysis.html              self-contained summary.html
```

## Output zip

| entry | manifest flag | contents |
|-------|---------------|----------|
| `summary.html` | `render` | agent table + charts embedded as data URIs (self-contained) |
| `events.parquet` | `event_log` | `position` / `reward` / `death` / `episode` rows per the recommended key registry |
| `occupancy.png`, `timeline.png` | — | the raw charts as free-form aux files |

## Configuration

- `ATLAS_LOCATION_ORDER` — `xy` (default) or `rc`. MettaGrid replays store
  agent `location` as a 2-list whose axis order is game-defined; if the
  occupancy map looks transposed against a non-square map, flip this.

## Local loop

```bash
./smoke.sh          # synthetic bundle → reporter → asserts the zip shape
uv run pytest reporters/mettagrid/mettagrid_replay_atlas/tests
./build.sh          # docker image (context: reporters/reporters)
```

Non-MettaScope bundles (e.g. Among Them's `.bitreplay`) are rejected with a
clear error — this reporter targets MettaGrid games only.

Owner: rdahlgren. Built on `episode_analysis` (origin: Ron Dahlgren's (swgy)
analysis tooling).
