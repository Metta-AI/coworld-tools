# reporters

Reporter implementations for **coworlds** — containers that consume a finished episode's artifacts (results, replay, logs, episode metadata) and produce a JSON envelope of analysis artifacts (summaries, stats, visualizations) for downstream surfacing in Observatory.

> **Status:** v1 contract complete (see [`docs/REPORTER_DESIGN.md`](docs/REPORTER_DESIGN.md), decisions D1–D10). No reporter implementations exist yet — the directories below are scaffolding for upcoming work.

## What is a coworld reporter?

A **coworld** is a Softmax v2 tournament unit: one game container + one or more player containers + a `coworld_manifest.json`. A **reporter** is an optional role declared in the manifest under `reporter: [...]` that runs after an episode completes successfully.

Each reporter is a process-style container that:

1. Reads what it needs from env-supplied URIs (game results, replay, logs, episode metadata, the full manifest, and its own reporter id).
2. Writes a single JSON envelope of `{id, content_type, content}` artifacts to its output URI.
3. Exits.

The platform persists each envelope and exposes it through Observatory's API and frontend, plus through the `coworld` CLI.

Coworld background: [`docs/COWORLD_REFERENCE.md`](docs/COWORLD_REFERENCE.md). Full v1 contract and decisions log: [`docs/REPORTER_DESIGN.md`](docs/REPORTER_DESIGN.md).

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
| `<reporter_name>.py` | Reporter entrypoint. Reads env-supplied input URIs, constructs an envelope, writes to `COGAME_REPORT_OUTPUT_URI`, exits 0. |
| `build.sh` | Builds the reporter's Docker image. Each reporter is its own image; reporters do not share a build system. |
| `README.md` | Reporter-specific docs — what artifacts it produces, expected `id`s, how to test locally, any external dependencies. |

Reporters are **independent Docker images**, not a unified Python package — each leaf directory is the source root for one image. They do, however, share one **importable Python library**: [`reporters/reporter_sdk/`](reporters/reporter_sdk/), a pip-installable package providing envelope construction, env-supplied URI I/O, and contract-aligned types. Templates and concrete reporters depend on it so the v1 contract is encoded once rather than re-derived per reporter. Per-reporter `build.sh` scripts use `reporters/` as the Docker build context so both the SDK and the reporter source are reachable from a single `COPY` plane.

The repo-root `pyproject.toml` is a workspace anchor for `uv` / `.venv` setup; it intentionally has no runtime code or dependencies of its own.

## The v1 contract in one breath

From [`docs/REPORTER_DESIGN.md`](docs/REPORTER_DESIGN.md):

**Trigger.** Per-episode, after the game and player containers exit successfully and artifacts validate (D1, D6).

**Inputs** (env-supplied URIs, all set every invocation):

| Variable | Purpose |
| --- | --- |
| `COGAME_RESULTS_URI` | Game results JSON (validates against `game.results_schema`) |
| `COGAME_REPLAY_URI` | Game replay artifact (game-owned format) |
| `COGAME_LOG_URI` | Episode logs — optional, present iff the game wrote them |
| `COGAME_EPISODE_METADATA_URI` | Platform-generated episode metadata JSON |
| `COGAME_MANIFEST_URI` | Full coworld manifest JSON |
| `COGAME_REPORTER_ID` | This reporter's manifest `id` (plain string, not a URI) |
| `COGAME_REPORT_OUTPUT_URI` | **Write target** for the JSON envelope |

**Output.** A single JSON envelope written to `COGAME_REPORT_OUTPUT_URI`:

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

**First-class content types in v1:** `text/markdown`, `text/plain`, `application/json`, `image/png` (base64). `text/html` is stored but never inline-rendered. Other content types are stored and downloadable but not inline-rendered. (D3)

**Behavior contract.** Reporters are pure functions of their inputs — only side effect is writing the output URI; no external network calls beyond input/output URIs; no persistent state across runs. Determinism is strongly preferred but not required. (D1)

**Multi-reporter.** When a coworld declares multiple reporters, all run in parallel with isolated inputs/outputs/failures. Resource baseline per reporter: 2 CPU + 2 GiB memory. (D4)

**Failure handling.** Five failure codes (`start_failed`, `nonzero_exit`, `timeout`, `missing_output`, `invalid_envelope`). One retry on `timeout` only — never on other failure modes. Reporter status does not affect the runner's exit code; episode success and reporter status are orthogonal. (D8)

For everything else — certification, Observatory API surface, CLI, naming, the deferred-ideas inventory — read [`docs/REPORTER_DESIGN.md`](docs/REPORTER_DESIGN.md).

## Status of each component

| Component | Coworld | Kind | Status |
| --- | --- | --- | --- |
| `reporter_sdk` | (shared) | Library | Package skeleton in place; no implementation surface yet |
| `templates/summarizer_template` | (template) | Reporter scaffold | Scaffold only — no implementation |
| `among_them/among_them_summarizer` | Among Them | Reporter | Scaffold only — no implementation |
| `among_them/among_them_highlight_reel` | Among Them | Reporter | Scaffold only — no implementation |
| `paint_arena/paint_arena_summarizer` | PaintArena | Reporter | Scaffold only — no implementation |
| `cogs_v_clips/cogs_v_clips_summarizer` | Cogs vs Clips | Reporter | Scaffold only — no implementation |

The expected build order is `reporter_sdk` → `templates/summarizer_template` → `paint_arena/paint_arena_summarizer`. SDK first because the templates and concrete reporters import from it; `summarizer_template` second because it establishes the canonical two-artifact envelope shape (Markdown summary + JSON stats) that other summarizers will follow; PaintArena first among the concrete reporters because spec 0043 uses `paintarena-reporter` as its worked example and PaintArena is the simplest reference coworld in the metta repo.

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

Once implementations land, every reporter in this repo will share these v1 contract obligations (from [`docs/REPORTER_DESIGN.md`](docs/REPORTER_DESIGN.md)):

- Read env-supplied URIs only; no other inputs.
- Write exactly one valid envelope to `COGAME_REPORT_OUTPUT_URI` before exiting 0. Empty `artifacts: []` is a legal "ran successfully, nothing to surface" signal.
- Be a pure function of inputs. No external API calls outside what's reachable via the supplied URIs.
- Self-validate output internally if correctness matters (encouraged, not required).
- Match the per-reporter README structure — what artifacts are produced, what their `id`s and content types are, any non-obvious dependencies.

Detailed per-reporter author guidance will live in the eventual `REPORTER_RUNTIME_README.md` in the metta repo. This README points at the design; that one will point at the contract.
