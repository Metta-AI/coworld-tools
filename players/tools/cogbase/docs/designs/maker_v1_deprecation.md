# maker_v1 Deprecation Note

## Decision

`maker_v1` is deprecated. New work on the agent-making stage of the Cogbase
meta-pipeline should go into `maker_v2`. Existing `maker_v1` code and its
generated artifacts are preserved for reference and short-term continuity, but
`maker_v1` should not receive new features and should not be treated as the
canonical path from a `guide_v1` bundle to a baseline agent.

`maker_v2` is the successor toolkit. It is currently a fresh scaffold under
`testbed/maker_v2/` and has not yet replaced `maker_v1`'s functionality. Until
`maker_v2` is usable for the slices a caller cares about, `maker_v1` may still
be invoked, but every entry point now emits a deprecation warning and points at
`maker_v2`.

## Rationale

`maker_v1` accumulated a large amount of hand-coded Python "deriver" logic that
extracts facts from `guide_v1` outputs, classifies observation surfaces, picks
action candidates, templates starter agents, and assembles VLM bootstrap and
smoke-test wiring. That accretion has two practical problems:

1. **Rigidity.** Each new game shape, observation interface, or framework
   change tends to require new Python branches inside the toolkit rather than
   a different input or a different prompt. The pipeline is harder to extend
   without touching internal modules.

2. **Brittle coupling to surface details.** Many derivers parse Markdown
   sections, regex-match action names, or special-case decoder shapes. These
   are exactly the kinds of facts the `guide_contract.json` handoff was meant
   to make irrelevant, and they fight the contract-first direction Cogbase has
   been moving.

The right next move is not another round of patches inside `maker_v1`. It is a
clean restart that treats `guide_contract.json` (and where appropriate, coding
agents themselves) as the primary derivation surface, with Python reserved for
glue, validation, packaging, and verification rather than extraction logic.

## Replacement Model

The replacement is `maker_v2`, scaffolded under `testbed/maker_v2/`. Its
intended direction is captured in
[`maker_v2_design.md`](maker_v2_design.md). The headline shifts from
`maker_v1`:

- Treat `guide_contract.json` as the primary input contract, not Markdown.
- Prefer agent-driven generation (Claude/Codex runners) for code that today is
  produced by Python templating and ad hoc derivers.
- Keep small, composable steps so callers can pick the slices they need
  (build plan, decoder, starter policy, smoke harness, packaging) without
  inheriting the full monolith.
- Resist re-introducing per-game heuristics inside the toolkit. If a game
  needs a special case, prefer encoding that case in the guide contract or in
  per-game artifacts under `output/`.

`maker_v2` is intentionally not a port. It is allowed to drop, rename, or
restructure anything from `maker_v1`. Where a concept from `maker_v1` is still
the right shape, `maker_v2` may copy or adapt it.

## Status

- `testbed/maker_v1/` remains in place as deprecated prototype toolkit code.
  All entry points emit a `DeprecationWarning` and a printed banner that
  points at `maker_v2`.
- `tests/test_maker_v1.py` continues to run against the deprecated
  implementation so we can detect regressions while `maker_v2` is being built.
- `testbed/maker_v2/` is a fresh scaffold. The CLI exists but is not yet
  implemented; it prints a "not yet implemented" message and exits non-zero.
- New games should plan around `maker_v2`. If `maker_v2` does not yet do what
  is needed, falling back to `maker_v1` is acceptable, but the gap should be
  recorded as a `maker_v2` requirement rather than a new `maker_v1` feature.

See [`maker_v1_design.md`](maker_v1_design.md) for the historical design and
[`maker_v2_design.md`](maker_v2_design.md) for the direction of the
replacement.
