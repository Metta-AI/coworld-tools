# paint_arena_summarizer

Per-episode summarizer reporter for the PaintArena Coworld. Reads the episode bundle (results, replay, config); writes a single output zip containing a self-contained HTML summary, a JSON stats file, a per-tick Parquet event log, and an in-zip `manifest.json` flagging the HTML as `render` and the Parquet as `event_log` per the canonical Coworld reporter contract. First concrete reporter in the repo — its inline primitives (HTTP I/O, deterministic-zip writer, shared event-log schema) are the source material for the upcoming [`reporter_sdk`](../../reporter_sdk/) extraction. See [`DESIGN.md`](DESIGN.md) for the locked-in design.

> **Implementation status (2026-05-23):** the running code follows a pre-canonical draft of the reporter contract (multiple input env vars; a top-level `render.txt` file inside the output zip). The README below describes the **canonical** Coworld contract this reporter will be migrated to alongside metta's reference reporters. See [`../../../docs/REPORTER_DESIGN.md` § Migration state](../../../docs/REPORTER_DESIGN.md#5-migration-state) for the migration plan and the gap.

## Output zip contents

```
report.zip
├── manifest.json       # {reporter_id, render: "summary.html", event_log: "proximity.parquet"}
├── summary.html        # rendered inline (flagged by manifest.json `render`)
├── stats.json          # auxiliary download (referenced from HTML footer)
└── proximity.parquet   # canonical event log (flagged by manifest.json `event_log`)
```

| Entry | Role | Contents |
| --- | --- | --- |
| `manifest.json` | render manifest | `{"reporter_id": "paint-arena-summarizer", "render": "summary.html", "event_log": "proximity.parquet"}` |
| `summary.html` | `render` target | Self-contained HTML page: verdict band, final-grid SVG heatmap, per-slot score table with proportional bars, back-and-forth highlight cards. Inline CSS only — no `<script>`, no `<link>` — safe inside an iframe+CSP sandbox. |
| `stats.json` | auxiliary | `{episode_id, variant_id, grid, ticks, duration_seconds, slots[], unpainted_tiles, unpainted_share_pct, winner_slot, margin_tiles, tie, proximity_event_count, highlights[]}` |
| `proximity.parquet` | `event_log` target | Per-tick event log in the canonical `(ts: int64, player: int64, key: string, value: string)` schema. Two `key` kinds today: `proximity` (one row per (tick, slot-pair) within Chebyshev distance ≤ 2) and `back_and_forth` (one row per detected contested-tile highlight). `value` is a JSON document; consumers `json.loads` per row. |

