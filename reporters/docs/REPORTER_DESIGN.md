# Reporter Design

> **Status:** the canonical Coworld reporter contract is owned upstream in `Metta-AI/metta` at
> [`packages/coworld/src/coworld/docs/roles/reporter.md`](../../metta/packages/coworld/src/coworld/docs/roles/reporter.md). This document is the reporters-repo restatement of that contract plus repo-local notes (status of the implementations here, repo conventions, and known migration debt against the canonical shape).
>
> **Canonical contract version:** the `contract defined, runtime pending` shape described in metta's `docs/roles/reporter.md` and `EPISODE_BUNDLE_README.md` (last revised in metta on 2026-05-22). When this doc and the metta role doc disagree, **metta is authoritative.**
>
> **Implementation status (this repo, 2026-05-23):** the two implemented reporters — [`reporters/paint_arena/paint_arena_summarizer/`](../reporters/paint_arena/paint_arena_summarizer/) and [`reporters/among_them/among_them_summarizer/`](../reporters/among_them/among_them_summarizer/) — were originally built against an internal pre-canonical draft (per-artifact input env vars; top-level `render.txt` in the output zip). The current implementations have **not yet been migrated** to the canonical `COGAME_EPISODE_BUNDLE_URI` / `COGAME_REPORT_URI` shape with an internal `manifest.json` flagging `render` and `event_log`. Migration is tracked as deferred work (see [§5](#5-migration-state) below); the metta-side reference reporters under `packages/coworld/src/coworld/examples/paintarena/reporter/` are in the same pre-migration state and will be migrated together.

---

## 1. What a reporter is

A **reporter** is a Coworld supporting runnable that turns one episode's artifacts into rendered highlights (a Markdown or HTML render) and a structured event log (a Parquet with `ts, player, key, value` columns). Reporters compress sparse episode experience — replays, results, logs — into dense signals for humans, Observatory surfaces, and downstream supporting runnables.

Reporters are **on-demand**. The episode runner does **not** invoke them automatically. A reporter run is triggered by a CLI command (planned: `coworld run-reporter` — exact shape still being settled), a hosted button, or an automatic Column pipeline. The invoker assembles the episode bundle, sets the env vars, and waits for the container to exit.

A reporter runnable is a short-lived, process-style container. It does not expose HTTP routes or websockets; it reads its inputs from an env-var URI, writes its output to an env-var URI, and exits.

For the upstream role doc and the episode-bundle contract, see:

- [`packages/coworld/src/coworld/docs/roles/reporter.md`](../../metta/packages/coworld/src/coworld/docs/roles/reporter.md) — canonical role contract.
- [`packages/coworld/src/coworld/EPISODE_BUNDLE_README.md`](../../metta/packages/coworld/src/coworld/EPISODE_BUNDLE_README.md) — bundle contents, the inner `manifest.json` schema, access-control rules, the three surfaces (`coworld bundle` CLI, `coworld.bundle` library, `GET /v2/episodes/{ereq}/bundle` backend API).
- [`packages/coworld/src/coworld/docs/roles/OVERVIEW.md`](../../metta/packages/coworld/src/coworld/docs/roles/OVERVIEW.md) — full artifact flow across the seven Coworld roles.
- [`packages/coworld/src/coworld/MANIFEST_README.md`](../../metta/packages/coworld/src/coworld/MANIFEST_README.md) — manifest field reference; the runnable shape used by `manifest.reporter[]`.

---

## 2. The v1 contract (canonical, paraphrased)

### Manifest declaration

`manifest.reporter[]`, with `type: "reporter"` on every entry. The array must contain at least one runnable; Coworlds without a custom reporter may reference `softmax/default-reporter:latest`. Each entry follows the standard declared-runnable shape — `id`, `name`, `description`, `image`, optional `run`, optional `env`, optional `source_url` — defined in [`MANIFEST_README.md` § Runnable Shape](../../metta/packages/coworld/src/coworld/MANIFEST_README.md#runnable-shape).

### Input

One env var:

| Var | Read/write | Purpose |
| --- | --- | --- |
| `COGAME_EPISODE_BUNDLE_URI` | R | URI (`file://` locally, `https://` hosted) of a `.zip` file containing the episode's artifacts. The reporter reads the zip, inspects its `manifest.json` to discover what's inside, and processes the files it cares about. |

The bundle always contains `results.json` and `replay.json`; it may also contain `config.json`, game logs, per-player logs (subject to access control), and `error_info.json` if the episode failed. The bundle's own `manifest.json` schema is documented in [`EPISODE_BUNDLE_README.md` § `manifest.json`](../../metta/packages/coworld/src/coworld/EPISODE_BUNDLE_README.md#manifestjson) — consumers should read from its `files` map rather than hard-coding paths.

The bundling layer is the seam between in-flight and post-episode roles. Bundles are assembled on demand by the consumer (the CLI command, the platform action) from the runner's per-URI artifacts; the reporter only sees the assembled zip.

### Output

One env var:

| Var | Read/write | Purpose |
| --- | --- | --- |
| `COGAME_REPORT_URI` | W | URI (`file://` locally, `https://` or `s3://` hosted) where the reporter writes a single `.zip` containing all report files. |

The output zip may include any files the reporter needs (Markdown, HTML, Parquet, images, JSON, etc.). At the root of the zip, the reporter should include a `manifest.json` describing the contents:

```json
{
  "reporter_id": "paint-arena-summarizer",
  "render": "summary.md",
  "event_log": "stats.parquet"
}
```

| Field | Required? | Purpose |
| --- | --- | --- |
| `reporter_id` | recommended | The id this reporter self-reports for itself. Conventionally matches the runnable's `id` in `manifest.reporter[]`, but the platform does not enforce a match. Useful for caches and downstream consumers tracking provenance. |
| `render` | optional | Path inside the zip to a single `.md` or `.html` file that UIs should render. **At most one per output.** |
| `event_log` | optional | Path inside the zip to a single Parquet file containing structured tick-aligned events. **At most one per output.** See [§3](#3-event-log-schema) below. |

All other files in the zip are free-form; reporters can include any auxiliary assets their output needs.

### Execution

Reporters are **on-demand**. They are **not** run automatically by the episode runner — an episode finishes and produces artifacts whether or not any reporter ever runs against them.

The invoker is responsible for:

1. Choosing which reporter to run (one of the runnables in `manifest.reporter[]`).
2. Assembling the input bundle via the bundling layer.
3. Setting `COGAME_EPISODE_BUNDLE_URI` and `COGAME_REPORT_URI` on the reporter container.
4. Waiting for the container to exit and consuming the output zip.

### Determinism

Reporters are **not required** to produce byte-identical output across runs over identical inputs, but should do so when feasible. Deterministic reporters enable caching and reproducible testing. The paintarena summarizer is an existing example of a deterministic reporter; LLM-based or otherwise non-deterministic reporters are also valid.

---

## 3. Event log schema

When a reporter writes an `event_log` Parquet file, it must use the following column schema:

| Column | Type | Purpose |
| --- | --- | --- |
| `ts` | int64 | Episode tick at which the event occurred. |
| `player` | int64 | Player slot (0..N-1) for player-scoped events, or `-1` for global events. |
| `key` | string | Event name or stat key. |
| `value` | string | Event value. JSON-encoded if the value is structured. |

The event log is the primary structured-data surface that downstream diagnosers and optimizers consume. It is the mechanism by which a reporter ties events and stat changes of interest to the specific ticks at which they occurred — so a diagnoser can ground "your policy did X at tick Y" in concrete evidence, and an optimizer can correlate ticks with reward signals and policy decisions.

---

## 4. Why this is on-demand (not a runner-triggered hook)

The on-demand model is a deliberate property of the canonical contract:

- **Decoupling.** An episode finishes and produces artifacts whether or not any reporter ever runs. The runner's job ends at "write the per-URI artifacts"; reporters' jobs begin when a consumer asks for a report.
- **Bundling is consumption-time.** The runner does not assemble episode bundles; bundles are constructed on demand by the consumer (CLI, library, backend) from the per-URI artifacts. Reporters consume bundles, so they too are consumption-time.
- **Cost control.** Running every declared reporter on every episode is wasted work when most reporter outputs are read only when someone surfaces them.
- **Composability.** On-demand keeps space open for chained reporters, grader-driven highlight selection, and "rerun this reporter against the archived bundle" without re-running the episode.

If a future "run every declared reporter automatically on episode completion" pattern is needed, it layers on top of this contract as a platform-side policy, not a change to the reporter contract itself.

---

## 5. Migration state

The two reporters in this repo (and the two upstream reference reporters under `packages/coworld/src/coworld/examples/paintarena/reporter/`) were written against an earlier internal draft that diverged from the canonical contract on three load-bearing points:

| Concern | Pre-canonical (current code) | Canonical (metta `docs/roles/reporter.md`) |
| --- | --- | --- |
| **Input** | Multiple env vars: `COGAME_RESULTS_URI`, `COGAME_REPLAY_URI`, `COGAME_LOG_URI`, `COGAME_EPISODE_METADATA_URI`, `COGAME_REPORTER_ID` | Single env var: `COGAME_EPISODE_BUNDLE_URI` (a zip with an inner `manifest.json`) |
| **Output env var** | `COGAME_REPORT_OUTPUT_URI` | `COGAME_REPORT_URI` |
| **Output zip render manifest** | A top-level `render.txt` text file listing renderable paths in order | A top-level `manifest.json` with `reporter_id`, `render` (one `.md`/`.html`), `event_log` (one `.parquet`) |
| **Trigger** | Per-episode, auto-fired from the episode runner | On-demand, fired by a CLI / button / pipeline |

The migration plan: bring the reporters' input layer over to the `coworld.bundle` library; replace `render.txt` with `manifest.json` (with `render` and `event_log` paths); rename the output env var; drop the runner integration assumptions. The actual artifact files inside the output zip (`summary.html`, `stats.json`, `events.parquet`, etc.) carry over essentially unchanged — the change is in how they're *flagged*, not in what they *are*.

Implementations in this repo will be migrated alongside metta's reference reporters; the two should land together so the contract has a stable working example end-to-end.

Until migration completes, the per-reporter READMEs describe the canonical contract shape; the running code follows the pre-canonical shape. This is the same gap that exists in metta between its docs and the example reporters.

---

## 6. Repo conventions (this repo only)

Anchored on the canonical contract, with no contract extensions:

- **One zip per reporter run.** Even for empty or "nothing to surface" outputs, write a valid zip.
- **Use `manifest.json` to flag `render` and `event_log`.** No other in-band metadata files.
- **Use the shared event-log schema.** `(ts: int64, player: int64, key: string, value: string)` per the canonical contract. JSON-encode structured `value`s.
- **Prefer determinism when feasible.** Pin Parquet writer version, pin zip-entry mtimes (recommended sentinel: `(1980, 1, 1, 0, 0, 0)`). Determinism is preferred but not required.
- **Match the per-reporter README structure.** What artifacts are produced, which files `manifest.json` flags, any non-obvious dependencies. [`reporters/paint_arena/paint_arena_summarizer/README.md`](../reporters/paint_arena/paint_arena_summarizer/README.md) is the reference shape.

For repo layout (the `CATALOG.yaml`, the `users/<handle>/` subtree, the `tools/` directory), see [`docs/specs/0045-coworld-role-repos.md`](../../metta/docs/specs/0045-coworld-role-repos.md) in metta and the top-level [`README.md`](../README.md) in this repo.

---

## 7. Out of scope for v1 (canonical)

Items the canonical metta role doc explicitly defers:

- **Default renderer marker.** A future manifest-level flag that marks one reporter as the Coworld's "default renderer" Observatory runs against every episode. Not implemented; the manifest-level marker is not yet defined.
- **Chained reports.** A reporter consuming another reporter's output as part of its input. The current bundle contract does not surface prior reporter outputs; chaining will be added when a real chained reporter ships.
- **Additional structured-data formats beyond Parquet.** The `event_log` slot accepts one Parquet path; SVG, CSV, JSON-as-tree, etc. live in the zip as auxiliary files referenced from the `render` target.
- **Multi-bundle / cross-episode reporters.** A reporter that consumes multiple bundles to produce a single output. Single-bundle is the v1 shape.

For the full deferred list, see metta's `docs/roles/reporter.md` § "Future directions".

---

## 8. References

Canonical (metta):

- [`packages/coworld/src/coworld/docs/roles/reporter.md`](../../metta/packages/coworld/src/coworld/docs/roles/reporter.md) — role contract.
- [`packages/coworld/src/coworld/docs/roles/OVERVIEW.md`](../../metta/packages/coworld/src/coworld/docs/roles/OVERVIEW.md) — full artifact flow.
- [`packages/coworld/src/coworld/EPISODE_BUNDLE_README.md`](../../metta/packages/coworld/src/coworld/EPISODE_BUNDLE_README.md) — bundle contract.
- [`packages/coworld/src/coworld/MANIFEST_README.md`](../../metta/packages/coworld/src/coworld/MANIFEST_README.md) — manifest field reference.
- [`packages/coworld/src/coworld/COWORLD_README.md`](../../metta/packages/coworld/src/coworld/COWORLD_README.md) — top-level Coworld guide; Role Status framework.
- [`docs/specs/0045-coworld-role-repos.md`](../../metta/docs/specs/0045-coworld-role-repos.md) — per-role-repo structure, `CATALOG.yaml`, `users/<handle>/` subtree.

Local (this repo):

- [`docs/COWORLD_REFERENCE.md`](./COWORLD_REFERENCE.md) — navigation guide into metta.
- [`README.md`](../README.md) — repo layout, status of each reporter, conventions.
- Per-reporter READMEs under [`reporters/<game>/<reporter>/`](../reporters/).
