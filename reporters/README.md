# reporters

Reporter implementations for **coworlds** — runnables that turn sparse episode experience (results, replays, logs, metadata, and game-authored context) into dense report artifacts for people, agents, and Observatory surfaces.

> **Status:** canonical Coworld role repo. One concrete reporter is implemented — [`reporters/paint_arena/paint_arena_summarizer/`](reporters/paint_arena/paint_arena_summarizer/) — and the current envelope-style implementation details live in [`docs/REPORTER_DESIGN.md`](docs/REPORTER_DESIGN.md). Remaining reporter directories below are scaffolding.

## What is a coworld reporter?

A **coworld** is a Softmax v2 tournament unit: one game container + one or more player containers + a `coworld_manifest.json`. A **reporter** is an optional role declared in the manifest under `reporter: [...]` that runs after episode artifacts are available.

A reporter compresses replay-level experience into a denser signal. That can be a narrative recap, commentary for surfaces like The Column, a highlight reel, an HTML or Markdown report, JSON stats, a Parquet/rich-data dump, or another artifact that helps humans and downstream agents understand what happened. Former "extractor" use cases belong here as structured-data reporters; Coworld does not have a separate canonical top-level extractor role.

Each reporter is a process-style container that:

1. Reads what it needs from env-supplied URIs (game results, replay, logs, episode metadata, and its own reporter id).
2. Writes its declared report artifact or artifact bundle to its output URI.
3. Exits.

The platform persists reporter outputs and exposes them through Observatory's API and frontend, plus through the `coworld` CLI.

Coworld background: [`docs/COWORLD_REFERENCE.md`](docs/COWORLD_REFERENCE.md). Current envelope-style implementation notes and decisions log: [`docs/REPORTER_DESIGN.md`](docs/REPORTER_DESIGN.md).

## Repository layout

```
reporters/
├── README.md                                  # this file
├── pyproject.toml                             # workspace anchor (see reporter_sdk for the shared library)
├── docs/
│   ├── COWORLD_REFERENCE.md                   # coworld navigation guide
│   └── REPORTER_DESIGN.md                     # v1 reporter design + D1–D10 decisions
└── reporters/                                 # reporter implementations + shared SDK
    ├── reporter_sdk/                          # pip-installable shared library (envelope, I/O, types)
    ├── templates/
    │   └── summarizer_template/               # starting point for new summarizer-style reporters
    ├── among_them/
    │   ├── among_them_summarizer/
    │   └── among_them_highlight_reel/
    ├── paint_arena/
    │   └── paint_arena_summarizer/
    └── cogs_v_clips/
        └── cogs_v_clips_summarizer/
```

Each leaf reporter directory follows the same shape:

| File | Purpose |
| --- | --- |
| `<reporter_name>.py` | Reporter entrypoint. Reads env-supplied input URIs, writes the reporter output, exits 0. |
| `build.sh` | Builds the reporter's Docker image. Each reporter is its own image; reporters do not share a build system. |
| `README.md` | Reporter-specific docs — what artifacts it produces, expected `id`s, how to test locally, any external dependencies. |

Reporters are **independent Docker images**, not a unified Python package — each leaf directory is the source root for one image. They do, however, share one **importable Python library**: [`reporters/reporter_sdk/`](reporters/reporter_sdk/), a pip-installable package that currently provides envelope construction, env-supplied URI I/O, and contract-aligned types for envelope-style reporters. Templates and concrete reporters depend on it so shared reporter mechanics are encoded once rather than re-derived per reporter. Per-reporter `build.sh` scripts use `reporters/` as the Docker build context so both the SDK and the reporter source are reachable from a single `COPY` plane.

The repo-root `pyproject.toml` is a workspace anchor for `uv` / `.venv` setup; it intentionally has no runtime code or dependencies of its own.

## Current envelope runtime

From [`docs/REPORTER_DESIGN.md`](docs/REPORTER_DESIGN.md):

**Trigger.** Per-episode, after the game and player containers exit successfully and artifacts validate (D1, D6).

**Inputs** (env-supplied URIs, all set every invocation):

| Variable | Purpose |
| --- | --- |
| `COGAME_RESULTS_URI` | Game results JSON (validates against `game.results_schema`) |
| `COGAME_REPLAY_URI` | Game replay artifact (game-owned format); also the source of game config for reporters that need it (D11) |
| `COGAME_LOG_URI` | Episode logs — optional, present iff the game wrote them |
| `COGAME_EPISODE_METADATA_URI` | Platform-generated episode metadata JSON |
| `COGAME_REPORTER_ID` | This reporter's manifest `id` (plain string, not a URI) |
| `COGAME_REPORT_OUTPUT_URI` | **Write target** for the JSON envelope |

**Output.** The implemented summarizer path writes a single JSON envelope to `COGAME_REPORT_OUTPUT_URI`:

```jsonc
{
  "version": "1",
  "artifacts": [
    {
      "id": "summary",
      "content_type": "text/markdown",
      "content": "# Episode Summary\n\nSlot 0 won by ..."
    },
    {
      "id": "stats",
      "content_type": "application/json",
      "content": { "scores": [42, 38], "ticks": 100, "winner_slot": 0 }
    },
    {
      "id": "heatmap",
      "content_type": "image/png",
      "encoding": "base64",
      "content": "iVBORw0KGgo..."
    }
  ]
}
```

**Envelope content types:** `text/markdown`, `text/plain`, `application/json`, `image/png` (base64). `text/html` is stored but never inline-rendered. Other content types are stored and downloadable but not inline-rendered. (D3)

