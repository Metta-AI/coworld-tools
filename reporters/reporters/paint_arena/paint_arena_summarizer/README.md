# paint_arena_summarizer

Per-episode summarizer reporter for the PaintArena coworld. Reads results, episode metadata, and the replay's `config` block; writes a JSON envelope with a Markdown summary and a JSON stats artifact. First concrete reporter in the repo — its inline primitives are the source material for the upcoming [`reporter_sdk`](../../reporter_sdk/) extraction. See [`DESIGN.md`](DESIGN.md) for the locked-in design.

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
| `COGAME_REPLAY_URI` | grid `width` × `height` via the replay's `config` block (PaintArena's game server embeds `CONFIG` in the replay payload) |
| `COGAME_REPORT_OUTPUT_URI` | write target for the envelope |
| `COGAME_REPORTER_ID` | stamped into log lines |

`COGAME_LOG_URI` is not consumed in v1; the replay's `frames` array is also ignored — only `config` is read.

## Failure modes

| Situation | Behavior |
| --- | --- |
| All inputs valid, normal episode | Exit 0, full envelope |
| `painted_tiles` all zero | Exit 0; summary says "no tiles were painted; no winner"; `winner_slot: null` |
| Tied painted-tile counts | Exit 0; summary says "tied at N tiles"; `winner_slot: null`, `tie: true` |
| Replay JSON missing `config`, or `config` missing `width`/`height` | Exit 1 (`nonzero_exit` per D8); no envelope written |
| Results JSON missing required field or unparseable | Exit 1; no envelope written |
| Required env var missing or output URI unreachable | Exit 1; error logged to stderr |

See [`DESIGN.md`](DESIGN.md) for the full failure-mode table.

## Running locally

```bash
COGAME_RESULTS_URI=file:///path/to/results.json \
COGAME_EPISODE_METADATA_URI=file:///path/to/metadata.json \
COGAME_REPLAY_URI=file:///path/to/replay.json \
COGAME_REPORT_OUTPUT_URI=file:///path/to/report.json \
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

Each reporter ships its own `Dockerfile.dockerignore` (allowlist style) so the build context contains only the SDK plus that reporter's runtime source. Docker 25+ honors the per-Dockerfile ignore file in preference to a `reporters/.dockerignore` at the context root, which lets each reporter scope its own includes. The paint_arena_summarizer context transfers ~460 B.

## Tests

```bash
uv run pytest reporters/paint_arena/paint_arena_summarizer/tests/ -v
```

Covers happy path, zero-paint, tie, replay missing-or-malformed `config`, malformed and unparseable results, missing env vars, envelope self-validation, key-order regression, HTTP retry policy (transient retries, capped attempts, exact backoff schedule), and a determinism check (two runs over the same inputs produce byte-identical output).

### Containerized smoke test

```bash
./smoke.sh                  # builds + runs the image against smoke/fixtures/
IMAGE=ghcr.io/.../par:1 ./smoke.sh
```

Builds the image, runs the container against checked-in fixtures under `smoke/fixtures/`, mounts a `mktemp -d` directory for the output envelope, and asserts envelope shape (version, two artifacts in `[summary, stats]` order, expected content types), key ordering (top-level and per-artifact, both parsed and bytewise), and that grid dimensions resolve from the replay's `config` block. This is the integration-level check that the *packaged image* still satisfies the contract; the pytest suite is the fast iteration loop.

## SDK extraction candidates (inline today)

The following primitives are in `paint_arena_summarizer.py` and slated for promotion to `reporter_sdk`:

- `ReporterInputs` dataclass + `load_reporter_inputs()`
- `read_uri` / `write_uri` / `read_json` (scheme-dispatched `file://` and `http(s)://` with retry)
- `Envelope` / `Artifact` dataclasses (`to_json_bytes()` with sorted keys for determinism)
- `validate_envelope()` (D3 dict-shape check)

The PaintArena-specific parts (`build_stats`, `render_summary_markdown`, `build_envelope`, the `PaintArenaReplay` / `ReplayConfig` parsing) stay in this file — replay-shape coupling is coworld-specific by D11 and intentionally not promotion material.
