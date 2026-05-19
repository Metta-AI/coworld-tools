# templates

Game-agnostic template reporters — scaffolding and base implementations meant to make it easy to start a new reporter for a coworld.

> **Status: intentionally on hold.** No template code exists yet, and we are **not** writing speculative templates. `summarizer_template` will be *extracted* from [`reporters/paint_arena/paint_arena_summarizer`](../paint_arena/paint_arena_summarizer/) once that concrete reporter is implemented and its game-agnostic shape is visible. See the "Build strategy" section of the [root README](../../README.md) for the rationale.

## Purpose

This directory holds reporters that are **not tied to any specific game**. They exist to:

- Demonstrate the v1 coworld reporter contract end-to-end in runnable form, so a new game-specific reporter has a concrete pattern to follow rather than only the prose contract in [`../../docs/REPORTER_DESIGN.md`](../../docs/REPORTER_DESIGN.md).
- Serve as readable starting skeletons. Templates should be **clean, minimal, and easy to read**; their job is to lower the cost of writing reporter number 2, 3, 4, and N, not to be a framework.

Reusable primitives — envelope construction, env-supplied URI resolution, artifact helpers, contract-aligned types — do **not** live here. They live in the shared, pip-installable [`reporter_sdk`](../reporter_sdk/) package alongside this directory. Templates import from `reporter_sdk` just like every concrete reporter does; the templates' job is to show *how* you wire the SDK together for a typical reporter shape, not to re-implement the primitives.

The bar for what belongs in a template is "I am starting a reporter for a new coworld — what is the minimum shape that already works against the SDK and the contract?" Anything beyond that belongs in `reporter_sdk` (if it is reusable) or in a concrete reporter (if it is game-specific).

## Usage

Templates are consumed by game-specific reporters (`reporters/paint_arena/paint_arena_summarizer`, `reporters/among_them/among_them_summarizer`, `reporters/cogs_v_clips/cogs_v_clips_summarizer`, future additions) by **copying** a template into a new reporter directory as a starting skeleton, then filling in the game-specific logic (results parsing, summary content, stats extraction).

You do **not** import from a template. Templates are not a runtime dependency of concrete reporters — they are scaffolding. The runtime dependency every reporter (templates included) shares is [`reporter_sdk`](../reporter_sdk/), which is where envelope construction, URI I/O, and shared types live. If you find yourself wanting to import a helper from a template, that helper belongs in `reporter_sdk` instead — move it there and have both the template and the concrete reporter import it from one place.

The goal is consistency with the reporter contract: every concrete reporter ends up reading the same env-supplied URIs, producing the same envelope shape, and surfacing artifacts via the same first-class content types.

## Execution constraints

Templates here are **game-agnostic and therefore cannot be executed as-is against any specific game's results**. They have no knowledge of a particular game's results-JSON shape, replay format, or what "a meaningful summary" looks like for that game, so running one directly would at best produce a trivial envelope and at worst fail.

Concretely:

- A template may build and write a syntactically valid envelope (per the D3 envelope schema), but the artifacts inside it will be placeholders rather than real analysis.
- A template is not registered in any `coworld_manifest.json` — only concrete, game-specific reporters are declared in manifests and invoked by the runner.
- To produce meaningful artifacts, a template must be specialized with game-specific logic: parsing the game's `COGAME_RESULTS_URI` payload against the game's `results_schema`, extracting whatever the coworld author cares to surface, and shaping the envelope accordingly.

If you find yourself wanting to run a template directly against real game results, you are looking for a concrete reporter, not a template.

## References

For everything the reporter contract requires — lifecycle, inputs, outputs, failure semantics, certification — read these first:

- [`../../README.md`](../../README.md) — repository overview, layout, the v1 contract in one breath, conventions every reporter must follow.
- [`../../docs/REPORTER_DESIGN.md`](../../docs/REPORTER_DESIGN.md) — full v1 design with the D1–D10 decisions log: the per-episode trigger and purity rules (D1), the env-supplied URI input contract (D2) including `COGAME_RESULTS_URI`, `COGAME_REPLAY_URI`, `COGAME_LOG_URI`, `COGAME_EPISODE_METADATA_URI`, `COGAME_MANIFEST_URI`, `COGAME_REPORTER_ID`, and the write target `COGAME_REPORT_OUTPUT_URI`, the JSON envelope schema and first-class content types (D3), multi-reporter execution (D4), and failure handling (D8).
- [`../reporter_sdk/`](../reporter_sdk/) — the shared, pip-installable Python library implementing those contract primitives. Templates and concrete reporters both depend on it.

Templates in this directory must stay aligned with those documents. If a template drifts from the contract, fix the template — the contract is the source of truth.

## Roadmap

| Template | Role | Status |
| --- | --- | --- |
| `summarizer_template` | Standard pattern for producing a Markdown summary artifact (`text/markdown`) plus a JSON stats artifact (`application/json`) from an episode's results. The default starting point for any new `<coworld>_summarizer` reporter. | On hold — will be extracted from `paint_arena_summarizer` |

`summarizer_template` will be derived from `paint_arena/paint_arena_summarizer` after that reporter is implemented end-to-end. The "canonical two-artifact envelope (Markdown summary + JSON stats)" shape that a summarizer template should encode is exactly what `paint_arena_summarizer` ends up being, minus the PaintArena-specific bits (results parsing, summary phrasing, stats fields). Extracting in that direction guarantees the template reflects something that actually works, rather than an imagined shape we have to retrofit reporters to.

Additional templates (e.g. a highlight-reel template for binary/image artifacts) follow the same rule: extract from a working concrete reporter rather than write speculatively. Templates follow demand; they do not anticipate it.
