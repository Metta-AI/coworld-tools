# paint_arena_summarizer

Per-episode summarizer reporter for the PaintArena coworld. Reads results, episode metadata, and the replay (`config` + `frames`); writes a zip containing a self-contained HTML summary, a JSON stats file, a per-tick Parquet event log, and a `render.txt` manifest per the D12 reporter contract. First concrete reporter in the repo — its inline primitives (HTTP I/O, deterministic-zip writer, shared event-log schema) are the source material for the upcoming [`reporter_sdk`](../../reporter_sdk/) extraction. See [`DESIGN.md`](DESIGN.md) for the locked-in design.

## Output zip contents

```
report.zip
├── summary.html        # rendered inline (listed in render.txt)
├── stats.json          # download-only (referenced from HTML footer)
├── proximity.parquet   # download-only; per-tick event log
└── render.txt          # single line: "summary.html\n"
```

| Entry | Renderable? | Contents |
| --- | --- | --- |
| `summary.html` | yes (`.html` in D12 allowlist) | Self-contained HTML page: verdict band, final-grid SVG heatmap, per-slot score table with proportional bars, back-and-forth highlight cards. Inline CSS only — no `<script>`, no `<link>` — safe inside an iframe+CSP sandbox. |
| `stats.json` | no (download-only) | `{episode_id, variant_id, grid, ticks, duration_seconds, slots[], unpainted_tiles, unpainted_share_pct, winner_slot, margin_tiles, tie, proximity_event_count, highlights[]}` |
| `proximity.parquet` | no (download-only) | Per-tick event log in the shared `(ts: int64, player: int16, key: string, value: string)` schema. Two `key` kinds today: `proximity` (one row per (tick, slot-pair) within Chebyshev distance ≤ 2) and `back_and_forth` (one row per detected contested-tile highlight). `value` is a JSON document; consumers `json.loads` per row. |
| `render.txt` | n/a (the manifest itself) | `summary.html\n` |

