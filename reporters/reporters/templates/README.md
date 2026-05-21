# templates

Game-agnostic template reporters — scaffolding and base implementations meant to make it easy to start a new reporter for a coworld.

> **Status: still on hold.** [`reporters/paint_arena/paint_arena_summarizer`](../paint_arena/paint_arena_summarizer/) and [`reporters/among_them/among_them_summarizer`](../among_them/among_them_summarizer/) are now implemented end-to-end, so the game-agnostic shape `summarizer_template` will encode is visible from two real consumers. The next step is `reporter_sdk` extraction; this template gets extracted from the two concrete reporters *after* the SDK absorbs the reusable primitives (so the template imports from the SDK rather than inlining). See the "Build strategy" section of the [root README](../../README.md) for the rationale.

## Purpose

This directory holds reporters that are **not tied to any specific game**. They exist to:

- Demonstrate the v1 coworld reporter contract end-to-end in runnable form, so a new game-specific reporter has a concrete pattern to follow rather than only the prose contract in [`../../docs/REPORTER_DESIGN.md`](../../docs/REPORTER_DESIGN.md).
- Serve as readable starting skeletons. Templates should be **clean, minimal, and easy to read**; their job is to lower the cost of writing reporter number 3, 4, and N, not to be a framework.

Reusable primitives — the D12 deterministic zip writer, `render.txt` assembly, env-supplied URI resolution, the shared `(ts, player, key, value)` parquet event-log schema, contract-aligned types — do **not** live here. They will live in the shared, pip-installable [`reporter_sdk`](../reporter_sdk/) package alongside this directory once the extraction pass completes. Templates will import from `reporter_sdk` just like every concrete reporter does; the templates' job is to show *how* you wire the SDK together for a typical reporter shape, not to re-implement the primitives.

The bar for what belongs in a template is "I am starting a reporter for a new coworld — what is the minimum shape that already works against the SDK and the contract?" Anything beyond that belongs in `reporter_sdk` (if it is reusable) or in a concrete reporter (if it is game-specific).

## Usage

Templates are consumed by game-specific reporters by **copying** a template into a new reporter directory as a starting skeleton, then filling in the game-specific logic (results parsing, replay decoding if needed, HTML rendering, stats extraction, parquet event rows).

You do **not** import from a template. Templates are not a runtime dependency of concrete reporters — they are scaffolding. The runtime dependency every reporter (templates included) shares is [`reporter_sdk`](../reporter_sdk/), which is where the D12 zip writer, URI I/O, the shared event-log schema, and shared types live. If you find yourself wanting to import a helper from a template, that helper belongs in `reporter_sdk` instead — move it there and have both the template and the concrete reporter import it from one place.

The goal is consistency with the reporter contract: every concrete reporter ends up reading the same env-supplied URIs, writing a single zip to `COGAME_REPORT_OUTPUT_URI` with the same `render.txt` discipline, and emitting events into the same `(ts, player, key, value)` parquet schema.

## Execution constraints

Templates here are **game-agnostic and therefore cannot be executed as-is against any specific game's results**. They have no knowledge of a particular game's results-JSON shape, replay format, or what "a meaningful summary" looks like for that game, so running one directly would at best produce a trivial zip and at worst fail.

Concretely:

- A template may build and write a syntactically valid D12 zip (an empty `render.txt`, or a placeholder `summary.html`), but the artifacts inside it will be placeholders rather than real analysis.
- A template is not registered in any `coworld_manifest.json` — only concrete, game-specific reporters are declared in manifests and invoked by the runner.
- To produce meaningful artifacts, a template must be specialized with game-specific logic: parsing the game's `COGAME_RESULTS_URI` payload against the game's `results_schema`, optionally decoding the replay at `COGAME_REPLAY_URI` (the format is game-owned per D11), extracting whatever the coworld author cares to surface, and shaping the zip accordingly.

If you find yourself wanting to run a template directly against real game results, you are looking for a concrete reporter, not a template.

## References

For everything the reporter contract requires — lifecycle, inputs, outputs, failure semantics, certification — read these first:

- [`../../README.md`](../../README.md) — repository overview, layout, the v1 contract in one breath, conventions every reporter must follow.
- [`../../docs/REPORTER_DESIGN.md`](../../docs/REPORTER_DESIGN.md) — full v1 design with the D1–D12 decisions log: the per-episode trigger and purity rules (D1), the env-supplied URI input contract (D2, narrowed by D11) — `COGAME_RESULTS_URI`, `COGAME_REPLAY_URI`, `COGAME_LOG_URI`, `COGAME_EPISODE_METADATA_URI`, `COGAME_REPORTER_ID`, and the write target `COGAME_REPORT_OUTPUT_URI` — the single-zip output contract with `render.txt`-driven inline rendering (D12), multi-reporter execution (D4), and failure handling (D8 + D12).
- [`../reporter_sdk/`](../reporter_sdk/) — the shared, pip-installable Python library that will implement the contract's primitives. Templates and concrete reporters will both depend on it once extraction is done.

Templates in this directory must stay aligned with those documents. If a template drifts from the contract, fix the template — the contract is the source of truth.

## Roadmap

| Template | Role | Status |
| --- | --- | --- |
| `summarizer_template` | Standard pattern for producing an HTML summary + a JSON stats blob + a `(ts, player, key, value)` parquet event log inside a single D12 zip with `render.txt` listing the HTML. The default starting point for any new `<coworld>_summarizer` reporter. | On hold — both `paint_arena_summarizer` and `among_them_summarizer` implemented; awaiting `reporter_sdk` extraction before template extraction |

`summarizer_template` will be derived from the two concrete reporters once the SDK absorbs the reusable primitives. The "canonical summarizer shape" (HTML rendered inline + stats.json download + events.parquet download + render.txt manifest, deterministic zip mtimes, shared event-log schema) is exactly what both PaintArena and Among Them ended up being, minus the game-specific bits (results parsing, replay decoding, summary phrasing, stats fields). Extracting in that direction guarantees the template reflects something that actually works, rather than an imagined shape we have to retrofit reporters to.

Additional templates (e.g. a highlight-reel template for binary/image artifacts) follow the same rule: extract from a working concrete reporter rather than write speculatively. Templates follow demand; they do not anticipate it.
