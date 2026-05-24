# reporter_sdk

Shared, pip-installable Python package providing the primitives every Coworld reporter in this repo programs against.

> **Status: implemented.** Extracted from the two concrete reporters ([`reporters/paint_arena/paint_arena_summarizer`](../paint_arena/paint_arena_summarizer/) and [`reporters/among_them/among_them_summarizer`](../among_them/among_them_summarizer/)) after both migrated to the canonical Coworld reporter contract. Both reporters now import their bundle reader, deterministic zip writer, event-log schema and writer, env-var URI helpers, retrying URI I/O, and validating output-manifest writer from this package. The SDK exposes a small, deliberate surface; everything game-specific stays in the per-Coworld reporter.

## Purpose

Encode the canonical Coworld reporter contract — defined in [`packages/coworld/src/coworld/docs/roles/reporter.md`](../../../metta/packages/coworld/src/coworld/docs/roles/reporter.md) in metta, restated locally in [`../../docs/REPORTER_DESIGN.md`](../../docs/REPORTER_DESIGN.md) — once, in one importable place. Concrete reporters consume the SDK so they do not each re-derive the bundle reader, the deterministic zip writer, the in-zip `manifest.json` writer, the `(ts, player, key, value)` event-log schema, or contract-aligned types.

Scope is deliberately narrow:

- **In scope:**
  - Episode-bundle reader: opens a bundle zip from a `file://` or `https://` URI, parses its inner `manifest.json`, exposes typed accessors for `results.json`, `replay.json`, optional `config.json`, optional logs, optional `error_info.json`.
  - Deterministic zip writer with pinned-mtime support (recommended sentinel: `(1980, 1, 1, 0, 0, 0)`).
  - In-zip `manifest.json` writer for the reporter output: validates that `render` (if set) points at an existing `.md` or `.html` entry and `event_log` (if set) points at an existing Parquet entry.
  - Env-var URI accessors (`COGAME_EPISODE_BUNDLE_URI`, `COGAME_REPORT_URI`).
  - I/O wrappers compatible with metta's `packages/coworld/src/coworld/runner/io.py` (`file://`, `https://`, presigned S3, retries on 429/5xx).
  - The shared Parquet event-log schema and a writer over it.
  - Shared dataclasses / Pydantic models for the bundle's inner `manifest.json` shape and the reporter's output `manifest.json` shape.
- **Out of scope:** anything game-specific (results parsing, replay decoding, summary phrasing). Those belong in the game-specific reporter under `reporters/<coworld>/`.

The SDK is a library, not a framework — it provides primitives reporters call, not a lifecycle reporters fit into. The platform-side lifecycle lives in metta's `packages/coworld/`.

## Layout

```
reporter_sdk/
├── README.md             # this file
├── pyproject.toml        # pip-installable, hatchling backend, requires Python >=3.11
├── reporter_sdk/         # the importable package
│   ├── __init__.py       # re-exports the full public surface
│   ├── bundle.py         # BundleReader, BundleInnerManifest
│   ├── event_log.py      # EVENT_LOG_SCHEMA, write_events_parquet
│   ├── io.py             # ReporterInputs, load_reporter_inputs, read_uri, write_uri, read_json
│   ├── output_manifest.py# OutputManifest, build_report_zip, RENDERABLE_EXTENSIONS, EVENT_LOG_EXTENSIONS
│   └── zip_writer.py     # write_deterministic_zip, stable_json, MTIME_SENTINEL
└── tests/                # per-submodule unit tests
```

Flat (non-`src/`) layout for consistency with the rest of the repo. The public API is whatever `reporter_sdk/__init__.py` re-exports — consumers should reach for symbols via `from reporter_sdk import X` rather than the submodule paths so the layout can evolve without breaking callers.

## Public API

Imported as `from reporter_sdk import X`:

