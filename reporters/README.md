# reporters

Reporter implementations for **Coworlds** — on-demand runnables that turn one episode's bundle (`results.json`, `replay.json`, optional logs, optional config and error info) into a single zip containing a rendered highlight (`.md` or `.html`), a structured event log (Parquet), and optional machine traces.

> **Status:** shared reporter source inside `Metta-AI/coworld-tools`. The old `Metta-AI/reporters` repo is archived.
> Keep reusable reporters and reporter SDK work here. Keep a reporter beside a game when it is game-specific and should
> be rebuilt with that `Metta-AI/coworld-<slug>` repo.

> **Canonical contract:** [`packages/coworld/src/coworld/docs/roles/reporter.md`](../metta/packages/coworld/src/coworld/docs/roles/reporter.md) in metta. Local restatement: [`docs/REPORTER_DESIGN.md`](docs/REPORTER_DESIGN.md). Navigation guide into the rest of metta: [`docs/COWORLD_REFERENCE.md`](docs/COWORLD_REFERENCE.md).
>
> **Implementation status (2026-05-30):** concrete reporters under [`reporters/paint_arena/paint_arena_summarizer/`](reporters/paint_arena/paint_arena_summarizer/), [`reporters/among_them/among_them_summarizer/`](reporters/among_them/among_them_summarizer/), and [`reporters/cogs_vs_clips/cogs_vs_clips_summarizer/`](reporters/cogs_vs_clips/cogs_vs_clips_summarizer/) are functionally complete and run on the canonical `COGAME_EPISODE_BUNDLE_URI` / `COGAME_REPORT_URI` contract with an in-zip `manifest.json` flagging `render`, `event_log`, and optionally `trace`. The matching metta-side reference reporters under `packages/coworld/src/coworld/examples/paintarena/reporter/` are still on the pre-canonical shape and will be migrated in a paired upstream PR.

## What is a Coworld reporter?

A **Coworld** is a Softmax v2 tournament unit: one game container, one or more player containers, five supporting-runnable arrays (commissioner, reporter, grader, diagnoser, optimizer) — each required by the manifest schema, with Softmax-published default images available for any role a Coworld does not implement itself — and a `coworld_manifest.json` describing them all. A **reporter** is one of the four post-episode supporting roles. It reads an **episode bundle** — a single zip assembled on demand from the episode's per-URI artifacts — and writes a single output zip carrying a rendered highlight and an event log.

Reporters compress sparse episode experience into dense highlight signals: narrative recap, news-caster commentary for surfaces like The Column, a highlight reel, an HTML or Markdown summary, structured statistics, or any other artifact that helps humans and downstream agents understand what happened.

Each reporter is a process-style container that:

1. Reads the episode bundle from `COGAME_EPISODE_BUNDLE_URI`, inspecting the bundle's internal `manifest.json` to discover which files are present.
2. Writes its single output zip to `COGAME_REPORT_URI`, including a top-level `manifest.json` flagging the `render` target (one `.md` or `.html`), the `event_log` (one Parquet with `(ts, player, key, value)` columns), and an optional `trace` (`.jsonl` or `.json`) for machine-readable timelines.
3. Exits.

The platform persists reporter outputs and exposes them through Observatory's API and frontend, plus through the `coworld` CLI. **Reporters are on-demand** — they are not auto-invoked by the episode runner. A reporter run is triggered by a CLI command (planned: `coworld run-reporter`), a hosted button, or an automatic Column pipeline.

Coworld background: [`docs/COWORLD_REFERENCE.md`](docs/COWORLD_REFERENCE.md). Canonical reporter contract: [`docs/REPORTER_DESIGN.md`](docs/REPORTER_DESIGN.md) and the metta role doc it points at.

## Repository layout

This repo follows the per-role-repo layout defined in [`docs/specs/0045-coworld-role-repos.md`](../metta/docs/specs/0045-coworld-role-repos.md):

```text
reporters/
├── README.md                                  # this file
├── pyproject.toml                             # workspace anchor (see reporter_sdk for the shared library)
├── CATALOG.yaml                               # canonical implementations index (see "CATALOG.yaml" below)
├── docs/
│   ├── COWORLD_REFERENCE.md                   # navigation guide into metta
│   └── REPORTER_DESIGN.md                     # canonical contract restatement + repo notes
├── reporters/                                 # canonical reporter implementations + shared SDK
│   ├── reporter_sdk/                          # pip-installable shared library (zip writer, bundle reader, event-log schema, types)
│   ├── templates/
│   │   └── summarizer_template/               # starting point for new summarizer-style reporters
│   ├── default/                               # softmax/default-reporter — placeholder for Coworlds without a game-specific reporter
│   ├── among_them/
│   │   ├── among_them_summarizer/
│   │   └── among_them_highlight_reel/
│   ├── paint_arena/
│   │   └── paint_arena_summarizer/
│   └── cogs_vs_clips/
│       └── cogs_vs_clips_summarizer/
├── users/                                     # contributor experiment subtree (spec 0045)
│   └── <handle>/<project>/                    # contributor reporters live here pre-promotion
└── tools/                                     # reporter-specific tools (spec 0045); includes validate_catalog.py
```

