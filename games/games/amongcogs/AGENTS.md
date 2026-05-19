# AGENTS.md

Guidance for AI assistants working inside the AmongCogs standalone game repo.

## Start Here

AmongCogs is a concrete game repo downstream of the shared
[`Metta-AI/cogame`](https://github.com/Metta-AI/cogame) template. Keep the
game-specific implementation in `src/amongcogs/`, and keep the inherited
template docs and skills current so future template updates can be merged
instead of copied manually.

1. Read [`src/amongcogs/README.md`](src/amongcogs/README.md) for game mechanics
   and current behavior.
2. Use [`skills/cg.game.core-mechanics/SKILL.md`](skills/cg.game.core-mechanics/SKILL.md)
   when changing rules, maps, roles, or the play loop.
3. Use [`skills/cg.game.build-game/SKILL.md`](skills/cg.game.build-game/SKILL.md)
   for larger mechanics implementation work.
4. Use [`skills/cg.game.variant-tree/SKILL.md`](skills/cg.game.variant-tree/SKILL.md)
   when adding or refactoring variants.
5. Use [`skills/cg.game.generate-assets/SKILL.md`](skills/cg.game.generate-assets/SKILL.md)
   for game art and atlas work.

## Quick Commands

```bash
uv sync
uv run pytest tests/amongcogs -q
uv run amongcogs-headless --num-agents 8 --max-steps 120 --episodes 1 --output summary
```

From a Metta checkout with the `amongcogs` extra:

```bash
uv run --extra amongcogs metta play amongcogs render=none max_steps=8 cogs=6 seed=0
```

## Architecture

- [`src/amongcogs/missions/mission.py`](src/amongcogs/missions/mission.py) defines the
  `AmongUsGame` mission and builds the `MettaGridConfig`.
- [`src/amongcogs/game/`](src/amongcogs/game) contains mechanic variants and the CoGame
  registration module.
- [`src/amongcogs/runtime.py`](src/amongcogs/runtime.py) exposes the local runtime
  registry and `make_game` helper used by tests and headless tools.
- [`src/amongcogs/recipe.py`](src/amongcogs/recipe.py) owns the Metta play recipe
  implementation; the Metta repo should only keep a thin bridge to this function.
- [`src/amongcogs/agent/`](src/amongcogs/agent) contains scripted and cyborg policies.
- [`tests/amongcogs/`](tests/amongcogs) contains focused game regressions.

## Reference Documentation

- [`docs/MAKING_A_COGAME.md`](docs/MAKING_A_COGAME.md)
- [`docs/TECHNICAL_MANUAL.md`](docs/TECHNICAL_MANUAL.md)
- [`docs/mettagrid/`](docs/mettagrid)

## Non-Negotiables

1. Run the code. If a change is local and reversible, run the relevant `pytest`,
   headless smoke, or Metta play command.
2. Do not paper over errors. Let exceptions crash with a full traceback.
3. Make minimal, root-cause changes. If the root cause touches adjacent files,
   touch them.
4. Do not add backwards-compat shims for stale template or extracted-monorepo
   paths. This repo owns the current game shape.
5. Prefer Pydantic config objects over raw dict plumbing.