The `stats.json` is generalized over slot count (PaintArena's `results_schema` allows 1–4 players); `winner_slot` is `null` on ties or no-paint episodes. The exact field set is specified in [`DESIGN.md`](DESIGN.md). Zip entries pin `date_time` to `(1980, 1, 1, 0, 0, 0)` so byte-identical reruns over identical inputs produce byte-identical zips (determinism is preferred but not required by the canonical contract). Within one pinned `pyarrow` version the Parquet bytes are deterministic too — the `requirements.txt` pin is what makes that hold across reruns of the same image.

## Inputs

Per the canonical reporter contract ([`packages/coworld/src/coworld/docs/roles/reporter.md`](../../../../metta/packages/coworld/src/coworld/docs/roles/reporter.md) in metta), the reporter reads one env var and writes one env var:

| Env var | Direction | Purpose |
| --- | --- | --- |
| `COGAME_EPISODE_BUNDLE_URI` | read | URI of the episode-bundle zip. The reporter opens it, inspects its inner `manifest.json`, and reads the entries it needs: `results.json` (`scores`, `painted_tiles`, `ticks`), `replay.json` (the replay's `config` block for grid dimensions, plus per-frame `{tick, positions, tile_owners}` for proximity events and back-and-forth highlights), and optional `config.json`. |
| `COGAME_REPORT_URI` | write | Write target for the output zip (`Content-Type: application/zip`). |

The episode bundle's contract is documented in [`EPISODE_BUNDLE_README.md`](../../../../metta/packages/coworld/src/coworld/EPISODE_BUNDLE_README.md) in metta. Episode-metadata fields the reporter populates in `stats.json` (`episode_id`, `variant_id`, per-slot `policy_name`, `duration_seconds`) come from the bundle's `manifest.json` and the embedded `replay.json` / `results.json`.

## Failure modes

| Situation | Behavior |
| --- | --- |
| All inputs valid, normal episode | Exit 0, valid zip with `manifest.json`, `summary.html`, `stats.json`, `proximity.parquet` |
| `painted_tiles` all zero | Exit 0; summary says "no tiles were painted"; `winner_slot: null` |
| Tied painted-tile counts | Exit 0; summary says "tied at N tiles"; `winner_slot: null`, `tie: true` |
| Replay with no frames | Exit 0; HTML highlights section shows the empty state; `proximity.parquet` is a well-formed zero-row table |
| Replay JSON missing `config`, or `config` missing `width`/`height` | Exit 1; no zip written |
| Results JSON missing required field or unparseable | Exit 1; no zip written |
| `COGAME_EPISODE_BUNDLE_URI` missing/unreachable, or `COGAME_REPORT_URI` unwritable | Exit 1; error logged to stderr |
| Bundle's inner `manifest.json` reports `status: "failed"` and required artifacts absent | Exit 1; the reporter cannot operate on missing inputs |

See [`DESIGN.md`](DESIGN.md) for the full failure-mode table.

## Running locally

```bash
COGAME_EPISODE_BUNDLE_URI=file:///path/to/bundle.zip \
COGAME_REPORT_URI=file:///path/to/report.zip \
python paint_arena_summarizer.py
```

Both `file://` and `http(s)://` URIs are supported. HTTP requests retry on 429 and 5xx (5 attempts, exponential backoff).

Assemble a local bundle from a runner workspace via metta's CLI:

```bash
uv run coworld bundle <ereq_id> --output /tmp/bundle.zip --include results,replay,config
```

## Building the image

```bash
./build.sh                              # builds paint-arena-summarizer:latest for linux/amd64
IMAGE=ghcr.io/.../par:1 ./build.sh      # override tag
PLATFORM=linux/arm64 ./build.sh         # override platform (local-only; rejected by coworld upload)
```

`build.sh` defaults to `--platform linux/amd64` because `coworld upload` requires amd64 (hosted episodes run on amd64) and would reject a host-arch build from Apple Silicon. On non-amd64 hosts the build and any subsequent `docker run` happen under emulation, which is slower but keeps the locally tested image byte-identical to the uploadable image.

The Docker build context is `reporters/` (the directory containing `reporter_sdk/` and per-Coworld trees), so the Dockerfile can `COPY` both the shared SDK and the reporter source from one context. The SDK is installed even though its public surface is currently empty — this reserves the import path for the imminent extraction.

Each reporter ships its own `Dockerfile.dockerignore` (allowlist style) so the build context contains only the SDK plus that reporter's runtime source. Docker 25+ honors the per-Dockerfile ignore file in preference to a `reporters/.dockerignore` at the context root, which lets each reporter scope its own includes.

## Tests

```bash
uv run pytest reporters/paint_arena/paint_arena_summarizer/tests/ -v
```

Covers happy path, zero-paint, tie, replay missing-or-malformed `config`, replay with no frames, malformed and unparseable results, missing env vars, zip shape and in-zip `manifest.json` consistency (`render` and `event_log` paths exist; `render` has a renderable extension; `event_log` is Parquet), pinned zip-entry mtimes, HTTP retry policy (transient retries, capped attempts, exact backoff schedule), and a determinism check (two runs over the same inputs produce byte-identical zip bytes). Frame-derived logic is covered separately: proximity-event extraction (including the >2-slot generic case), tile-flip detection (only painted→painted transitions count), and back-and-forth window detection (`min_flips`, `window_ticks`, `max_results`). Parquet content is asserted to use the canonical `(ts, player, key, value)` schema with `proximity` and `back_and_forth` `key` values.

### Containerized smoke test

```bash
./smoke.sh                  # builds + runs the image against smoke/fixtures/
IMAGE=ghcr.io/.../par:1 ./smoke.sh
```

Builds the image, runs the container against checked-in fixtures under `smoke/fixtures/`, mounts a `mktemp -d` directory for the output zip, and asserts the canonical zip contract (`manifest.json` flags `render: summary.html` and `event_log: proximity.parquet`; both target paths exist in the zip; `render` has a renderable extension; `event_log` is Parquet), pinned mtimes, that grid dimensions resolve from the replay's `config` block, that `summary.html` looks like a self-contained HTML document, and that `proximity.parquet` is non-empty when the fixture has frames.

## SDK extraction candidates (inline today)

The following primitives are in `paint_arena_summarizer.py` and slated for promotion to [`reporter_sdk`](../../reporter_sdk/) once this reporter migrates to the canonical contract:

- Bundle reader — opens the bundle zip from `COGAME_EPISODE_BUNDLE_URI`, parses its inner `manifest.json`, exposes typed accessors for the standard bundle tokens.
- `read_uri` / `write_uri` / `read_json` (scheme-dispatched `file://` and `http(s)://` with retry).
- `write_deterministic_zip(entries)` — `zipfile.ZipFile` helper with pinned mtimes for byte-identical reruns.
- In-zip `manifest.json` writer — validates that `render` points at an existing `.md`/`.html` entry and `event_log` points at an existing Parquet entry.
- `EVENT_LOG_SCHEMA` + `write_events_parquet(rows)` — the canonical `(ts, player, key, value)` event-log schema and its pyarrow writer; intended to be reused across reporters.

The PaintArena-specific parts (`build_stats`, `build_proximity_rows`, `extract_tile_flips`, `detect_back_and_forth_highlights`, `render_summary_html`, the `PaintArenaReplay` / `ReplayConfig` / `PaintArenaFrame` parsing, the choice of which auxiliary files to include and which to flag as `render` / `event_log`) stay in this file — replay-shape coupling is Coworld-specific and intentionally not promotion material, and the in-zip file layout is the reporter author's decision.
