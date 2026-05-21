# reporters

Reporter implementations for **coworlds** — runnables that turn sparse episode experience (results, replays, logs, metadata, and game-authored context) into dense report artifacts for people, agents, and Observatory surfaces.

> **Status:** canonical Coworld role repo. Two concrete reporters are implemented under the D12 zip + `render.txt` contract: [`reporters/paint_arena/paint_arena_summarizer/`](reporters/paint_arena/paint_arena_summarizer/) and [`reporters/among_them/among_them_summarizer/`](reporters/among_them/among_them_summarizer/) (phases 1–5 + design correction landed; phases 6–8 — determinism tests, Dockerfile/smoke, README expansion — deferred). The current v1 contract details live in [`docs/REPORTER_DESIGN.md`](docs/REPORTER_DESIGN.md) (decisions D1–D12). Remaining reporter directories listed in the status table below are scaffolding.

## What is a coworld reporter?

A **coworld** is a Softmax v2 tournament unit: one game container + one or more player containers + a `coworld_manifest.json`. A **reporter** is an optional role declared in the manifest under `reporter: [...]` that runs after episode artifacts are available.

A reporter compresses replay-level experience into a denser signal. That can be a narrative recap, commentary for surfaces like The Column, a highlight reel, an HTML or Markdown report, JSON stats, a Parquet/rich-data dump, or another artifact that helps humans and downstream agents understand what happened. Former "extractor" use cases belong here as structured-data reporters; Coworld does not have a separate canonical top-level extractor role.

Each reporter is a process-style container that:

1. Reads what it needs from env-supplied URIs (game results, replay, logs, episode metadata, and its own reporter id).
2. Writes its declared report artifact or artifact bundle to its output URI.
3. Exits.

The platform persists reporter outputs and exposes them through Observatory's API and frontend, plus through the `coworld` CLI.

Coworld background: [`docs/COWORLD_REFERENCE.md`](docs/COWORLD_REFERENCE.md). Current v1 contract and decisions log: [`docs/REPORTER_DESIGN.md`](docs/REPORTER_DESIGN.md).

## Repository layout

