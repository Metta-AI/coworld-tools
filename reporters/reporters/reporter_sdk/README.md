# reporter_sdk

Shared, pip-installable Python package providing the primitives every coworld reporter in this repo programs against.

> **Status: still intentionally on hold.** The package exists and is installable but exposes no real surface yet. The two implemented reporters — [`reporters/paint_arena/paint_arena_summarizer`](../paint_arena/paint_arena_summarizer/) and [`reporters/among_them/among_them_summarizer`](../among_them/among_them_summarizer/) — both inline the primitives that will live here. The SDK's API will be *extracted* from those two reporters once their shared shape is stable; see the "Build strategy" section of the [root README](../../README.md) for the rationale. The skeleton exists now so the import path is reserved and the package is wired up for an editable install whenever it becomes useful.

## Purpose

Encode the v1 coworld reporter contract — defined in [`../../docs/REPORTER_DESIGN.md`](../../docs/REPORTER_DESIGN.md) (decisions D1–D12) — once, in one importable place. Concrete reporters consume the SDK so they do not each re-derive the deterministic zip writer, the `(ts, player, key, value)` event-log schema, env-supplied URI resolution, or contract-aligned types from the design document.

Scope is deliberately narrow:

- **In scope:** the D12 zip writer with pinned-mtime determinism, `render.txt` assembly + validation, env-var URI accessors, `runner/io.py`-compatible I/O wrappers, the shared parquet event-log schema, shared dataclasses/Pydantic models for episode-metadata shapes, HTTP retry helpers.
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

For per-reporter Docker builds, the SDK is installed from the build context. Each reporter's `build.sh` is expected to set the build context to `reporters/` (from the repo root — i.e. the directory containing `reporter_sdk/`, `templates/`, and the per-coworld reporter directories) so the SDK and the reporter source are both reachable. Sketch of a reporter Dockerfile:

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

These primitives are duplicated verbatim between `paint_arena_summarizer.py` and `among_them_summarizer.py`; they're the shopping list for the upcoming extraction pass:

- `ReporterInputs` (Pydantic model) + `load_reporter_inputs()` — reads the `COGAME_*` env vars into a typed value.
- `read_uri(uri) -> bytes` / `write_uri(uri, payload, content_type)` / `read_json(uri)` — scheme-dispatched I/O over `file://` and `http(s)://` with retries on 429/5xx (5 attempts, exponential backoff).
- `write_deterministic_zip(entries)` — `zipfile.ZipFile` helper with pinned `date_time=(1980, 1, 1, 0, 0, 0)` for byte-identical reruns per D12.
- `EVENT_LOG_SCHEMA` (the `(ts: int64, player: int16, key: string, value: string)` pyarrow schema) + `write_events_parquet(rows)` — the shared event-log columnar shape used by both reporters and intended for cross-coworld aggregation.
- `_stable_json(obj)` — `json.dumps(obj, sort_keys=True, separators=(",", ":"))` for byte-identical parquet payloads.

Each reporter labels these in its own `DESIGN.md` ("Inline primitives" section) so the extraction pass has a clear inventory.

## Usage (post-extraction sketch)

```python
# Indicative — actual API will be added during extraction.
from reporter_sdk import (
    ReporterInputs,
    load_reporter_inputs,
    read_json,
    write_uri,
    write_deterministic_zip,
    EVENT_LOG_SCHEMA,
    write_events_parquet,
)

inputs: ReporterInputs = load_reporter_inputs()
results = read_json(inputs.results_uri)
# ... build per-coworld stats / HTML / event rows ...
zip_bytes = write_deterministic_zip([
    ("summary.html", summary_html_bytes),
    ("stats.json", stats_json_bytes),
    ("events.parquet", events_parquet_bytes),
    ("render.txt", b"summary.html\n"),
])
write_uri(inputs.report_output_uri, zip_bytes, content_type="application/zip")
```

Treat the contract in [`../../docs/REPORTER_DESIGN.md`](../../docs/REPORTER_DESIGN.md) (especially D1, D2, D4, D10, D11, D12) as the source of truth; the SDK is the implementation of that contract.

## Versioning

`0.0.0` until the extraction pass produces the first real public API. From there, SemVer:

- **0.x.y** — pre-1.0, breaking changes allowed at minor bumps. Coordinate via the commit that introduces the break.
- **1.0.0** — first release once both PaintArena and Among Them reporters import a stable surface.

Because reporters build against repo-HEAD by default, breaking changes require updating every consumer in the same commit. Treat that as the forcing function for keeping the API small and considered.

## References

- [`../../README.md`](../../README.md) — repository overview and v1 contract summary.
- [`../../docs/REPORTER_DESIGN.md`](../../docs/REPORTER_DESIGN.md) — full v1 design and decisions log (D1–D12). The SDK exists to encode this document; if the two disagree, the design doc wins and the SDK is wrong.
- [`../paint_arena/paint_arena_summarizer/`](../paint_arena/paint_arena_summarizer/) and [`../among_them/among_them_summarizer/`](../among_them/among_them_summarizer/) — the two concrete reporters whose inline primitives are the source material for extraction.
- [`../templates/`](../templates/) — template reporter scaffolds (will be extracted from the concrete reporters after the SDK lands).