| Symbol | Kind | Purpose |
| --- | --- | --- |
| `BundleReader` | class | Open an episode bundle zip from `file://` / `https://`, parse the inner `manifest.json`, expose typed accessors keyed by token name (`results`, `replay`, `metadata`, ...). |
| `BundleInnerManifest` | pydantic model | The shape of the bundle's inner `manifest.json`: `ereq_id`, `status`, `include`, `files`. `extra="allow"` for forward-compat. |
| `OutputManifest` | pydantic model | The shape of the reporter's own in-zip `manifest.json`: `reporter_id`, optional `render`, optional `event_log`. |
| `build_report_zip(manifest, entries)` | function | Validate `manifest` against `entries` and produce a deterministic zip with `manifest.json` prepended. `render` must point at an in-zip `.md`/`.html`; `event_log` must point at an in-zip `.parquet`. |
| `write_deterministic_zip(entries)` | function | Lower-level deterministic zip writer (used by `build_report_zip` and by reporters that need full control). Pins `date_time=(1980,1,1,0,0,0)` on every entry. |
| `MTIME_SENTINEL` | constant | `(1980, 1, 1, 0, 0, 0)`. |
| `stable_json(obj)` | function | `json.dumps` with `sort_keys=True, separators=(",", ":")`; use for any JSON embedded inside another container (event-log `value` strings, manifest payloads). |
| `EVENT_LOG_SCHEMA` | pyarrow.Schema | `(ts: int64, player: int64, key: string, value: string)`. |
| `write_events_parquet(rows)` | function | Encode event-log rows to Parquet bytes using `EVENT_LOG_SCHEMA`. Empty list → well-formed zero-row table. |
| `ReporterInputs` | pydantic model | `episode_bundle_uri`, `report_uri`. |
| `load_reporter_inputs()` | function | Read both from the canonical env vars (`COGAME_EPISODE_BUNDLE_URI`, `COGAME_REPORT_URI`). Raises `KeyError` if either is missing. |
| `read_uri(uri)` / `write_uri(uri, payload, content_type)` | functions | Dispatched over `file://` and `http(s)://`. HTTP retries on 429/5xx with exponential backoff (5 attempts, capped at 8s). |
| `read_json(uri)` | function | `read_uri` + JSON decode. |
| `RENDERABLE_EXTENSIONS` / `EVENT_LOG_EXTENSIONS` | frozensets | The accepted extensions for `OutputManifest.render` / `OutputManifest.event_log`. |

## Install

For local development against a checkout of this repo:

```bash
# from the repo root
uv pip install -e reporters/reporter_sdk
# or
pip install -e reporters/reporter_sdk
```

For per-reporter Docker builds, the SDK is installed from the build context. Each reporter's `build.sh` is expected to set the build context to `reporters/` (from the repo root — i.e. the directory containing `reporter_sdk/`, `templates/`, and the per-Coworld reporter directories) so the SDK and the reporter source are both reachable. Sketch of a reporter Dockerfile:

```dockerfile
FROM python:3.13-slim
WORKDIR /app
COPY reporter_sdk/ ./reporter_sdk/
COPY <coworld>/<reporter_name>/ ./reporter/
RUN pip install ./reporter_sdk \
 && pip install ./reporter
CMD ["python", "-m", "reporter.<entrypoint>"]
```

Reporters build against repo-HEAD SDK by default. If a reporter ever needs to pin to an older SDK, bump the SDK version, tag the commit, and have that reporter install from a built wheel instead — the package is structured to support this without rework.

## Out of scope

Anything game-specific stays in the per-Coworld reporter:

- Results / replay parsing (PaintArena's `PaintArenaResults`, Among Them's `parse_bitreplay`, etc.).
- Summary-HTML rendering and CSS.
- Event projection from game state into the canonical `(ts, player, key, value)` rows.

Among Them's binary `.bitreplay` decoder is the canonical example of "not an SDK candidate" — see [`reporters/among_them/among_them_summarizer/DESIGN.md`](../among_them/among_them_summarizer/DESIGN.md) (Inline primitives section).