The `stats.json` is generalized over slot count (PaintArena's `results_schema` allows 1–4 players); `winner_slot` is `null` on ties or no-paint episodes. The exact field set is specified in [`DESIGN.md`](DESIGN.md). Zip entries pin `date_time` to `(1980, 1, 1, 0, 0, 0)` so byte-identical reruns over identical inputs produce byte-identical zips (D12 determinism). Within one pinned `pyarrow` version the parquet bytes are deterministic too — the requirements.txt pin is what makes that hold across reruns of the same image.

## Inputs

Per the v1 reporter contract ([`../../../docs/REPORTER_DESIGN.md`](../../../docs/REPORTER_DESIGN.md), D2/D10/D11), all consumed inputs arrive as env-supplied URIs:

| Env var | Read |
| --- | --- |
| `COGAME_RESULTS_URI` | results JSON: `scores`, `painted_tiles`, `ticks` |
| `COGAME_EPISODE_METADATA_URI` | `episode_id`, `variant_id`, per-slot `policy_name`, `duration_seconds` |
| `COGAME_REPLAY_URI` | grid `width` × `height` via the replay's `config` block; per-frame `{tick, positions, tile_owners}` for proximity events and back-and-forth highlight detection |
| `COGAME_REPORT_OUTPUT_URI` | write target for the zip (`Content-Type: application/zip`) |
| `COGAME_REPORTER_ID` | stamped into log lines |

`COGAME_LOG_URI` is not consumed in v1.

## Failure modes

| Situation | Behavior |
| --- | --- |
| All inputs valid, normal episode | Exit 0, valid zip with all four entries |
| `painted_tiles` all zero | Exit 0; summary says "no tiles were painted"; `winner_slot: null` |
| Tied painted-tile counts | Exit 0; summary says "tied at N tiles"; `winner_slot: null`, `tie: true` |
| Replay with no frames | Exit 0; HTML highlights section shows the empty state; `proximity.parquet` is a well-formed zero-row table |
| Replay JSON missing `config`, or `config` missing `width`/`height` | Exit 1 (`nonzero_exit` per D8); no zip written |
| Results JSON missing required field or unparseable | Exit 1; no zip written |
| Required env var missing or output URI unreachable | Exit 1; error logged to stderr |

See [`DESIGN.md`](DESIGN.md) for the full failure-mode table.

## Running locally

```bash
COGAME_RESULTS_URI=file:///path/to/results.json \
COGAME_EPISODE_METADATA_URI=file:///path/to/metadata.json \
COGAME_REPLAY_URI=file:///path/to/replay.json \
COGAME_REPORT_OUTPUT_URI=file:///path/to/report.zip \
COGAME_REPORTER_ID=paint-arena-summarizer \
python paint_arena_summarizer.py
```

Both `file://` and `http(s)://` URIs are supported. HTTP requests retry on 429 and 5xx (5 attempts, exponential backoff).

## Building the image

```bash
./build.sh                              # builds paint-arena-summarizer:latest for linux/amd64
IMAGE=ghcr.io/.../par:1 ./build.sh      # override tag
PLATFORM=linux/arm64 ./build.sh         # override platform (local-only; rejected by coworld upload)
```

`build.sh` defaults to `--platform linux/amd64` because `coworld upload` requires amd64 (hosted episodes run on amd64) and would reject a host-arch build from Apple Silicon. On non-amd64 hosts the build and any subsequent `docker run` happen under emulation, which is slower but keeps the locally tested image byte-identical to the uploadable image.

The Docker build context is `reporters/` (the directory containing `reporter_sdk/` and per-coworld trees), so the Dockerfile can `COPY` both the shared SDK and the reporter source from one context. The SDK is installed even though its public surface is currently empty — this reserves the import path for the imminent extraction.

Each reporter ships its own `Dockerfile.dockerignore` (allowlist style) so the build context contains only the SDK plus that reporter's runtime source. Docker 25+ honors the per-Dockerfile ignore file in preference to a `reporters/.dockerignore` at the context root, which lets each reporter scope its own includes.

## Tests

```bash
uv run pytest reporters/paint_arena/paint_arena_summarizer/tests/ -v
```

Covers happy path, zero-paint, tie, replay missing-or-malformed `config`, replay with no frames, malformed and unparseable results, missing env vars, zip-shape and `render.txt` consistency (paths exist, renderable extension, no self-reference, no duplicates), pinned zip-entry mtimes, HTTP retry policy (transient retries, capped attempts, exact backoff schedule), and a determinism check (two runs over the same inputs produce byte-identical zip bytes). Frame-derived logic is covered separately: proximity-event extraction (including the >2-slot generic case), tile-flip detection (only painted→painted transitions count), and back-and-forth window detection (`min_flips`, `window_ticks`, `max_results`). Parquet content is asserted to use the shared `(ts, player, key, value)` schema with `proximity` and `back_and_forth` `key` values.

### Containerized smoke test

```bash
./smoke.sh                  # builds + runs the image against smoke/fixtures/
IMAGE=ghcr.io/.../par:1 ./smoke.sh
```

Builds the image, runs the container against checked-in fixtures under `smoke/fixtures/`, mounts a `mktemp -d` directory for the output zip, and asserts the four-entry zip contract (`{summary.html, stats.json, proximity.parquet, render.txt}`), `render.txt` lists `summary.html`, every listed path exists and has a renderable extension, pinned mtimes, that grid dimensions resolve from the replay's `config` block, that `summary.html` looks like a self-contained HTML document, and that `proximity.parquet` is non-empty when the fixture has frames.

## SDK extraction candidates (inline today)

The following primitives are in `paint_arena_summarizer.py` and slated for promotion to `reporter_sdk`:

- `ReporterInputs` dataclass + `load_reporter_inputs()`
- `read_uri` / `write_uri` / `read_json` (scheme-dispatched `file://` and `http(s)://` with retry)
- `write_deterministic_zip(entries)` — `zipfile.ZipFile` helper with pinned mtimes for D12 byte-identical reruns
- `EVENT_LOG_SCHEMA` + `write_events_parquet(rows)` — the shared `(ts, player, key, value)` event-log schema and its pyarrow writer; intended to be reused across reporters

The PaintArena-specific parts (`build_stats`, `build_proximity_rows`, `extract_tile_flips`, `detect_back_and_forth_highlights`, `render_summary_html`, `build_zip_bytes`, the `PaintArenaReplay` / `ReplayConfig` / `PaintArenaFrame` parsing, the `summary.html` / `stats.json` / `proximity.parquet` / `render.txt` layout) stay in this file — replay-shape coupling is coworld-specific by D11 and intentionally not promotion material, and the in-zip file layout is the reporter author's decision under D12.
