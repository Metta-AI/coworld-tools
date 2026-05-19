# AGENTS.md

Guidance for AI assistants working inside the standalone Diplomacog repo.

## Start Here

This repo is the Diplomacog game package downstream of the [`Metta-AI/cogame`](https://github.com/Metta-AI/cogame) standalone game template. It shares template git history so docs, skills, and repo guidance can be merged forward, but the real game code lives under `src/diplomacog`.

1. Read [`skills/cg.game.new-game/SKILL.md`](skills/cg.game.new-game/SKILL.md) before adding or reshaping game mechanics.
2. Read [`skills/cg.game.core-mechanics/SKILL.md`](skills/cg.game.core-mechanics/SKILL.md) to reason about rules, map, roles, and loops.
3. Use [`skills/cg.game.build-game/SKILL.md`](skills/cg.game.build-game/SKILL.md) for implementation work.
4. Use [`skills/cg.game.variant-tree/SKILL.md`](skills/cg.game.variant-tree/SKILL.md) when changing variants or dependencies.
5. Use [`skills/cg.game.generate-assets/SKILL.md`](skills/cg.game.generate-assets/SKILL.md) for renderer assets.

Player-authoring skills are not shipped here. Get them from `metta-ai/metta/skills/` only when this checkout is also being used to build a policy.

## Quick Commands

```bash
./install.sh                                             # install against the matching Metta branch
.venv/bin/python -m pytest -q                           # full standalone tests
uv run ruff check .                                      # lint
metta play diplomacog render=none max_steps=8 cogs=6 seed=9
```

## Architecture

- [`src/diplomacog/game.py`](src/diplomacog/game.py) defines the mission, map builder, resources, handlers, observations, rewards, and `make_diplomacog_mission`.
- [`src/diplomacog/cogame.py`](src/diplomacog/cogame.py) registers Diplomacog with `cogames` as `diplomacog`.
- [`src/diplomacog/recipe.py`](src/diplomacog/recipe.py) exposes the Metta `play` entrypoint used by the monorepo optional game extra.
- [`src/diplomacog/variants/`](src/diplomacog/variants) contains public launch variants and hidden mechanic-building variants.
- [`src/diplomacog/agent/diplomacy_agent/policy.py`](src/diplomacog/agent/diplomacy_agent/policy.py) contains the scripted baseline policy.
- [`assets/mettascope/diplomacy/`](assets/mettascope/diplomacy) contains Diplomacog renderer assets.
- [`tests/`](tests) contains standalone smoke and policy tests.

## Template Sync

This clone should have a local `cogame` remote:

```bash
git remote add cogame git@github.com:Metta-AI/cogame.git  # if missing
git fetch cogame
git merge cogame/main
```

Resolve template merges toward Diplomacog package names, assets, tests, and docs. Never push to `Metta-AI/cogame` from this repo.

## Reference Documentation

- [`docs/MAKING_A_COGAME.md`](docs/MAKING_A_COGAME.md) is the template guide for authoring a cogame from scratch.
- [`docs/TECHNICAL_MANUAL.md`](docs/TECHNICAL_MANUAL.md) is the cogames technical manual.
- [`docs/mettagrid/`](docs/mettagrid) contains mettagrid API references.

## Non-Negotiables

1. **Run the code.** If a change is local and reversible, run tests, lint, or `metta play` to verify it. Do not ask permission for local reversible operations.
2. **Do not paper over errors.** Let exceptions crash with full tracebacks. Avoid `try/except` that hides broken invariants.
3. **Minimal diffs, root-cause fixes.** Write the smallest change that actually solves the problem. If the real fix touches adjacent files, touch them.
4. **No backwards-compat shims.** This package is the standalone game surface. Update callers to the current shape instead of layering aliases.
5. **Prefer pydantic models over raw dicts.** `MettaGridConfig` and related config types are pydantic models, so use typed fields directly.
