# reporter_sdk

Shared, pip-installable Python package providing the primitives every Coworld reporter in this repo programs against.

> **Status: still intentionally on hold.** The package exists and is installable but exposes no real surface yet. The two implemented reporters — [`reporters/paint_arena/paint_arena_summarizer`](../paint_arena/paint_arena_summarizer/) and [`reporters/among_them/among_them_summarizer`](../among_them/among_them_summarizer/) — both inline the primitives that will live here. The SDK's API will be *extracted* from those two reporters once their shared canonical shape is stable; see the "Build strategy" section of the [root README](../../README.md) for the rationale. The skeleton exists now so the import path is reserved and the package is wired up for an editable install whenever it becomes useful.
>
> The two reporters are currently pre-canonical (input via multiple per-artifact env vars; render manifest as `render.txt`). The SDK extraction is gated on those two reporters first migrating to the canonical `COGAME_EPISODE_BUNDLE_URI` / `COGAME_REPORT_URI` shape with an in-zip `manifest.json`; otherwise the SDK would crystallize the pre-canonical contract.

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
├── README.md            # this file
├── pyproject.toml       # pip-installable, hatchling backend, requires Python >=3.13
└── reporter_sdk/        # the importable package
    └── __init__.py
```

Flat (non-`src/`) layout for consistency with the rest of the repo. Public API is whatever `reporter_sdk/__init__.py` re-exports; submodules will be added per feature as concrete needs surface.

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

## Extraction candidates (still inline in the two reporters)

These primitives are duplicated between `paint_arena_summarizer.py` and `among_them_summarizer.py`; they're the shopping list for the upcoming extraction pass. Names are indicative — the canonical-contract migration of the two reporters will reshape some of them.

- **Bundle reader** — opens the bundle zip pointed at by `COGAME_EPISODE_BUNDLE_URI`, reads its inner `manifest.json`, exposes typed accessors for the standard bundle tokens (`results`, `replay`, `config`, `game_logs`, `player_logs`, `error_info`). Replaces today's collection of per-artifact URI env-var readers.
- **Output `manifest.json` writer** — emits the in-zip `manifest.json` flagging `reporter_id`, `render`, and `event_log`. Validates that `render` resolves to an existing `.md` or `.html` entry and `event_log` resolves to an existing Parquet entry.
- **`write_deterministic_zip(entries)`** — `zipfile.ZipFile` helper with pinned `date_time=(1980, 1, 1, 0, 0, 0)` for byte-identical reruns over identical inputs.
- **I/O helpers** — `read_uri(uri) -> bytes`, `write_uri(uri, payload, content_type)`, `read_json(uri)` — scheme-dispatched over `file://`, `http(s)://`, and presigned S3 with retries on 429/5xx (5 attempts, exponential backoff). Aligned with metta's `runner/io.py`.
- **`EVENT_LOG_SCHEMA`** — the canonical `(ts: int64, player: int64, key: string, value: string)` Parquet schema — plus a `write_events_parquet(rows)` writer.
- **`_stable_json(obj)`** — `json.dumps(obj, sort_keys=True, separators=(",", ":"))` for byte-identical Parquet payloads embedded as `value` strings in event-log rows.

Each reporter labels its own inline primitives in `DESIGN.md` ("Inline primitives" section) so the extraction pass has a clear inventory.

## Usage (post-extraction sketch)

```python
# Indicative — actual API will be added during extraction.
from reporter_sdk import (
    BundleReader,
    ReportZipWriter,
    EVENT_LOG_SCHEMA,
    write_events_parquet,
    read_env_uris,
)

bundle_uri, report_uri = read_env_uris()  # COGAME_EPISODE_BUNDLE_URI, COGAME_REPORT_URI

with BundleReader(bundle_uri) as bundle:
    results = bundle.read_json("results")
    replay = bundle.read_json("replay")
    config = bundle.read_json_optional("config")

    # ... build per-Coworld stats / HTML / event rows ...

    summary_html_bytes = render_summary(results, replay)
    stats_json_bytes = serialize_stats(results)
    events_parquet_bytes = write_events_parquet(event_rows)

writer = ReportZipWriter(reporter_id="paint-arena-summarizer", deterministic=True)
writer.add("summary.html", summary_html_bytes)
writer.add("stats.json", stats_json_bytes)
writer.add("proximity.parquet", events_parquet_bytes)
writer.set_render("summary.html")
writer.set_event_log("proximity.parquet")
writer.write(report_uri)
```

Treat the canonical contract — [`packages/coworld/src/coworld/docs/roles/reporter.md`](../../../metta/packages/coworld/src/coworld/docs/roles/reporter.md) in metta — as the source of truth; the SDK is the implementation of that contract. If the SDK and the metta doc disagree, the metta doc wins and the SDK is wrong.

## Versioning

`0.0.0` until the extraction pass produces the first real public API. From there, SemVer:

- **0.x.y** — pre-1.0, breaking changes allowed at minor bumps. Coordinate via the commit that introduces the break.
- **1.0.0** — first release once both PaintArena and Among Them reporters import a stable surface against the canonical contract.

Because reporters build against repo-HEAD by default, breaking changes require updating every consumer in the same commit. Treat that as the forcing function for keeping the API small and considered.

## References

- [`../../README.md`](../../README.md) — repository overview and canonical contract summary.
- [`../../docs/REPORTER_DESIGN.md`](../../docs/REPORTER_DESIGN.md) — local restatement of the canonical contract + repo-local notes (migration state, repo conventions).
- [`packages/coworld/src/coworld/docs/roles/reporter.md`](../../../metta/packages/coworld/src/coworld/docs/roles/reporter.md) in metta — **canonical reporter role contract** the SDK encodes.
- [`packages/coworld/src/coworld/EPISODE_BUNDLE_README.md`](../../../metta/packages/coworld/src/coworld/EPISODE_BUNDLE_README.md) in metta — bundle contract the SDK's bundle reader implements.
- [`../paint_arena/paint_arena_summarizer/`](../paint_arena/paint_arena_summarizer/) and [`../among_them/among_them_summarizer/`](../among_them/among_them_summarizer/) — the two concrete reporters whose inline primitives are the source material for extraction.
- [`../templates/`](../templates/) — template reporter scaffolds (will be extracted from the concrete reporters after the SDK lands).