`CATALOG.yaml`, `users/`, and `tools/` are required (or required-when-used) elements of the per-role-repo layout per spec 0045. The `users/<handle>/<project>/` subtree is the recommended starting point for contributor experiments — researchers and external collaborators can develop reporter implementations here without merging into the canonical `reporters/` tree, and promote successful work into the canonical tree via a separate contribution.

Each canonical leaf reporter directory follows the same shape:

| File | Purpose |
| --- | --- |
| `<reporter_name>.py` | Reporter entrypoint. Reads the episode bundle from `COGAME_EPISODE_BUNDLE_URI`, writes the output zip to `COGAME_REPORT_URI`, exits 0. |
| `build.sh` | Builds the reporter's Docker image. Each reporter is its own image; reporters do not share a build system. |
| `Dockerfile` | The image referenced by the catalog entry's `image` field. |
| `README.md` | Reporter-specific docs — what artifacts the output zip contains, which file `manifest.json` flags as `render`, which Parquet is the `event_log`, how to test locally, any external dependencies. |
| `requirements.txt` *or* `pyproject.toml` | Build/runtime dependencies. |
| `tests/` *(recommended)* | Implementation-specific tests. |

Reporters are **independent Docker images**, not a unified Python package — each leaf directory is the source root for one image. They do, however, share one **importable Python library**: [`reporters/reporter_sdk/`](reporters/reporter_sdk/), a pip-installable package that provides bundle reading, the deterministic zip writer, the shared `(ts, player, key, value)` event-log schema, and contract-aligned types. Per-reporter `build.sh` scripts use `reporters/` as the Docker build context so both the SDK and the reporter source are reachable from a single `COPY` plane.

The repo-root `pyproject.toml` is a workspace anchor for `uv` / `.venv` setup; it intentionally has no runtime code or dependencies of its own.

## CATALOG.yaml

[`CATALOG.yaml`](CATALOG.yaml) at the repo root is the canonical list of implementations in this repo. The schema is defined in [spec 0045 § `CATALOG.yaml` schema](../metta/docs/specs/0045-coworld-role-repos.md). Required fields per entry: `name`, `image`, `source`, `source_url`, `status`, `target`, `owner`, `description`. Optional: `family`, `since`. The `status` enum is `active`, `starter`, `experimental`, `archived` (per spec 0045). This repo uses `experimental` for placeholder/scaffold entries — see the header comment in [`CATALOG.yaml`](CATALOG.yaml) for the convention.

**Authoritative:** a reporter exists in this repo if and only if it has an entry in `CATALOG.yaml`. Source on disk without a catalog entry is incomplete; a catalog entry without source is broken.

### Validation

The catalog is validated on every reporter PR and every relevant push to `main` by
[`../.github/workflows/validate-reporter-catalog.yml`](../.github/workflows/validate-reporter-catalog.yml), which runs
the validator at [`tools/validate_catalog.py`](tools/validate_catalog.py). To check locally from this directory:

```bash
python tools/validate_catalog.py             # validate CATALOG.yaml at repo root
python tools/validate_catalog.py --self-test # exercise the validator's catch paths
pytest tools/tests/                          # full unit-test suite for the validator
```

The validator confirms every required field is present and non-empty, every `status` is in the spec-0045 enum, every entry's `source` path exists on disk, and no two entries share a `name`. It does **not** check that `image` tags actually resolve to a published image — that's a separate concern owned by each reporter's image-publishing CI.

### Adding a new entry

When you ship a new reporter:

1. Add an entry to `CATALOG.yaml` with all required fields. Use `target: "*"` for game-agnostic reporters; otherwise the world id (e.g. `paint_arena`, `among_them`, `cogs_vs_clips`).
2. Confirm the `source` path matches the reporter's directory on disk and the `source_url` points to its tree on `main`.
3. Run `python tools/validate_catalog.py` locally — CI will re-run it on the PR.

Example shape (illustrative; see [`CATALOG.yaml`](CATALOG.yaml) for the live entries):

