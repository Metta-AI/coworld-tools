# paint_arena_summarizer — Design

> **Status:** implemented on the D12 zip + `render.txt` contract. `paint_arena_summarizer.py` plus a `pytest` suite covers the failure-mode table below; `Dockerfile` and `build.sh` are functional. This is the first concrete reporter in the repo and was intentionally built before `reporter_sdk` and `templates/summarizer_template`. The "Inline primitives" section below remains the extraction shopping list for the next step. See the [root README](../../../README.md) "Build strategy" section for the broader rationale.
>
> **Output evolution (2026-05-20):** the summary is now rendered HTML (replacing Markdown) and the zip carries a per-tick `proximity.parquet` event log alongside `stats.json`. Both additions are driven by reading the replay's `frames` (previously ignored), so the reporter is no longer purely a function of `config`.

## Purpose

Produce a per-episode human-readable summary, a machine-readable stats artifact, and a per-tick event log for the PaintArena coworld. Pure function of `COGAME_RESULTS_URI` + `COGAME_EPISODE_METADATA_URI` + `COGAME_REPLAY_URI`; deterministic within one image (pyarrow version is pinned in `requirements.txt`); no log access in v1.

This document is load-bearing in two directions: it specifies what the implementation must do, and it records the decisions the SDK extraction pass will refer back to.

## Inputs

| Env var | Used? | Why |
| --- | --- | --- |
| `COGAME_RESULTS_URI` | **Yes** | Source of `scores` / `painted_tiles` / `ticks`. |
| `COGAME_EPISODE_METADATA_URI` | **Yes** | Per-slot `policy_name`, `started_at`/`ended_at`/`duration_seconds`, `episode_id`, `variant_id`. |
| `COGAME_REPLAY_URI` | **Yes** | Source of `config.{width,height}` for the grid total-tile count and `frames[*]` for proximity + back-and-forth analysis. PaintArena's game server embeds its `CONFIG` and the per-tick snapshots in `_replay_payload`. |
| `COGAME_REPORTER_ID` | Logs only | Stamped into log lines for observability; not used for output content. |
| `COGAME_REPORT_OUTPUT_URI` | **Yes** | Write target for the zip. |
| `COGAME_LOG_URI` | No | Not consumed in v1. |

## Output zip (D12)

Per REPORTER_DESIGN.md D12, the reporter writes a single zip to `COGAME_REPORT_OUTPUT_URI` with `Content-Type: application/zip`. Top-level layout:

```
report.zip
├── summary.html        # rendered inline (listed in render.txt)
├── stats.json          # download-only (not in render.txt; surfaced from HTML footer)
├── proximity.parquet   # download-only; per-tick event log in shared (ts, player, key, value) schema
└── render.txt          # single line: "summary.html\n"
```

`render.txt` lists only files Observatory renders inline. The renderable-extension allowlist in D12 is `.md` / `.txt` / `.html` / `.htm`; `stats.json` and `proximity.parquet` are intentionally outside that allowlist and stay download-only. Zip-entry mtimes are pinned to `(1980, 1, 1, 0, 0, 0)` so byte-identical reruns over identical inputs produce byte-identical zip bytes (D12 determinism clause).

### `summary.html` (rendered)

A single self-contained HTML page — inline CSS only, no `<script>` or `<link>` tags — so it can render safely inside Observatory's iframe+CSP sandbox without any external fetches. Sections, top to bottom:

1. **Header** — episode id, variant, grid dimensions, duration.
2. **Verdict card** — winner / tie / no-paint, with a colored swatch matching the slot's heatmap color.
3. **Final-grid heatmap** — an SVG of the last frame's `tile_owners`, one rounded `<rect>` per tile, colored per owning slot (unpainted = `#e9ecef`).
4. **Tiles painted table** — per-slot rows with policy name, tile count, share percentage, and a proportional colored bar. Includes an "unpainted" row.
5. **Back-and-forth highlights** — up to `HIGHLIGHT_MAX_RESULTS` cards (default 5), each with a small SVG locator (the contested tile haloed against the dimmed final grid), the tile coordinate, the re-paint count, the tick range, and the involved slots. If no contested tiles meet the threshold, an explanatory empty-state line shows the threshold parameters.
6. **Footer** — proximity-event count (a hint that `proximity.parquet` is worth opening) and reference to `stats.json`.

