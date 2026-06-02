# diagnosers

Diagnoser implementations for **coworlds** - policy-facing runnables and prompts that evaluate a target policy and produce actionable advice or assay results.

> **Status:** canonical Coworld role repo. The Among Them starter diagnoser is implemented in [`diagnosers/among_them/among_them_diagnoser/`](diagnosers/among_them/among_them_diagnoser/). The role is defined at the manifest level, but hosted runner support is still pending.

## What is a coworld diagnoser?

A **coworld** is a Softmax v2 tournament unit: one game container + one or more player containers + a `coworld_manifest.json`. A **diagnoser** is an optional role declared in the manifest under `diagnoser: [...]`.

A diagnoser differs from a reporter by taking a target policy as part of its subject. Reporters explain episode experience; diagnosers ask "what does this policy do well or poorly?" They may consume the Coworld manifest, game docs, a target policy, replay/results artifacts, reporter outputs, structured stats dumps, and local assay runs. Their output should be useful advice or skill-test results, for example "this policy handles X with Y reliability" across a battery of X/Y checks.

The platform does not yet launch diagnosers automatically as part of hosted episode execution. This repo is the implementation home for diagnoser containers, markdown prompts, templates, and shared tooling as that surface becomes concrete.

Coworld background: [`docs/COWORLD_REFERENCE.md`](docs/COWORLD_REFERENCE.md). Diagnoser contract notes: [`docs/DIAGNOSER_DESIGN.md`](docs/DIAGNOSER_DESIGN.md).

## Repository layout

```text
diagnosers/
|-- README.md
|-- pyproject.toml
|-- docs/
|   |-- COWORLD_REFERENCE.md
|   `-- DIAGNOSER_DESIGN.md
`-- diagnosers/
    |-- templates/
    |   `-- diagnoser_template/
    |-- among_them/
    |   `-- among_them_diagnoser/
    |-- crewrift/
    |   `-- crewrift_diagnoser/
    |-- paint_arena/
    |   `-- paint_arena_diagnoser/
    `-- cogs_v_clips/
        `-- cogs_v_clips_diagnoser/
```

Each leaf diagnoser directory follows the same placeholder shape:

| File | Purpose |
| --- | --- |
| `<diagnoser_name>.py` | Diagnoser entrypoint placeholder. Evaluate a target policy and write advice or assay results. |
| `build.sh` | Builds the diagnoser's Docker image. Each diagnoser can be its own image unless a shared image pattern emerges. |
| `README.md` | Diagnoser-specific docs: what it inspects, expected inputs/outputs, local test command, and dependencies. |

## Status of each diagnoser

| Diagnoser | Coworld | Status |
| --- | --- | --- |
| `templates/diagnoser_template` | (template) | Scaffold only - no implementation |
| `among_them/among_them_diagnoser` | Among Them | Starter implementation - emits Markdown policy-assay advice from a target policy and optional episode artifacts |
| `crewrift/crewrift_diagnoser` | Crewrift | Starter implementation - emits Markdown policy-assay advice from a target policy and optional episode artifacts |
| `paint_arena/paint_arena_diagnoser` | PaintArena | Scaffold only - no implementation |
| `cogs_v_clips/cogs_v_clips_diagnoser` | Cogs vs Clips | Scaffold only - no implementation |

## Related metta repo locations

- `~/coding/metta/packages/coworld/` - coworld package: manifest schema, runner, certifier, and role types.
- `~/coding/metta/packages/coworld/src/coworld/types.py` - source of truth for the `diagnoser` manifest section.
- `~/coding/metta/packages/coworld/src/coworld/GAME_RUNTIME_README.md` - canonical game runtime contract.
- `~/coding/metta/docs/specs/0043-user-container-management.md` - shared runnable shape behind game, player, reporter, commissioner, diagnoser, and optimizer roles.
- `~/coding/metta/packages/coworld/src/coworld/examples/paintarena/` - simplest reference coworld.

## Conventions for new diagnosers

- Keep concrete diagnoser implementations under the top-level `diagnosers/` tree.
- Keep one leaf directory per runnable image or entrypoint.
- Keep game-specific code under that game's directory.
- Keep diagnosers policy-facing. Episode-only summaries, stats dumps, HTML reports, and highlight reels belong in `Metta-AI/reporters`.
- Do not invent a conflicting runtime contract inside an implementation. Update `docs/DIAGNOSER_DESIGN.md` and the metta coworld contract first.
- Keep game/runtime package code in its owning repo unless the file is genuinely diagnoser source.