```yaml
entries:
  - name: paint-arena-summarizer
    image: ghcr.io/metta-ai/reporters-paint-arena-summarizer:latest
    source: reporters/paint_arena/paint_arena_summarizer
    source_url: https://github.com/Metta-AI/coworld-tools/tree/main/reporters/reporters/paint_arena/paint_arena_summarizer
    status: active
    target: paint_arena
    owner: jboggs
    description: Per-episode HTML summary + proximity event log for PaintArena.
```

## v1 reporter runtime (canonical)

From [`packages/coworld/src/coworld/docs/roles/reporter.md`](../metta/packages/coworld/src/coworld/docs/roles/reporter.md) in metta, restated locally in [`docs/REPORTER_DESIGN.md`](docs/REPORTER_DESIGN.md):

**Trigger.** On-demand. The episode runner does not invoke reporters automatically. A reporter run is triggered by a CLI command (planned: `coworld run-reporter`), a hosted button, or an automatic Column pipeline.

**Input** (one env var):

| Variable | Purpose |
| --- | --- |
| `COGAME_EPISODE_BUNDLE_URI` | URI (`file://` local, `https://` hosted) of a `.zip` containing the episode's artifacts. The reporter reads the zip and inspects its internal `manifest.json` to discover what's inside. |

An episode bundle always contains `results.json` and `replay.json`; it may also contain `config.json`, game logs, per-player logs (subject to access control), and `error_info.json` if the episode failed. See [`EPISODE_BUNDLE_README.md`](../metta/packages/coworld/src/coworld/EPISODE_BUNDLE_README.md) in metta for the full bundle contract.

**Output** (one env var):

| Variable | Purpose |
| --- | --- |
| `COGAME_REPORT_URI` | URI (`file://` local, `https://` or `s3://` hosted) where the reporter writes a single `.zip` containing all report files. |

The output zip may include any files the reporter needs (Markdown, HTML, Parquet, images, JSON, etc.). At the root of the zip, the reporter should include a `manifest.json` describing the contents:

```json
{
  "reporter_id": "paint-arena-summarizer",
  "render": "summary.html",
  "event_log": "proximity.parquet",
  "trace": "trace.jsonl"
}
```

| Field | Required? | Purpose |
| --- | --- | --- |
| `reporter_id` | recommended | The id this reporter self-reports for itself. Conventionally matches the runnable's `id` in `manifest.reporter[]`. |
| `render` | optional | Path inside the zip to a single `.md` or `.html` file that UIs should render. **At most one per output.** |
| `event_log` | optional | Path inside the zip to a single Parquet file containing structured tick-aligned events. **At most one per output.** Schema: `(ts: int64, player: int64, key: string, value: string)`. |
| `trace` | optional | Path inside the zip to a single `.jsonl` or `.json` machine-readable trace artifact. **At most one per output.** |

All other files in the zip are free-form auxiliary assets — referenced from the render target via relative paths, or downloaded directly via the file-direct API surface when one ships.

**Event log schema.** When a reporter writes an `event_log` Parquet, it must use this column schema:

| Column | Type | Purpose |
| --- | --- | --- |
| `ts` | int64 | Episode tick at which the event occurred. |
| `player` | int64 | Player slot (0..N-1) for player-scoped events, `-1` for global events. |
| `key` | string | Event name or stat key. |
| `value` | string | Event value. JSON-encoded if the value is structured. |

The event log is the primary structured-data surface that downstream diagnosers and optimizers consume.

**Determinism.** Reporters are not required to produce byte-identical output across runs over identical inputs, but should do so when feasible. Deterministic reporters enable caching and reproducible testing. To get byte-identical zips, pin zip-entry mtimes to a fixed value (recommended sentinel: `(1980, 1, 1, 0, 0, 0)`) and pin Parquet writer versions. LLM-based or otherwise non-deterministic reporters are also valid as long as they remain pure functions of their inputs.

For everything else — manifest declaration shape, the bundle's internal `manifest.json` schema, access-control rules, the planned `coworld run-reporter` CLI surface — read [`docs/REPORTER_DESIGN.md`](docs/REPORTER_DESIGN.md) and the metta docs it points at.

## Status of each component