## Usage

```python
import json

from reporter_sdk import (
    BundleReader,
    OutputManifest,
    build_report_zip,
    load_reporter_inputs,
    stable_json,
    write_events_parquet,
    write_uri,
)

REPORTER_ID = "paint-arena-summarizer"

inputs = load_reporter_inputs()  # reads COGAME_EPISODE_BUNDLE_URI / COGAME_REPORT_URI

with BundleReader(inputs.episode_bundle_uri) as bundle:
    inner = bundle.inner_manifest()
    if inner.status != "success":
        raise RuntimeError(f"bundle status={inner.status!r}; cannot operate on failed episode")
    results = bundle.read_json("results")
    replay = bundle.read_json("replay")
    metadata = bundle.read_json_optional("metadata") or {}

# ... build per-Coworld stats / HTML / event rows ...
summary_html_bytes = render_summary(results, replay)
stats_json_bytes = (json.dumps(stats, indent=2) + "\n").encode("utf-8")
events_parquet_bytes = write_events_parquet([
    {"ts": 1, "player": 0, "key": "k", "value": stable_json({"x": 1})},
])

payload = build_report_zip(
    OutputManifest(
        reporter_id=REPORTER_ID,
        render="summary.html",
        event_log="events.parquet",
    ),
    [
        ("summary.html", summary_html_bytes),
        ("stats.json", stats_json_bytes),
        ("events.parquet", events_parquet_bytes),
    ],
)
write_uri(inputs.report_uri, payload, content_type="application/zip")
```

See [`reporters/paint_arena/paint_arena_summarizer/paint_arena_summarizer.py`](../paint_arena/paint_arena_summarizer/paint_arena_summarizer.py) and [`reporters/among_them/among_them_summarizer/among_them_summarizer.py`](../among_them/among_them_summarizer/among_them_summarizer.py) for full working examples.

Treat the canonical contract — [`packages/coworld/src/coworld/docs/roles/reporter.md`](../../../metta/packages/coworld/src/coworld/docs/roles/reporter.md) in metta — as the source of truth; the SDK is the implementation of that contract. If the SDK and the metta doc disagree, the metta doc wins and the SDK is wrong.

## Versioning

`0.1.0` — first release with a real public API, extracted from the two concrete reporters. SemVer from here:

- **0.x.y** — pre-1.0, breaking changes allowed at minor bumps. Coordinate via the commit that introduces the break.
- **1.0.0** — first release once the API is stable across both in-repo reporters and the metta-side reference reporters that consume the SDK across a repo boundary.

Because reporters build against repo-HEAD by default, breaking changes require updating every consumer in the same commit. Treat that as the forcing function for keeping the API small and considered.

## References

- [`../../README.md`](../../README.md) — repository overview and canonical contract summary.
- [`../../docs/REPORTER_DESIGN.md`](../../docs/REPORTER_DESIGN.md) — local restatement of the canonical contract + repo-local notes (migration state, repo conventions).
- [`packages/coworld/src/coworld/docs/roles/reporter.md`](../../../metta/packages/coworld/src/coworld/docs/roles/reporter.md) in metta — **canonical reporter role contract** the SDK encodes.
- [`packages/coworld/src/coworld/EPISODE_BUNDLE_README.md`](../../../metta/packages/coworld/src/coworld/EPISODE_BUNDLE_README.md) in metta — bundle contract the SDK's bundle reader implements.
- [`../paint_arena/paint_arena_summarizer/`](../paint_arena/paint_arena_summarizer/) and [`../among_them/among_them_summarizer/`](../among_them/among_them_summarizer/) — the two concrete reporters whose inline primitives are the source material for extraction.
- [`../templates/`](../templates/) — template reporter scaffolds (will be extracted from the concrete reporters after the SDK lands).
