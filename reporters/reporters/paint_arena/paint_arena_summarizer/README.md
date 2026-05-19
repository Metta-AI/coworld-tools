# paint_arena_summarizer

Per-episode summarizer reporter for the PaintArena coworld. Reads results, episode metadata, and the manifest; writes a JSON envelope with a Markdown summary and a JSON stats artifact. First concrete reporter in the repo — its inline primitives are the source material for the upcoming [`reporter_sdk`](../../reporter_sdk/) extraction. See [`DESIGN.md`](DESIGN.md) for the locked-in design.

## Artifacts produced

| `id` | `content_type` | Contents |
| --- | --- | --- |
| `summary` | `text/markdown` | Human-readable per-slot table + winner / tie / no-paint verdict |
| `stats`   | `application/json` | `{episode_id, variant_id, grid, ticks, duration_seconds, slots[], unpainted_tiles, unpainted_share_pct, winner_slot, margin_tiles, tie}` |

The `stats` JSON is generalized over slot count (PaintArena's `results_schema` allows 1–4 players); `winner_slot` is `null` on ties or no-paint episodes. The exact field set is specified in [`DESIGN.md`](DESIGN.md).

## Inputs

Per the v1 reporter contract ([`../../../docs/REPORTER_DESIGN.md`](../../../docs/REPORTER_DESIGN.md), D2/D10), all consumed inputs arrive as env-supplied URIs:

| Env var | Read |
| --- | --- |
| `COGAME_RESULTS_URI` | results JSON: `scores`, `painted_tiles`, `ticks` |
| `COGAME_EPISODE_METADATA_URI` | `episode_id`, `variant_id`, per-slot `policy_name`, `duration_seconds` |
| `COGAME_MANIFEST_URI` | grid `width` × `height` via `variants[].game_config` lookup keyed on `variant_id` |
| `COGAME_REPORT_OUTPUT_URI` | write target for the envelope |
| `COGAME_REPORTER_ID` | stamped into log lines |

`COGAME_REPLAY_URI` and `COGAME_LOG_URI` are not consumed in v1.

## Failure modes

| Situation | Behavior |
| --- | --- |
| All inputs valid, normal episode | Exit 0, full envelope |
| `painted_tiles` all zero | Exit 0; summary says "no tiles were painted; no winner"; `winner_slot: null` |
| Tied painted-tile counts | Exit 0; summary says "tied at N tiles"; `winner_slot: null`, `tie: true` |
| `variant_id` not in manifest's `variants[]` | Exit 1 (`nonzero_exit` per D8); no envelope written |
| Results JSON missing required field or unparseable | Exit 1; no envelope written |
| Required env var missing or output URI unreachable | Exit 1; error logged to stderr |

See [`DESIGN.md`](DESIGN.md) for the full failure-mode table.

## Running locally

```bash
COGAME_RESULTS_URI=file:///path/to/results.json \
COGAME_EPISODE_METADATA_URI=file:///path/to/metadata.json \
COGAME_MANIFEST_URI=file:///path/to/coworld_manifest.json \
COGAME_REPORT_OUTPUT_URI=file:///path/to/report.json \
COGAME_REPORTER_ID=paint-arena-summarizer \
python paint_arena_summarizer.py
```

Both `file://` and `http(s)://` URIs are supported. HTTP requests retry on 429 and 5xx (5 attempts, exponential backoff).

## Building the image

```bash
./build.sh                  # builds paint-arena-summarizer:latest
IMAGE=ghcr.io/.../par:1 ./build.sh
```

The Docker build context is `reporters/` (the directory containing `reporter_sdk/` and per-coworld trees), so the Dockerfile can `COPY` both the shared SDK and the reporter source from one context. The SDK is installed even though its public surface is currently empty — this reserves the import path for the imminent extraction.

## Tests

```bash
uv run pytest reporters/paint_arena/paint_arena_summarizer/tests/ -v
```

Covers happy path, zero-paint, tie, missing-variant, malformed and unparseable results, missing env vars, envelope self-validation, and a determinism check (two runs over the same inputs produce byte-identical output).

## SDK extraction candidates (inline today)

The following primitives are in `paint_arena_summarizer.py` and slated for promotion to `reporter_sdk`:

- `ReporterInputs` dataclass + `load_reporter_inputs()`
- `read_uri` / `write_uri` / `read_json` (scheme-dispatched `file://` and `http(s)://` with retry)
- `Envelope` / `Artifact` dataclasses (`to_json_bytes()` with sorted keys for determinism)
- `validate_envelope()` (D3 dict-shape check)
- `lookup_variant()`

The PaintArena-specific parts (`build_stats`, `render_summary_markdown`, `build_envelope`, the `_validate_results` shape check) stay in this file.
