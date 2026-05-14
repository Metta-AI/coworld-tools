# maker_v2 Design

## Status

Fresh scaffold. `testbed/maker_v2/` contains a CLI stub and an empty
`maker_v2` package. No generation behavior is implemented yet. This document
captures the direction; specific slices will be designed and implemented as
the toolkit grows.

`maker_v2` supersedes the deprecated `maker_v1`. See
[`maker_v1_deprecation.md`](maker_v1_deprecation.md) for why `maker_v1` is
being retired, and [`maker_v1_design.md`](maker_v1_design.md) for the
historical design that informs (but does not constrain) `maker_v2`.

## Goals

`maker_v2` should take a `guide_v1` bundle and produce a runnable, eventually
submit-ready baseline agent, but it should reach that outcome without the
weight of `maker_v1`. Specifically:

- **Contract-first.** `guide_contract.json` is the primary input. Markdown
  parsing, if needed, is a narrow fallback rather than a parallel code path.
- **Less Python derivation, more agent-driven generation.** Where `maker_v1`
  hand-codes extraction or templating, `maker_v2` should prefer a coding-agent
  runner with a focused prompt and a small validation step. Python is for
  glue, schema enforcement, packaging, and tests rather than for prose
  parsing or per-game heuristics.
- **Composable slices.** Each generation step (build plan, decoder, starter
  policy, VLM bootstrap, smoke harness, packaging) should be invokable on its
  own. A caller that only needs a starter policy should not have to run the
  rest of the pipeline.
- **Stable artifact boundary.** Game-specific outputs continue to live under
  `output/<game>/`. Toolkit code does not learn game-specific facts at import
  time.
- **Boring tests.** Validation should focus on the contract between
  `maker_v2` and its inputs/outputs (guide contract in, manifest + artifacts
  out), not on the internal shape of derivers.

## Non-Goals

- Not a feature-for-feature port of `maker_v1`. Concepts may be dropped or
  reshaped.
- Not a replacement for `guide_v1`. Game understanding stays in the guide
  bundle.
- Not a rejection of all Python code generation. Where deterministic
  templating is the right answer (Dockerfiles, manifests, glue), Python is
  fine. The target is to stop using Python as a Markdown/guide parser.
- Not committed to a specific runner choice or prompt structure yet. Those
  decisions belong in the first implementation slice.

## Open Questions

These are intentionally not decided in this document:

- Which steps should be runner-driven and which should remain deterministic
  Python? Likely candidates for runner generation: starter policy code,
  decoder code, per-game adapter boilerplate. Likely candidates for
  deterministic code: manifest emission, Dockerfile assembly, smoke test
  harness.
- How should `maker_v2` validate runner output before writing it to the
  artifact bundle? At minimum, structural schema checks; possibly also a
  cheap smoke import / lint pass.
- What is the smallest first slice that delivers value over `maker_v1`?
  Candidate: a contract-driven build plan plus a runner-generated starter
  policy that targets `agent_policies.frameworks.coborg`, with manifest and
  Dockerfile reused or simplified from the deterministic pieces of
  `maker_v1`.
- Does `maker_v2` keep the VLM visual bootstrap loop, hand it off to a
  separate tool, or defer it until a real game needs it?

## Pipeline Position

`maker_v2` occupies the same position in the meta-pipeline as `maker_v1`:

```text
game source
  -> guide_v1
     -> guide bundle (guide_contract.json + Markdown)
  -> maker_v2
     -> agent build plan
     -> generated agent code and tests
     -> coworld-compatible player image
```

The repository rule is unchanged: toolkit code lives under `testbed/maker_v2/`
and generated game artifacts live under `testbed/maker_v2/output/<game>/`.

## Implementation Plan (Sketch)

This is intentionally light; real slices will be designed as they are picked
up.

1. **Scaffold.** Create `testbed/maker_v2/` with a CLI stub and a `maker_v2`
   Python package. CLI prints "not yet implemented" until slices land.
2. **First slice: contract-driven build plan.** Read
   `guide_contract.json`, emit a `maker_v2_manifest.json` and a build-plan
   document, with no Python prose parsing. Treat missing contract fields as
   loud errors rather than silently falling back to Markdown.
3. **Second slice: runner-generated starter policy.** Drive a coding-agent
   runner from the contract and the guide bundle to produce a starter policy
   targeting `agent_policies.frameworks.coborg`, with a small validation
   pass.
4. **Later slices.** Decoder generation, VLM bootstrap reconsideration,
   smoke-test harness, and Coworld packaging, in whatever order the work
   demands. Each slice should have a short design note appended to this
   document or split into its own file.

Each slice should explicitly call out what it replaces from `maker_v1` and
what (if anything) it leaves to the deprecated path.
