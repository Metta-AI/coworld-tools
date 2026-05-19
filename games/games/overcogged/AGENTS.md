# AGENTS.md

Guidance for AI assistants (Claude Code, Codex) working inside Overcogged.

## Start here

This is the standalone repository for the Overcogged MettaGrid game. It is based on the
[`Metta-AI/cogame`](https://github.com/Metta-AI/cogame) template, and keeps that template's
local docs and game-authoring skills so template updates can be merged downstream.

1. Read [`docs/MAKING_A_COGAME.md`](docs/MAKING_A_COGAME.md) for the standalone game contract.
2. Use [`skills/cg.game.core-mechanics/SKILL.md`](skills/cg.game.core-mechanics/SKILL.md)
   before changing rules, maps, roles, or the play loop.
3. Use [`skills/cg.game.build-game/SKILL.md`](skills/cg.game.build-game/SKILL.md)
   for mechanics work.
4. Use [`skills/cg.game.variant-tree/SKILL.md`](skills/cg.game.variant-tree/SKILL.md)
   when changing launch or curriculum variants.
5. Use [`skills/cg.game.generate-assets/SKILL.md`](skills/cg.game.generate-assets/SKILL.md)
   when adding art or atlas entries.

## Quick commands

```bash
pytest
overcogged play --render none --autostart --seed 7
overcogged play --mission classic --cogs 2 --render none --autostart --seed 7
```

For a direct local install with the CLI dependencies:

```bash
pip install -e ".[standalone]"
```

For the Metta handoff path:

```bash
./install.sh
metta play overcogged render=none autostart=true seed=7
```

## Architecture

- [`src/overcogged/game/game.py`](src/overcogged/game/game.py) contains the canonical kitchen mission and CoGame registration.
- [`src/overcogged/classic/`](src/overcogged/classic) contains the preserved classic mission.
- [`src/overcogged/variants/`](src/overcogged/variants) contains the launch and curriculum variant graph.
- [`src/overcogged/agent/overcogged_agent/`](src/overcogged/agent/overcogged_agent) contains the built-in scripted policy.
- [`src/overcogged/recipe.py`](src/overcogged/recipe.py) exposes the `metta play overcogged` recipe entrypoint.
- [`src/overcogged/cli.py`](src/overcogged/cli.py) is the `overcogged` console script.

## Reference documentation

- [`docs/MAKING_A_COGAME.md`](docs/MAKING_A_COGAME.md)
- [`docs/TECHNICAL_MANUAL.md`](docs/TECHNICAL_MANUAL.md)
- [`docs/mettagrid/`](docs/mettagrid)

## Non-negotiables

1. **Run the code.** If a change is local and reversible, run `pytest`, `overcogged play --render none`, or
   `metta play overcogged` to verify.
2. **Don't paper over errors.** Let exceptions crash with a full traceback.
3. **Minimal diffs, root-cause fixes.** Write the smallest change that actually solves the problem.
4. **No backwards-compat shims.** This is the standalone game source of truth.
5. **Prefer pydantic models over raw dicts.** `MettaGridConfig` and its children are pydantic.