```
reporters/
├── README.md                                  # this file
├── pyproject.toml                             # workspace anchor (see reporter_sdk for the shared library)
├── docs/
│   ├── COWORLD_REFERENCE.md                   # coworld navigation guide
│   └── REPORTER_DESIGN.md                     # v1 reporter design + D1–D12 decisions
└── reporters/                                 # reporter implementations + shared SDK
    ├── reporter_sdk/                          # pip-installable shared library (zip writer, I/O, event-log schema, types)
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

Reporters are **independent Docker images**, not a unified Python package — each leaf directory is the source root for one image. They do, however, share one **importable Python library**: [`reporters/reporter_sdk/`](reporters/reporter_sdk/), a pip-installable package that will provide the zip-output writer, env-supplied URI I/O, the shared `(ts, player, key, value)` event-log schema, and contract-aligned types per D12. The SDK skeleton exists today but exports no real surface yet — those primitives are still inlined in `paint_arena_summarizer.py` and `among_them_summarizer.py`, where they'll be lifted from once the two reporters' shared shape is stable (see the "Build strategy" section). Per-reporter `build.sh` scripts use `reporters/` as the Docker build context so both the SDK and the reporter source are reachable from a single `COPY` plane.

The repo-root `pyproject.toml` is a workspace anchor for `uv` / `.venv` setup; it intentionally has no runtime code or dependencies of its own.

## v1 reporter runtime

From [`docs/REPORTER_DESIGN.md`](docs/REPORTER_DESIGN.md) (decisions D1–D12; D3's JSON envelope was superseded by D12's single-zip output on 2026-05-20):

**Trigger.** Per-episode, after the game and player containers exit successfully and artifacts validate (D1, D6).

**Inputs** (env-supplied URIs, all set every invocation):

| Variable | Purpose |
| --- | --- |
| `COGAME_RESULTS_URI` | Game results JSON (validates against `game.results_schema`) |
| `COGAME_REPLAY_URI` | Game replay artifact (game-owned format); also the source of game config for reporters that need it (D11) |
| `COGAME_LOG_URI` | Episode logs — optional, present iff the game wrote them |
| `COGAME_EPISODE_METADATA_URI` | Platform-generated episode metadata JSON |
| `COGAME_REPORTER_ID` | This reporter's manifest `id` (plain string, not a URI) |
| `COGAME_REPORT_OUTPUT_URI` | **Write target** for the output zip file |

**Output (D12).** Each reporter writes a single zip file to `COGAME_REPORT_OUTPUT_URI`. Content types are inferred from file extensions — no in-band metadata. An optional top-level `render.txt` lists, one zip-relative path per line, the files Observatory renders inline (in order). Renderable extensions in v1: `.md`, `.txt`, `.html` / `.htm`. Other extensions (`.png`, `.json`, `.parquet`, `.svg`, …) MUST NOT appear in `render.txt`; they live in the zip as downloads, referenced from rendered files via relative paths. Missing/empty `render.txt` = nothing inline. Empty zip = "ran successfully, nothing to surface" (valid output).

Example (paint_arena's actual output):

```
report.zip
├── summary.html        # rendered inline (listed in render.txt)
├── stats.json          # download-only; referenced from HTML footer
├── proximity.parquet   # download-only; per-tick event log
└── render.txt          # single line: "summary.html\n"
```

**Determinism (D12).** Reporters that want byte-identical reruns over identical inputs MUST pin zip-entry mtimes (e.g. `ZipInfo.date_time = (1980, 1, 1, 0, 0, 0)`); Python's default `os.stat` mtimes would otherwise break the guarantee. Determinism is strongly preferred but not required (D1) — LLM-based reporters are permitted as long as purity holds.

**Behavior contract (D1).** Reporters are pure functions of their inputs — only side effect is writing the output URI; no external network calls beyond input/output URIs; no persistent state across runs.

**Multi-reporter (D4).** When a coworld declares multiple reporters, all run in parallel with isolated inputs/outputs/failures. Resource baseline per reporter: 2 CPU + 2 GiB memory.

**Failure handling (D8, D12).** Five failure codes (`start_failed`, `nonzero_exit`, `timeout`, `missing_output`, `invalid_output`). `invalid_output` covers unreadable zips, `render.txt` listing a missing file, and `render.txt` listing a file whose extension isn't in the renderable allowlist. One retry on `timeout` only — never on other failure modes. Reporter status does not affect the runner's exit code; episode success and reporter status are orthogonal.

**Zip safety is the consumer's responsibility (D12).** Path traversal on extract, zip bombs, symlink entries, excessive file count, and large single-entry streaming are enforced by Observatory and the local runner — not by the reporter contract.

For everything else — certification, Observatory API surface, CLI, naming, and the deferred-ideas inventory — read [`docs/REPORTER_DESIGN.md`](docs/REPORTER_DESIGN.md).

## Status of each component

| Component | Coworld | Kind | Status |
| --- | --- | --- | --- |
| `paint_arena/paint_arena_summarizer` | PaintArena | Reporter | **Implemented** — first concrete reporter; tests passing; D12 zip + `render.txt` contract; primitives inline, awaiting SDK extraction |
| `reporter_sdk` | (shared) | Library | Package skeleton in place; ready to absorb the primitives now inlined in `paint_arena_summarizer` and `among_them_summarizer` |
| `templates/summarizer_template` | (template) | Reporter scaffold | On hold; ready to be derived once the SDK is extracted from the two concrete reporters |
| `among_them/among_them_summarizer` | Among Them | Reporter | **Implemented (phases 1–5 + design correction)** — second concrete reporter; D12 zip + `render.txt` contract; full binary `.bitreplay` parser, input-stream analytics, HTML scoreboard with palette + sparkline; tests passing. Phases 6 (determinism tests) / 7 (Dockerfile + smoke) / 8 (README expansion) deferred. See [`reporters/among_them/among_them_summarizer/DESIGN.md`](reporters/among_them/among_them_summarizer/DESIGN.md). |
| `among_them/among_them_highlight_reel` | Among Them | Reporter | Scaffold only — no implementation |
| `cogs_v_clips/cogs_v_clips_summarizer` | Cogs vs Clips | Reporter | Scaffold only — no implementation |

### Build strategy: concrete reporter first, then extract

We are intentionally **not** building the SDK and `summarizer_template` first. The previous plan was to ship reusable primitives, then templates, then concrete reporters — a clean bottom-up order. We changed our minds: you cannot design good primitives without a real consumer to ground them, and shipping speculative abstractions before the first reporter exists risks baking the wrong ones in.

The new order is:

1. **Build `paint_arena/paint_arena_summarizer` end-to-end**, with the deterministic zip writer, env-supplied URI I/O, the shared `(ts, player, key, value)` event-log schema, and contract-aligned types all inline in the reporter. PaintArena is the right starting target: spec 0043 already uses `paintarena-reporter` as its worked example, the game has the smallest results schema in the reference coworlds (`scores`, `painted_tiles`, `ticks` — see [`docs/REPORTER_DESIGN.md`](docs/REPORTER_DESIGN.md) for the broader contract), and the metta repo has a complete PaintArena example to point at. **Done.** See [`reporters/paint_arena/paint_arena_summarizer/`](reporters/paint_arena/paint_arena_summarizer/) — implementation (originally on the D3 envelope shape; migrated to the D12 zip + `render.txt` shape in 2026-05-20), Dockerfile, build script, and pytest suite covering the failure-mode table in `DESIGN.md`.
2. **Extract `reporter_sdk`** from the inline primitives in `paint_arena_summarizer` once they exist. The API is whatever turns out to actually be useful, not what we guessed in advance. The extraction candidates are explicitly listed in the reporter's `DESIGN.md` ("Inline primitives" section) and labelled in `paint_arena_summarizer.py`.
3. **Extract `templates/summarizer_template`** from `paint_arena_summarizer` by stripping the PaintArena-specific bits. The "canonical summarizer shape" is whatever the concrete reporter ends up being once the SDK absorbs the reusable parts.
4. **Build the second concrete summarizer.** `among_them/among_them_summarizer` is now in progress (phases 1–5 landed; phases 6–8 deferred). We **inverted the original step ordering** here: rather than extract the SDK first and write the second reporter against it, we wrote the second reporter inline as well — same primitive duplication as PaintArena — so that the SDK extraction has *two* real consumers driving its API rather than one. Pain points uncovered while writing reporter #2 feed back into the SDK and template in the still-pending step 2/3 extraction work.

Cost of this order: the first two reporters do not get to import polished helpers — they build them inline, with literal copy-paste of the inline primitives (`ReporterInputs`, `read_uri`/`write_uri`, `write_deterministic_zip`, `EVENT_LOG_SCHEMA`, `write_events_parquet`) between them. That is the point. The duplication and friction that surface when writing them are exactly the signal we need to know what belongs in the SDK.

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
- Write a single zip file to `COGAME_REPORT_OUTPUT_URI` before exiting 0; an empty zip is a valid output (D12).
- If the zip should render anything inline, include a top-level `render.txt` listing the renderable files (one zip-relative path per line) — extensions must be in the D12 allowlist (`.md`, `.txt`, `.html` / `.htm`).
- Pin zip-entry mtimes to a fixed value (e.g. `(1980, 1, 1, 0, 0, 0)`) if byte-identical reruns matter; without this, deterministic reporters still drift through `os.stat`-stamped mtimes.
- Prefer pure functions of inputs. If a reporter needs richer external context, document that dependency in the reporter README and manifest.
- Match the per-reporter README structure — what artifacts are produced, the zip layout, which files `render.txt` lists, and any non-obvious dependencies. [`reporters/paint_arena/paint_arena_summarizer/README.md`](reporters/paint_arena/paint_arena_summarizer/README.md) is the reference shape.

Detailed per-reporter author guidance will live in the eventual `REPORTER_RUNTIME_README.md` in the metta repo. This README points at the design; that one will point at the contract.
