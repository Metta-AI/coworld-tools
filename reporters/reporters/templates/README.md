# templates

Game-agnostic template reporters — scaffolding and base implementations meant to make it easy to start a new reporter for a Coworld.

> **Status (2026-05-23):** `summarizer_template` has been extracted from the post-SDK `paint_arena_summarizer` and is implemented. The template imports from [`reporter_sdk`](../reporter_sdk/) and produces a valid-shape (but stub-content) output zip end-to-end; see [`summarizer_template/README.md`](summarizer_template/README.md) for usage. Additional templates (e.g. a highlight-reel template) follow the same rule: extract from a working concrete reporter rather than write speculatively.

## Purpose

This directory holds reporters that are **not tied to any specific game**. They exist to:

- Demonstrate the canonical Coworld reporter contract end-to-end in runnable form, so a new game-specific reporter has a concrete pattern to follow rather than only the prose contract in [`../../docs/REPORTER_DESIGN.md`](../../docs/REPORTER_DESIGN.md) and the canonical role doc it points at.
- Serve as readable starting skeletons. Templates should be **clean, minimal, and easy to read**; their job is to lower the cost of writing reporter number 3, 4, and N, not to be a framework.

Reusable primitives — the deterministic zip writer, the bundle reader, the in-zip `manifest.json` writer, env-supplied URI resolution, the shared `(ts, player, key, value)` Parquet event-log schema, contract-aligned types — do **not** live here. They will live in the shared, pip-installable [`reporter_sdk`](../reporter_sdk/) package alongside this directory once the extraction pass completes. Templates will import from `reporter_sdk` just like every concrete reporter does; the templates' job is to show *how* you wire the SDK together for a typical reporter shape, not to re-implement the primitives.

The bar for what belongs in a template is "I am starting a reporter for a new Coworld — what is the minimum shape that already works against the SDK and the contract?" Anything beyond that belongs in `reporter_sdk` (if it is reusable) or in a concrete reporter (if it is game-specific).

## Usage

Templates are consumed by game-specific reporters by **copying** a template into a new reporter directory as a starting skeleton, then filling in the game-specific logic (results parsing, replay decoding if needed, HTML rendering, stats extraction, Parquet event rows).

You do **not** import from a template. Templates are not a runtime dependency of concrete reporters — they are scaffolding. The runtime dependency every reporter (templates included) shares is [`reporter_sdk`](../reporter_sdk/), which is where the deterministic zip writer, bundle reader, URI I/O, the shared event-log schema, and shared types live. If you find yourself wanting to import a helper from a template, that helper belongs in `reporter_sdk` instead — move it there and have both the template and the concrete reporter import it from one place.

The goal is consistency with the canonical reporter contract: every concrete reporter ends up reading the bundle from `COGAME_EPISODE_BUNDLE_URI`, writing a single output zip to `COGAME_REPORT_URI` with an in-zip `manifest.json` flagging `render` and `event_log`, and emitting events into the same `(ts, player, key, value)` Parquet schema.

## Execution constraints

Templates here are **game-agnostic and therefore cannot be executed as-is against any specific game's results**. They have no knowledge of a particular game's results-JSON shape, replay format, or what "a meaningful summary" looks like for that game, so running one directly would at best produce a trivial zip and at worst fail.

Concretely:

- A template may build and write a syntactically valid output zip (a placeholder `manifest.json`, or a stub `summary.html`), but the artifacts inside it will be placeholders rather than real analysis.
- A template is not registered in any `coworld_manifest.json` and has no entry in this repo's `CATALOG.yaml` — only concrete, game-specific reporters are declared in manifests and shipped.
- To produce meaningful artifacts, a template must be specialized with game-specific logic: opening the bundle at `COGAME_EPISODE_BUNDLE_URI`, parsing the bundle's `results.json` against the game's `results_schema`, optionally decoding `replay.json` (format is game-owned), extracting whatever the Coworld author cares to surface, and shaping the output zip accordingly.

If you find yourself wanting to run a template directly against real game results, you are looking for a concrete reporter, not a template.

## References

For everything the reporter contract requires — lifecycle, inputs, outputs, the in-zip `manifest.json` shape, the event-log schema — read these first:

- [`../../README.md`](../../README.md) — repository overview, layout, canonical contract summary, conventions every reporter must follow.
- [`../../docs/REPORTER_DESIGN.md`](../../docs/REPORTER_DESIGN.md) — local restatement of the canonical contract plus repo-local notes (implementation status, migration debt, repo conventions).
- [`packages/coworld/src/coworld/docs/roles/reporter.md`](../../../metta/packages/coworld/src/coworld/docs/roles/reporter.md) in metta — **canonical reporter role contract**.
- [`packages/coworld/src/coworld/EPISODE_BUNDLE_README.md`](../../../metta/packages/coworld/src/coworld/EPISODE_BUNDLE_README.md) in metta — bundle the reporter reads.
- [`../reporter_sdk/`](../reporter_sdk/) — the shared, pip-installable Python library that will implement the contract's primitives. Templates and concrete reporters both depend on it once extraction is done.

Templates in this directory must stay aligned with the canonical metta role doc. If a template drifts from the contract, fix the template — the metta doc is the source of truth.

## Roadmap

| Template | Role | Status |
| --- | --- | --- |
| `summarizer_template` | Standard pattern for producing an HTML/Markdown summary inside a single output zip with an in-zip `manifest.json` flagging the rendered artifact as `render`. The default starting point for any new `<coworld>_summarizer` reporter. Game-specific reporters typically extend the template to also emit a JSON stats blob and a `(ts, player, key, value)` Parquet event log flagged as `event_log`. | Implemented — extracted from the post-SDK `paint_arena_summarizer`. Runs end-to-end via `summarizer.py`, produces a valid-shape but stub-content output zip. See [`summarizer_template/README.md`](summarizer_template/README.md). |

`summarizer_template` was derived from the post-extraction `paint_arena_summarizer` by stripping the PaintArena-specific bits and replacing every primitive with an import from `reporter_sdk`. The "canonical summarizer shape" (rendered artifact + optional `stats.json` auxiliary + optional `events.parquet` event log + `manifest.json` flagging `render` and `event_log`, deterministic zip mtimes, shared event-log schema) is what both PaintArena and Among Them produce; the template ships only the rendered-artifact half of that shape because anything more would be game-specific. Extracting from a working concrete reporter rather than an imagined shape guarantees the template reflects something that actually works.

Additional templates (e.g. a highlight-reel template for binary/image artifacts) follow the same rule: extract from a working concrete reporter rather than write speculatively. Templates follow demand; they do not anticipate it.
