# commissioners

Commissioner implementations for **coworlds** - containers and tooling that orchestrate tournament rounds, schedule episodes, carry round state, and return scoring or graduation decisions to the platform.

> **Status:** canonical Coworld role repo. The default and Among Them commissioners are runnable containers with `/healthz` and `/round` endpoints. The coworld `commissioner` role already has a protocol in metta; see [`docs/COMMISSIONER_DESIGN.md`](docs/COMMISSIONER_DESIGN.md) for pointers and repo conventions.

## What is a coworld commissioner?

A **coworld** is a Softmax v2 tournament unit: one game container + one or more player containers + a `coworld_manifest.json`. A **commissioner** is an optional role declared in the manifest under `commissioner: [...]` that participates in tournament round orchestration.

The canonical protocol lives in the metta repo at `packages/coworld/src/coworld/commissioner/protocol.py`. This repo is for commissioner implementations and scaffolding, not for redefining that protocol.

Commissioner lifetime is the lifetime of one round. The platform starts a commissioner round session by opening `/round` and sending `round_start`; the commissioner schedules episodes, receives `episode_result` or `episode_failed` messages, and eventually sends `round_complete`. A commissioner may schedule additional episodes from `on_episode_completed` in response to completed or failed episodes, so failures can trigger retries, replacements, or other adaptive round-local work before the round is closed.

Coworld background: [`docs/COWORLD_REFERENCE.md`](docs/COWORLD_REFERENCE.md). Commissioner protocol notes: [`docs/COMMISSIONER_DESIGN.md`](docs/COMMISSIONER_DESIGN.md).

## Repository layout

```text
commissioners/
|-- README.md
|-- pyproject.toml
|-- docs/
|   |-- COWORLD_REFERENCE.md
|   `-- COMMISSIONER_DESIGN.md
`-- commissioners/
    |-- templates/
    |   `-- commissioner_template/
    |-- among_them/
    |   `-- among_them_commissioner/
    |-- paint_arena/
    |   `-- paint_arena_commissioner/
    `-- cogs_v_clips/
        `-- cogs_v_clips_commissioner/
```

Each leaf commissioner directory follows the same placeholder shape:

| File | Purpose |
| --- | --- |
| `<commissioner_name>.py` | Commissioner entrypoint placeholder. Implement against the metta commissioner protocol. |
| `build.sh` | Builds the commissioner's Docker image. Each commissioner can be its own image unless a shared image pattern emerges. |
| `README.md` | Commissioner-specific docs: scheduling policy, state shape, local test command, and dependencies. |

## Status of each commissioner

| Commissioner | Coworld | Status |
| --- | --- | --- |
| `templates/commissioner_template` | (template) | Scaffold only - no implementation |
| `default/default_commissioner` | Any | Active runnable commissioner |
| `among_them/among_them_commissioner` | Among Them | Active runnable commissioner |
| `paint_arena/paint_arena_commissioner` | PaintArena | Scaffold only - no implementation |
| `cogs_v_clips/cogs_v_clips_commissioner` | Cogs vs Clips | Scaffold only - no implementation |

## Related metta repo locations

- `~/coding/metta/packages/coworld/` - coworld package: manifest schema, runner, certifier, and role types.
- `~/coding/metta/packages/coworld/src/coworld/types.py` - source of truth for the `commissioner` manifest section.
- `~/coding/metta/packages/coworld/src/coworld/commissioner/protocol.py` - canonical commissioner protocol.
- `~/coding/metta/docs/specs/0043-user-container-management.md` - shared runnable shape behind game, player, reporter, commissioner, diagnoser, and optimizer roles.
- `~/coding/metta/packages/coworld/src/coworld/examples/paintarena/` - simplest reference coworld.

## Conventions for new commissioners

- Keep concrete commissioner implementations under the top-level `commissioners/` tree.
- Keep one leaf directory per runnable image or entrypoint.
- Keep game-specific code under that game's directory.
- Treat `packages/coworld/src/coworld/commissioner/protocol.py` as canonical. If the protocol needs to change, change it in metta first.
- Keep game/runtime package code in its owning repo unless the file is genuinely commissioner source.