Constants live in the module as `_SLOT_COLORS`, `PROXIMITY_THRESHOLD`, `HIGHLIGHT_MIN_FLIPS`, `HIGHLIGHT_WINDOW_TICKS`, `HIGHLIGHT_MAX_RESULTS`.

### `stats.json` (download-only)

```jsonc
{
  "episode_id": "ep_abc123",
  "variant_id": "default",
  "grid": { "width": 12, "height": 8, "total_tiles": 96 },
  "ticks": 100,
  "duration_seconds": 19.4,
  "slots": [
    { "slot": 0, "policy_name": "champion-v3", "painted_tiles": 47, "share_pct": 48.96 },
    { "slot": 1, "policy_name": "starter",     "painted_tiles": 38, "share_pct": 39.58 }
  ],
  "unpainted_tiles": 11,
  "unpainted_share_pct": 11.46,
  "winner_slot": 0,
  "margin_tiles": 9,
  "tie": false,
  "proximity_event_count": 7,
  "highlights": [
    { "x": 5, "y": 3, "tick_start": 11, "tick_end": 14, "flips": 4, "slots": [0, 1] }
  ]
}
```

Generalized over slot count (results schema allows 1–4; iterate, don't hard-code 2). `painted_tiles` is the int from results; `scores` is dropped from output because it's just `painted_tiles` cast to float (no information). `proximity_event_count` mirrors the row count of `proximity.parquet`'s `proximity` rows; `highlights` mirrors its `back_and_forth` rows.

### `proximity.parquet` (download-only)

Encodes frame-derived facts in a generic event-log schema shared across reporters:

| Column | Type | Meaning |
| --- | --- | --- |
| `ts` | int64 | Replay tick (PaintArena's `frame.tick`). |
| `player` | int16 | Slot index, or `-1` for global / pair-level facts. |
| `key` | string | Event kind. v1 emits `"proximity"` and `"back_and_forth"`. |
| `value` | string | JSON-encoded payload; structure depends on `key`. |

Two `key` kinds today:

- **`proximity`** — one row per (tick, unordered slot-pair) where the two slots' Chebyshev (king-move) distance is `≤ PROXIMITY_THRESHOLD` (default 2). `player = -1`. The JSON payload is `{"slot_a", "slot_b", "pos_a", "pos_b", "chebyshev_distance", "tile_owner_a", "tile_owner_b"}`. Generic-over-slot-count: for an N-slot frame, every unordered pair within range gets a row.
- **`back_and_forth`** — one row per detected highlight, anchored at the window's last flip (`ts = tick_end`). `player = -1`. Payload is `{"x", "y", "tick_start", "tick_end", "flips", "slots"}`.

Determinism: pyarrow stamps a `created_by` string into the file footer that includes its own version. The Docker image pins `pyarrow` in `requirements.txt`, so two runs of the *same image* over identical inputs produce byte-identical parquet bytes. The pytest determinism check (`test_run_is_byte_identical_on_rerun`) exercises this within one process.

## Frame-derived analytics

### Proximity events
For each frame `f`, for each unordered slot pair `(i, j)`, compute Chebyshev distance `max(|xi - xj|, |yi - yj|)`. If `≤ PROXIMITY_THRESHOLD` (default 2), emit a row.

### Back-and-forth highlights
A "flip" is a tile-ownership transition between two *distinct, non-`-1`* slots in consecutive frames; first-time paints (`-1 → slot`) are excluded, because we're looking for contested ground, not the initial brush stroke.

For each tile that has ≥1 flip, slide a window of width `HIGHLIGHT_WINDOW_TICKS` (default 10) over its flip list and find the window with the most flips. If that maximum is ≥`HIGHLIGHT_MIN_FLIPS` (default 2), record a `Highlight` for that tile. Sort highlights by flip-count descending, then earliest first; keep the top `HIGHLIGHT_MAX_RESULTS` (default 5). At most one highlight per distinct tile.

Tradeoffs:

- **Why Chebyshev for proximity, not Manhattan or Euclidean?** Agents move on a grid in 8 directions (the game's `DIRECTIONS` dict — see `paintarena/game/server.py`); Chebyshev matches the metric the game itself uses for "one step away." Threshold 2 means "within 2 king-moves," which roughly captures the "they could collide next tick" relationship.
- **Why exclude `-1 → slot` from flip counting?** First-paint events would otherwise drown out the actual contested-tile signal — every tile painted exactly once would be reported as a flip-1 "highlight" with no opponent involvement.
- **Why one highlight per tile (not per window)?** Overlapping windows on the same tile would all surface the same incident; deduping by tile keeps the HTML legible.

## Decisions locked in

1. **Grid-coverage percentages, not within-painted ratios.** Knowing the grid dimensions answers the natural "did you cover the board?" question. Originally sourced via a manifest-variant lookup; since REPORTER_DESIGN.md D11 dropped the manifest URI, the same dimensions come from the replay's `config` block.
2. **`policy_name` from episode metadata for player display**, falling back to `"Slot N"` when null (e.g. certification context with no real policy). `policy_name` is the tournament-meaningful identity; variant-config `player_names` is cosmetic and ignored.
3. **HTML, not Markdown, for the rendered summary.** Markdown was fine when the summary was a table and a one-line verdict; once we wanted a heatmap, color swatches, and small contested-tile locators, raw HTML with inline SVG is the simpler primitive than fighting Markdown's renderer over images. The page is self-contained (inline CSS, no scripts, no external links) so it renders in Observatory's iframe+CSP sandbox without network access.
4. **`stats.json` retained alongside `proximity.parquet`.** They answer different questions: `stats.json` is the per-episode summary (winner, share, highlight count); the parquet is the per-tick event log a downstream notebook would join across many episodes. Both stay in the zip.
5. **Generic event-log schema (`ts, player, key, value`) for the parquet.** The columns are stable across reporters; new event kinds are new `key` values with JSON payloads, not new columns. `player = -1` denotes a pair-level or tile-level fact. This is the same schema other coworld reporters will reuse.
6. **Generic-over-slot-count.** Iterate `painted_tiles`; iterate every unordered pair `(i, j)`; do not hard-code 2 players.
7. **Couple to PaintArena's replay shape, not to a generic schema.** This reporter is a PaintArena-coworld build artifact; the `config.{width,height}` and per-frame `{tick, positions, tile_owners}` access paths are hard-wired to what `paintarena/game/server.py::_snapshot` writes. The replay format is owned by the same coworld bundle, so this is acceptable per REPORTER_DESIGN.md D11.
8. **Pinned mtime for zip determinism.** All zip entries use `date_time=(1980, 1, 1, 0, 0, 0)`. Required by D12's byte-identical-rerun guarantee. Parquet's own determinism is bounded by the pinned pyarrow version (see "Determinism note" in `write_events_parquet`).

## Failure-mode behavior

| Situation | Behavior | Exit |
| --- | --- | --- |
| All inputs valid, normal episode | Write zip with `summary.html`, `stats.json`, `proximity.parquet`, `render.txt` | 0 |
| `painted_tiles` sums to 0 (no tiles painted) | Write zip; summary says "no tiles were painted; no winner"; stats has `winner_slot: null`, `tie: false`, `margin_tiles: 0` | 0 |
| Tied painted-tile counts | Write zip; summary says "tied at N tiles"; stats has `winner_slot: null`, `tie: true`, `margin_tiles: 0` | 0 |
| Replay has zero frames or only 1-agent frames | Write zip; parquet has zero rows but is well-formed; HTML highlights section shows the threshold and an empty-state line | 0 |
| Replay JSON missing `config` block, or `config` missing `width`/`height` | `ValidationError` propagates; exit non-zero (`nonzero_exit` per D8) | 1 |
| Results JSON missing required field or unparseable | Log error, exit non-zero | 1 |
| Output URI unreachable | Bubble up exception, exit non-zero | 1 |

Per D8 (as amended by D12), the platform will surface these as `nonzero_exit` failure records. The reporter does not produce synthetic "I failed" zips — it either writes a valid zip and exits 0, or it exits non-zero.

## Inline primitives (the SDK extraction candidates)

These primitives live inline in `paint_arena_summarizer.py` for v1. The SDK extraction pass will lift what proves general:

- `ReporterInputs` typed-dict / dataclass and `load_reporter_inputs()` reading all `COGAME_*` env vars.
- `read_uri(uri) -> bytes` / `write_uri(uri, payload, content_type)` — scheme-dispatched (`file://`, `http(s)://`) with retries on 429/5xx for HTTP. Stdlib + `requests`.
- `write_deterministic_zip(entries)` — `zipfile.ZipFile` writer that pins each entry's `date_time` to `(1980, 1, 1, 0, 0, 0)` and uses `ZIP_DEFLATED`. The minimum scaffolding for the D12 contract; any reporter that wants byte-identical reruns needs this helper.
- `EVENT_LOG_SCHEMA` (`(ts, player, key, value)` pyarrow schema) and `write_events_parquet(rows)` — the shared event-log schema is intended to be reused by future reporters; both the schema constant and the writer are extraction candidates.

Anything *not* in that list (PaintArena results parsing, replay-`frame` parsing, proximity/flip extraction, the highlight algorithm, summary HTML phrasing, the per-slot percentage math, the `summary.html` / `stats.json` / `proximity.parquet` / `render.txt` file layout) stays in this reporter forever. Replay parsing in particular is coworld-specific by design (D11) and is not a candidate for SDK promotion.

## Determinism and testing

Output is a pure function of (results JSON, episode metadata JSON, replay JSON) within one pinned pyarrow version. Test plan:

- Unit tests with hand-crafted fixture JSONs covering the failure-mode table above.
- Frame-extraction unit tests covering proximity-event extraction (including the generic >2-slot case), tile-flip detection, and back-and-forth window detection.
- Parquet-content tests asserting the shared `(ts, player, key, value)` schema and the two `key` kinds emit the expected payloads.
- Zip-shape assertions: top-level entries are exactly `{summary.html, stats.json, proximity.parquet, render.txt}`; `render.txt` contents are `summary.html\n`; every listed path exists in the zip and has a renderable extension; no duplicates; `render.txt` does not list itself.
- Determinism check: run summarizer twice on the same fixtures, byte-compare the zip output.
- Local end-to-end smoke: `./smoke.sh` builds the image and runs it against `smoke/fixtures/`, asserting the four-entry contract, pinned mtimes, HTML self-containment, and that `proximity.parquet` is non-empty when the fixture has frames.

## Non-goals (v1)

- No log reading.
- No external network calls beyond input/output URIs (D1 purity).
- No LLM involvement.
- No platform-side schema declaration of the `stats` JSON shape (D7 shelved this).
- No multi-reporter coordination (D4 explicitly forbids cross-reporter pipelining anyway).
- No JavaScript in the rendered HTML. The page is intentionally static — Observatory's iframe+CSP sandbox is the deployment target and a scripted page would just create surface area to lose.
- No interactive replay scrubber in HTML. The parquet exists for downstream tools that want to do that work.