**Behavior contract.** Reporters are pure functions of their inputs — only side effect is writing the output URI; no external network calls beyond input/output URIs; no persistent state across runs. Determinism is strongly preferred but not required. (D1)

**Multi-reporter.** When a coworld declares multiple reporters, all run in parallel with isolated inputs/outputs/failures. Resource baseline per reporter: 2 CPU + 2 GiB memory. (D4)

**Failure handling.** Five failure codes (`start_failed`, `nonzero_exit`, `timeout`, `missing_output`, `invalid_envelope`). One retry on `timeout` only — never on other failure modes. Reporter status does not affect the runner's exit code; episode success and reporter status are orthogonal. (D8)

For everything else about the current envelope runtime — certification, Observatory API surface, CLI, naming, and the deferred-ideas inventory — read [`docs/REPORTER_DESIGN.md`](docs/REPORTER_DESIGN.md).

## Status of each component

| Component | Coworld | Kind | Status |
| --- | --- | --- | --- |
| `paint_arena/paint_arena_summarizer` | PaintArena | Reporter | **Implemented** — first concrete reporter; tests passing; primitives inline, awaiting SDK extraction |
| `reporter_sdk` | (shared) | Library | Package skeleton in place; ready to absorb the primitives now inlined in `paint_arena_summarizer` |
| `templates/summarizer_template` | (template) | Reporter scaffold | On hold; ready to be derived from `paint_arena_summarizer` once the SDK is extracted |
| `among_them/among_them_summarizer` | Among Them | Reporter | Scaffold only — no implementation |
| `among_them/among_them_highlight_reel` | Among Them | Reporter | Scaffold only — no implementation |
| `cogs_v_clips/cogs_v_clips_summarizer` | Cogs vs Clips | Reporter | Scaffold only — no implementation |

### Build strategy: concrete reporter first, then extract

We are intentionally **not** building the SDK and `summarizer_template` first. The previous plan was to ship reusable primitives, then templates, then concrete reporters — a clean bottom-up order. We changed our minds: you cannot design good primitives without a real consumer to ground them, and shipping speculative abstractions before the first reporter exists risks baking the wrong ones in.

The new order is:

1. **Build `paint_arena/paint_arena_summarizer` end-to-end**, with envelope construction, env-supplied URI I/O, and types all inline in the reporter. PaintArena is the right starting target: spec 0043 already uses `paintarena-reporter` as its worked example, the game has the smallest results schema in the reference coworlds (`scores`, `painted_tiles`, `ticks` — see [`docs/REPORTER_DESIGN.md`](docs/REPORTER_DESIGN.md) for the broader contract), and the metta repo has a complete PaintArena example to point at. **Done.** See [`reporters/paint_arena/paint_arena_summarizer/`](reporters/paint_arena/paint_arena_summarizer/) — implementation, Dockerfile, build script, and pytest suite covering the failure-mode table in `DESIGN.md`.
2. **Extract `reporter_sdk`** from the inline primitives in `paint_arena_summarizer` once they exist. The API is whatever turns out to actually be useful, not what we guessed in advance. The extraction candidates are explicitly listed in the reporter's `DESIGN.md` ("Inline primitives" section) and labelled in `paint_arena_summarizer.py`.
3. **Extract `templates/summarizer_template`** from `paint_arena_summarizer` by stripping the PaintArena-specific bits. The "canonical summarizer shape" is whatever the concrete reporter ends up being once the SDK absorbs the reusable parts.
4. **Build the second concrete summarizer** (likely `among_them/among_them_summarizer`) against the extracted SDK, using the template as the starting skeleton. Pain points uncovered in step 4 feed back into the SDK and template.

Cost of this order: the first reporter does not get to import polished helpers — it builds them inline. That is the point. The duplication and friction that surface when writing it are exactly the signal we need to know what belongs in the SDK.

## Related metta repo locations

The reporters in this repo target coworlds defined in the broader [`metta`](../metta) monorepo. Key paths:

- `~/coding/metta/packages/coworld/` — the coworld package: manifest schema, runner (`runner/runner.py`, `runner/kubernetes_runner.py`), certifier (`certifier.py`), types (`types.py`).
- `~/coding/metta/packages/coworld/src/coworld/GAME_RUNTIME_README.md` — canonical game runtime contract (peer to the eventual `REPORTER_RUNTIME_README.md`).
- `~/coding/metta/packages/coworld/src/coworld/examples/paintarena/` — PaintArena reference coworld.
- `~/coding/metta/packages/coworld/src/coworld/examples/cogs_vs_clips/` — Cogs vs Clips coworld.
- `~/coding/metta/packages/coworld/src/coworld/policies/amongthemstarter/` — Among Them starter policy template (the `among_them` `coworld make-policy` target).
- `~/coding/metta/docs/specs/0043-user-container-management.md` — the spec that defines `runnable` (image + run + env), the shared shape behind game, player, and reporter roles.

[`docs/COWORLD_REFERENCE.md`](docs/COWORLD_REFERENCE.md) is the navigation index into all of this — point future coding agents at it first.

## Conventions for new reporters

New reporters should start from the canonical Coworld role contract:

- Read env-supplied URIs only; no other inputs.
- Write the declared output artifact or artifact bundle before exiting 0.
- Prefer pure functions of inputs. If a reporter needs richer external context, document that dependency in the reporter README and manifest.
- Self-validate output internally if correctness matters (encouraged, not required).
- Match the per-reporter README structure — what artifacts are produced, their content types or file layout, and any non-obvious dependencies.

Detailed per-reporter author guidance will live in the eventual `REPORTER_RUNTIME_README.md` in the metta repo. This README points at the design; that one will point at the contract.
