# diagnosers

Diagnoser implementations for **coworlds** - containers that inspect coworld behavior, artifacts, logs, failures, or policies and produce diagnostic outputs for developers and tournament operators.

> **Status:** repository scaffold only. The coworld `diagnoser` runtime contract is not defined yet; see [`docs/DIAGNOSER_DESIGN.md`](docs/DIAGNOSER_DESIGN.md) for the current design placeholder and open questions.

## What is a coworld diagnoser?

A **coworld** is a Softmax v2 tournament unit: one game container + one or more player containers + a `coworld_manifest.json`. A **diagnoser** is an optional role declared in the manifest under `diagnoser: [...]`.

The manifest schema already has the role, but today the platform only validates declared diagnoser images during certification. It does not launch diagnosers as part of the runner. This repo is the implementation home for diagnoser containers once the contract is finalized.

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
    |-- paint_arena/
    |   `-- paint_arena_diagnoser/
    `-- cogs_v_clips/
        `-- cogs_v_clips_diagnoser/
```

Each leaf diagnoser directory follows the same placeholder shape:

| File | Purpose |
| --- | --- |
| `<diagnoser_name>.py` | Diagnoser entrypoint placeholder. Fill this in after the runtime contract is defined. |
| `build.sh` | Builds the diagnoser's Docker image. Each diagnoser can be its own image unless a shared image pattern emerges. |
| `README.md` | Diagnoser-specific docs: what it inspects, expected inputs/outputs, local test command, and dependencies. |

## Status of each diagnoser

| Diagnoser | Coworld | Status |
| --- | --- | --- |
| `templates/diagnoser_template` | (template) | Scaffold only - no implementation |
| `among_them/among_them_diagnoser` | Among Them | Scaffold only - no implementation |
| `paint_arena/paint_arena_diagnoser` | PaintArena | Scaffold only - no implementation |
| `cogs_v_clips/cogs_v_clips_diagnoser` | Cogs vs Clips | Scaffold only - no implementation |

## Related metta repo locations

- `~/coding/metta/packages/coworld/` - coworld package: manifest schema, runner, certifier, and role types.
- `~/coding/metta/packages/coworld/src/coworld/types.py` - source of truth for the `diagnoser` manifest section.
- `~/coding/metta/packages/coworld/src/coworld/GAME_RUNTIME_README.md` - canonical game runtime contract.
- `~/coding/metta/docs/specs/0043-user-container-management.md` - shared runnable shape behind game, player, grader, reporter, commissioner, diagnoser, and optimizer roles.
- `~/coding/metta/packages/coworld/src/coworld/examples/paintarena/` - simplest reference coworld.

## Conventions for new diagnosers

- Keep concrete diagnoser implementations under the top-level `diagnosers/` tree.
- Keep one leaf directory per runnable image or entrypoint.
- Keep game-specific code under that game's directory.
- Do not invent a runtime contract inside an implementation. Update `docs/DIAGNOSER_DESIGN.md` and the metta coworld contract first.
- Keep game/runtime package code in its owning repo unless the file is genuinely diagnoser source.
