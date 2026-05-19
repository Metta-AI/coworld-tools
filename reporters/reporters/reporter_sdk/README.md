# reporter_sdk

Shared, pip-installable Python package providing the primitives every coworld reporter in this repo programs against.

> **Status: intentionally on hold.** The package exists and is installable but exposes no real surface yet, and we are deliberately **not** adding one until [`reporters/paint_arena/paint_arena_summarizer`](../paint_arena/paint_arena_summarizer/) is built end-to-end with its primitives inline. The SDK's API will then be *extracted* from that reporter — see the "Build strategy" section of the [root README](../../README.md) for the rationale. The skeleton exists now so the import path is reserved and the package is wired up for an editable install whenever it becomes useful.

## Purpose

Encode the v1 coworld reporter contract — defined in [`../../docs/REPORTER_DESIGN.md`](../../docs/REPORTER_DESIGN.md) — once, in one importable place. Concrete reporters consume the SDK so they do not each re-derive envelope construction, env-supplied URI resolution, or contract-aligned types from the design document.

Scope is deliberately narrow:

- **In scope:** envelope schema and builders, env-var URI accessors, `runner/io.py`-compatible I/O wrappers, shared dataclasses/Pydantic models for envelope and episode-metadata shapes, validation helpers.
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

## Usage

```python
# Indicative — actual API will be added as the first concrete reporter is written.
from reporter_sdk.envelope import Envelope, Artifact
from reporter_sdk.io import read_input_uri, write_output_uri
from reporter_sdk.env import reporter_inputs

inputs = reporter_inputs()  # reads COGAME_* env vars
results = read_input_uri(inputs.results_uri)

envelope = Envelope(
    version="1",
    artifacts=[
        Artifact(id="summary", content_type="text/markdown", content="# ..."),
        Artifact(id="stats",   content_type="application/json", content={"...": "..."}),
    ],
)
write_output_uri(inputs.report_output_uri, envelope.to_json())
```

The above is a sketch of the intended ergonomics, not a stable API. Treat the contract in [`../../docs/REPORTER_DESIGN.md`](../../docs/REPORTER_DESIGN.md) (especially decisions D2, D3, D4, D10) as the source of truth; the SDK is the implementation of that contract.

## Versioning

`0.0.0` until the first concrete reporter ships and validates the API shape. From there, SemVer:

- **0.x.y** — pre-1.0, breaking changes allowed at minor bumps. Coordinate via the commit that introduces the break.
- **1.0.0** — first release once at least two concrete reporters depend on a stable API surface.

Because reporters build against repo-HEAD by default, breaking changes require updating every consumer in the same commit. Treat that as the forcing function for keeping the API small and considered.

## References

- [`../../README.md`](../../README.md) — repository overview and v1 contract summary.
- [`../../docs/REPORTER_DESIGN.md`](../../docs/REPORTER_DESIGN.md) — full v1 design and decisions log (D1–D10). The SDK exists to encode this document; if the two disagree, the design doc wins and the SDK is wrong.
- [`../templates/`](../templates/) — game-agnostic template reporters built on top of this SDK.
