# crewrift-analysis

CrewRift-specific analysis and figures over the game's own replay export.
The game-specific layer above the engine-generic `episode-analysis` package:

```
crewrift_analysis   game schema, player palette, contrast metrics, figures
    -> episode_analysis   charts, palette semantics, stats
        -> expand_replay --format jsonl --snapshot-every N   the input
```

Core deps: `episode-analysis` + numpy. matplotlib only via the `[charts]`
extra (which forwards to `episode-analysis[charts]`).

## Generating input

Everything consumes the newline-delimited JSON that the game repo's
`tools/expand_replay.nim` prints in snapshot mode:

```bash
# in coworld-crewrift
tools/expand_replay --format jsonl --snapshot-every 3 path/to/episode.bitreplay > episode.jsonl
```

One file per episode; the file stem is the episode id. A positive
`--snapshot-every` is required: the per-tick `player_state` tracks (and the
figures built on them) do not exist without it, and the adapter raises a
`CrewriftLogError` telling you to regenerate rather than rendering nothing.

## The modules

- **`events`** — typed adapter: one episode's JSONL -> `Episode` (players,
  phases, meetings, votes, chats, kills, sightings, numpy tracks).
- **`palette`** — the 16-color engine player palette (identity, never
  role), `ROLE_COLORS` reusing the house semantics, and lifted variants for
  dark backdrops.
- **`metrics`** — the imposter/crew contrast axes, one scalar per
  player-game, aggregated with rank AUC (`aggregate_contrast`).
- **`figures`** *(requires `crewrift-analysis[charts]`)* — the four
  figures: contrast table, vote ladder, missed-blend overlay, fog of war.
- **`testing`** — a deterministic synthetic episode (JSONL lines) for
  tests and smoke checks; every number hand-computable.

## Dev CLI

```bash
python -m crewrift_analysis contrast-table <dir-of-jsonl> --out out/
python -m crewrift_analysis vote-ladder episode.jsonl --out out/
python -m crewrift_analysis missed-blend episode.jsonl --slot 2 --map-image croatoan.png --out out/
python -m crewrift_analysis fog-of-war episode.jsonl --observer 1 --phases 1,2 --out out/
```

`--map-image` is optional everywhere it appears: the repo vendors no map
raster, so map figures render on the dark house surface unless you point
the flag at a Croatoan backdrop (1235x659, engine-aligned, y down).

## Schema quirks the adapter encodes

| Fact | Consequence |
|---|---|
| Skip votes are `value.target == "skip"` with no `target_slot` | `Vote.target is None`, never a sentinel int |
| `died` fires only for ejections; murders emit `kill` | `Episode.deaths` takes the min over both |
| `color_id` is an internal engine byte, not a palette index | identity comes from `color` (the name), always |
| Croatoan has 41 task stations and 11 vents | nothing hardcodes either count |
| The engine seats 8-16 players | nothing hardcodes a roster size |
| Ghosts keep moving (through walls) and completing tasks | behavioral stats mask through `playing & alive` |
| Meetings teleport everyone to the Bridge | distance never sums across non-Playing samples or stride gaps |
| Imposters are assigned zero tasks | no task-completion axis exists; station occupancy is the behavioral version |

## Why a library + dev CLI, not a Docker reporter

Coworld crewrift episode bundles carry the raw `.bitreplay`, and expanding
one requires re-running the Nim simulator (`tools/expand_replay`) - there
is nothing a Python-only reporter image could do with the bundle today. If
bundles grow an expanded-events artifact, a reporter wrapping these figures
becomes a thin composition; until then this package stays out of
`CATALOG.yaml` and ships no image workflow.

Future work worth flagging: the fog-of-war figure shades only where other
players were seen, because `player_visible_interval` records sightings, not
a field-of-view polygon. The honest upgrade is raycasting the observer's
actual visible region per tick with `players.player_sdk.nav_mesh.builder
.visibility` and shading that.

## Determinism posture

Same input, same bytes, except across matplotlib versions: pin matplotlib
wherever byte-stable figures matter, as with `episode_analysis.charts`.

## Origin

Adapted from Ron Dahlgren's (swgy) crewrift tooling (swgy-crewrift
`swgy_tools`: `spatial.eventlog`, `tasks.eventlog`, and the spatial
renderers); generalized pieces went to `episode_analysis`, and this package
keeps only what is CrewRift-shaped.
