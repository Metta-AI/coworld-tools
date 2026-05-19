# graders

Grader implementations for **coworlds** - containers that evaluate coworld runs, submissions, or artifacts and produce grading outputs for downstream tournament and Observatory workflows.

> **Status:** repository scaffold only. The coworld `grader` runtime contract is not defined yet; see [`docs/GRADER_DESIGN.md`](docs/GRADER_DESIGN.md) for the current design placeholder and open questions.

## What is a coworld grader?

A **coworld** is a Softmax v2 tournament unit: one game container + one or more player containers + a `coworld_manifest.json`. A **grader** is an optional role declared in the manifest under `grader: [...]`.

The manifest schema already has the role, but today the platform only validates declared grader images during certification. It does not launch graders as part of the runner. This repo is the implementation home for grader containers once the contract is finalized.

Coworld background: [`docs/COWORLD_REFERENCE.md`](docs/COWORLD_REFERENCE.md). Grader contract notes: [`docs/GRADER_DESIGN.md`](docs/GRADER_DESIGN.md).

## Repository layout

```text
graders/
|-- README.md
|-- pyproject.toml
|-- docs/
|   |-- COWORLD_REFERENCE.md
|   `-- GRADER_DESIGN.md
`-- graders/
    |-- templates/
    |   `-- grader_template/
    |-- among_them/
    |   `-- among_them_grader/
    |-- paint_arena/
    |   `-- paint_arena_grader/
    `-- cogs_v_clips/
        `-- cogs_v_clips_grader/
```

Each leaf grader directory follows the same placeholder shape:

| File | Purpose |
| --- | --- |
| `<grader_name>.py` | Grader entrypoint placeholder. Fill this in after the runtime contract is defined. |
| `build.sh` | Builds the grader's Docker image. Each grader can be its own image unless a shared image pattern emerges. |
| `README.md` | Grader-specific docs: what it grades, expected inputs/outputs, local test command, and dependencies. |

## Status of each grader

| Grader | Coworld | Status |
| --- | --- | --- |
| `templates/grader_template` | (template) | Scaffold only - no implementation |
| `among_them/among_them_grader` | Among Them | Scaffold only - no implementation |
| `paint_arena/paint_arena_grader` | PaintArena | Scaffold only - no implementation |
| `cogs_v_clips/cogs_v_clips_grader` | Cogs vs Clips | Scaffold only - no implementation |

## Related metta repo locations

- `~/coding/metta/packages/coworld/` - coworld package: manifest schema, runner, certifier, and role types.
- `~/coding/metta/packages/coworld/src/coworld/types.py` - source of truth for the `grader` manifest section.
- `~/coding/metta/packages/coworld/src/coworld/GAME_RUNTIME_README.md` - canonical game runtime contract.
- `~/coding/metta/docs/specs/0043-user-container-management.md` - shared runnable shape behind game, player, grader, reporter, commissioner, diagnoser, and optimizer roles.
- `~/coding/metta/packages/coworld/src/coworld/examples/paintarena/` - simplest reference coworld.

## Conventions for new graders

- Keep concrete grader implementations under the top-level `graders/` tree.
- Keep one leaf directory per runnable image or entrypoint.
- Keep game-specific code under that game's directory.
- Do not invent a runtime contract inside an implementation. Update `docs/GRADER_DESIGN.md` and the metta coworld contract first.
- Keep game/runtime package code in its owning repo unless the file is genuinely grader source.