| Component | Coworld | Kind | Status |
| --- | --- | --- | --- |
| `paint_arena/paint_arena_summarizer` | PaintArena | Reporter | **Implemented (canonical, SDK-consuming)** — first concrete reporter; tests passing. Runs on the canonical contract: single `COGAME_EPISODE_BUNDLE_URI` input, single `COGAME_REPORT_URI` output, in-zip `manifest.json` flagging `render` and `event_log`. Imports its shared primitives from [`reporter_sdk`](reporters/reporter_sdk/). |
| `reporter_sdk` | (shared) | Library | **Implemented** — `BundleReader`, `OutputManifest` + `build_report_zip`, deterministic zip writer, shared event-log schema and writer, trace manifest validation, env-var URI helpers, retrying `read_uri`/`write_uri`. Imported by concrete reporters. |
| `templates/summarizer_template` | (template) | Reporter scaffold | **Implemented** — extracted from the post-SDK `paint_arena_summarizer`. Runs end-to-end against a synthetic bundle and emits a valid-shape (stub-content) output zip via [`reporter_sdk`](reporters/reporter_sdk/); scaffolding for new `<coworld>_summarizer` reporters, not registered in any Coworld manifest. |
| `among_them/among_them_summarizer` | Among Them | Reporter | **Implemented (canonical, SDK-consuming, all eight design phases landed)** — second concrete reporter; full binary `.bitreplay` parser, input-stream analytics, HTML scoreboard, containerized smoke, determinism + zip-contract assertions, paint-arena-shaped README; tests passing. Imports its shared primitives from [`reporter_sdk`](reporters/reporter_sdk/). See [`reporters/among_them/among_them_summarizer/DESIGN.md`](reporters/among_them/among_them_summarizer/DESIGN.md). |
| `default/default_reporter` | (any) | Reporter | **Implemented (canonical, SDK-consuming)** — the Softmax-published placeholder reporter. Renders a per-slot score summary from `results.json::scores`; no event log. Published to `ghcr.io/metta-ai/reporters-default:latest` via [`../.github/workflows/build-default-reporter-image.yml`](../.github/workflows/build-default-reporter-image.yml); referenced by Coworld manifests that have not shipped a game-specific reporter (satisfies the schema's `min_length=1` on `manifest.reporter[]`). See [`reporters/default/README.md`](reporters/default/README.md). |
| `among_them/among_them_highlight_reel` | Among Them | Reporter | Scaffold only — no implementation. |
| `cogs_vs_clips/cogs_vs_clips_summarizer` | Cogs vs Clips | Reporter | **Implemented (canonical, SDK-consuming)** — decodes compact MettaScope replays into per-agent `trace.jsonl`, `events.parquet`, `behavior_summary.json`, and a Markdown summary. Published to `ghcr.io/metta-ai/reporters-cogs-vs-clips-summarizer:latest` via [`../.github/workflows/build-cogs-vs-clips-summarizer-image.yml`](../.github/workflows/build-cogs-vs-clips-summarizer-image.yml). |

### Build strategy: concrete reporter first, then extract

We intentionally **did not** build the SDK and `summarizer_template` first. The earlier plan was to ship reusable primitives, then templates, then concrete reporters — a clean bottom-up order. We changed our minds: you cannot design good primitives without a real consumer to ground them, and shipping speculative abstractions before the first reporter exists risks baking the wrong ones in.

The order is:

1. **Build `paint_arena/paint_arena_summarizer` end-to-end**, with the deterministic zip writer, env-supplied URI I/O, the shared event-log schema, and contract-aligned types all inline in the reporter. **Done.** See [`reporters/paint_arena/paint_arena_summarizer/`](reporters/paint_arena/paint_arena_summarizer/).
2. **Build `among_them/among_them_summarizer` end-to-end**, also inline rather than against an extracted SDK, so that the SDK extraction has *two* real consumers driving its API. **Done — all eight design phases landed.** See [`reporters/among_them/among_them_summarizer/`](reporters/among_them/among_them_summarizer/).
3. **Migrate both reporters to the canonical contract.** The two were originally built against an internal draft that diverged from the now-canonical metta contract on input env vars, output env var, and the in-zip render manifest. The migration changed how outputs are *flagged*, not what the actual artifact files contain. **Done.** Both reporters now read a single `COGAME_EPISODE_BUNDLE_URI`, write to `COGAME_REPORT_URI`, and emit a top-level `manifest.json` carrying `reporter_id` / `render` / `event_log`.
4. **Extract `reporter_sdk`** from the (post-migration) inline primitives in the two concrete reporters. The SDK API is whatever turns out to actually be useful, not what we guessed in advance. **Done.** `BundleReader`, the deterministic zip writer, the shared event-log schema and writer, env-var URI helpers, retrying `read_uri`/`write_uri`, and the validating `OutputManifest` writer all live in [`reporters/reporter_sdk/`](reporters/reporter_sdk/); both concrete reporters import them.
5. **Extract `templates/summarizer_template`** from `paint_arena_summarizer` by stripping the PaintArena-specific bits, importing from the extracted SDK. **Done.** The template runs end-to-end against a synthetic bundle, emits a valid-shape (stub-content) output zip via [`reporter_sdk`](reporters/reporter_sdk/), and is the scaffolding to copy when starting a new `<coworld>_summarizer` reporter. See [`reporters/templates/summarizer_template/`](reporters/templates/summarizer_template/).

Cost of this order: the first two reporters do not get to import polished helpers — they build them inline, with literal copy-paste between them. That is the point. The duplication and friction that surface when writing them are exactly the signal we need to know what belongs in the SDK.

## Related metta repo locations

The reporters in this repo target Coworlds defined in the broader [`metta`](../metta) monorepo. Key paths:

- `~/coding/metta/packages/coworld/` — the Coworld package: manifest schema, runner (`runner/runner.py`, `runner/kubernetes_runner.py`), certifier (`certifier.py`), types (`types.py`), bundling layer (`bundle.py`).
- `~/coding/metta/packages/coworld/src/coworld/docs/roles/reporter.md` — **canonical reporter role contract**.
- `~/coding/metta/packages/coworld/src/coworld/docs/roles/OVERVIEW.md` — full artifact flow.
- `~/coding/metta/packages/coworld/src/coworld/EPISODE_BUNDLE_README.md` — episode-bundle contract.
- `~/coding/metta/packages/coworld/src/coworld/MANIFEST_README.md` — manifest field reference.
- `~/coding/metta/packages/coworld/src/coworld/GAME_RUNTIME_README.md` — game-container runtime contract.
- `~/coding/metta/packages/coworld/src/coworld/examples/paintarena/` — PaintArena reference Coworld (including reference reporters under `reporter/`; both still pre-canonical, pending an upstream migration paired with this repo's).
- `~/coding/metta/packages/coworld/src/coworld/policies/amongthemstarter/` — Among Them starter policy template.
- `~/coding/metta/docs/specs/0045-coworld-role-repos.md` — per-role-repo structure spec; `CATALOG.yaml`, `users/`, `tools/`.

[`docs/COWORLD_REFERENCE.md`](docs/COWORLD_REFERENCE.md) is the navigation index into all of this — point future coding agents at it first.

## Conventions for new reporters

New reporters should start from the canonical Coworld role contract:

- Read **only** `COGAME_EPISODE_BUNDLE_URI`; inspect the bundle's internal `manifest.json` to find the files you need.
- Write a single zip to `COGAME_REPORT_URI` before exiting 0; an empty zip is a valid output ("ran successfully, nothing to surface").
- Include a top-level `manifest.json` flagging your `render` target (one `.md` or `.html`), your `event_log` (one Parquet), and your `trace` (one `.jsonl` or `.json`) if you produce them. `reporter_id` should match the runnable's manifest `id`.
- Use the canonical event-log schema: `(ts: int64, player: int64, key: string, value: string)`; JSON-encode structured `value`s.
- Pin zip-entry mtimes to a fixed value (e.g. `(1980, 1, 1, 0, 0, 0)`) if byte-identical reruns matter; without this, otherwise-deterministic reporters drift through `os.stat`-stamped mtimes.
- Prefer pure functions of the bundle. If a reporter needs richer external context, document the dependency in the reporter README and manifest entry.
- Match the per-reporter README structure — what artifacts the zip contains, which files `manifest.json` flags, any non-obvious dependencies. [`reporters/paint_arena/paint_arena_summarizer/README.md`](reporters/paint_arena/paint_arena_summarizer/README.md) is the reference shape.
- Add a `CATALOG.yaml` entry for the reporter when it ships — without one, tooling cannot find it.
- **Add a root `../.github/workflows/build-<name>-image.yml` workflow that publishes the image to GHCR.** Every finished (non-scaffold) reporter in this repo must have a sibling root workflow that pushes to `ghcr.io/metta-ai/reporters-<name>:latest` on push to `main`. Use `../.github/workflows/build-default-reporter-image.yml` (or `build-paint-arena-summarizer-image.yml`) as the template — same structure, just swap the image name, the path filter, and the Dockerfile path. Without this workflow, the `image` field in the reporter's `CATALOG.yaml` entry is a forward-looking placeholder pointing at a tag that does not exist in the registry.

For end-to-end author guidance, follow [`docs/REPORTER_DESIGN.md`](docs/REPORTER_DESIGN.md) and the metta role doc it points at.
