# maker_v2

Status: fresh scaffold. The CLI exists but no generation is implemented yet.
Running `generate_agent.py` prints a "not yet implemented" message and exits
non-zero.

`maker_v2` is the canonical successor to the deprecated
[`maker_v1`](../maker_v1/) toolkit. It occupies the same position in the
Cogbase meta-pipeline (consume a `guide_v1` bundle, produce a runnable
baseline agent) but is intended to be:

- **Contract-first.** `guide_contract.json` is the primary input. Markdown
  parsing, if needed at all, is a narrow fallback rather than a parallel
  code path.
- **Agent-driven where it matters.** Code that today is produced by hand-coded
  Python derivers in `maker_v1` (action candidates, starter policy, decoder
  scaffolding, prose extraction) is intended to come from coding-agent
  runners with focused prompts and small validation steps. Python is reserved
  for glue, schema enforcement, packaging, and tests.
- **Composable.** Each generation step (build plan, decoder, starter policy,
  VLM bootstrap, smoke harness, packaging) should be invokable on its own,
  not bolted into a single monolithic command.

For the rationale behind retiring `maker_v1`, see
[`docs/designs/maker_v1_deprecation.md`](../../docs/designs/maker_v1_deprecation.md).
For the direction of `maker_v2`, see
[`docs/designs/maker_v2_design.md`](../../docs/designs/maker_v2_design.md).

## What works today

Nothing yet. The scaffold provides:

- `generate_agent.py` -- entry point. Parses arguments and prints a clear
  not-yet-implemented message.
- `maker_v2/` -- Python package skeleton (`__init__.py`, `cli.py`).

## Intended usage (once implemented)

```bash
# From this directory:
# cd testbed/maker_v2

python generate_agent.py ../guide_v1/output/<game> \
  --output-dir ./output/<game>
```

The exact flag surface will be designed as slices land. The first slice is
expected to be a contract-driven build plan; see the design doc for the
sketched plan.

## While maker_v2 is being built

If you need agent generation today, the deprecated `maker_v1` is still
runnable. Its entry points emit a deprecation warning and direct users here.
Any gap that forces a fallback to `maker_v1` should be filed as a `maker_v2`
requirement rather than a new `maker_v1` feature.

## Artifact Boundary

Reusable generator code belongs directly under this directory, for example
`maker_v2/` and `generate_agent.py`.

Generated game-specific outputs must go under `output/<game>/`. Those outputs
may include code, tests, prompts, fixtures, and final agent packages, but
they are artifacts produced by `maker_v2`, not part of the toolkit itself.
