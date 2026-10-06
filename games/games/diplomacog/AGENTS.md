# AGENTS.md

Guidance for AI assistants working inside the standalone Diplomacog repo.

## Start Here

This repo is the Diplomacog game package downstream of the shared standalone game template. It shares template git history so docs, skills, and repo guidance can be merged forward, but the real game code lives under `src/diplomacog`.

1. Read [`skills/cg.game.new-game/SKILL.md`](skills/cg.game.new-game/SKILL.md) before adding or reshaping game mechanics.
2. Read [`skills/cg.game.core-mechanics/SKILL.md`](skills/cg.game.core-mechanics/SKILL.md) to reason about rules, map, roles, and loops.
3. Use [`skills/cg.game.build-game/SKILL.md`](skills/cg.game.build-game/SKILL.md) for implementation work.
4. Use [`skills/cg.game.variant-tree/SKILL.md`](skills/cg.game.variant-tree/SKILL.md) when changing variants or dependencies.
5. Use [`skills/cg.game.generate-assets/SKILL.md`](skills/cg.game.generate-assets/SKILL.md) for renderer assets.

Player-authoring skills belong in the player project. Use that project's guidance when building a policy.

## Quick Commands

```bash
.venv/bin/python -m pytest -q                           # full standalone tests
uv run ruff check .                                      # lint
```

## Architecture

- [`src/diplomacog/game.py`](src/diplomacog/game.py) defines the mission, map builder, resources, handlers, observations, rewards, and `make_diplomacog_mission`.
- [`src/diplomacog/cogame.py`](src/diplomacog/cogame.py) registers Diplomacog with `cogames` as `diplomacog`.
- [`src/diplomacog/recipe.py`](src/diplomacog/recipe.py) exposes the `play` entrypoint used by downstream integrations.
- [`src/diplomacog/variants/`](src/diplomacog/variants) contains public launch variants and hidden mechanic-building variants.
- [`src/diplomacog/agent/diplomacy_agent/policy.py`](src/diplomacog/agent/diplomacy_agent/policy.py) contains the scripted baseline policy.
- [`assets/mettascope/diplomacy/`](assets/mettascope/diplomacy) contains Diplomacog renderer assets.
- [`tests/`](tests) contains standalone smoke and policy tests.

## Template Sync

Review template updates from the upstream configured for this checkout.
Resolve merges toward Diplomacog package names, assets, tests, and docs.
Do not push changes to an upstream template without explicit authorization.

## Reference Documentation

- [`docs/MAKING_A_COGAME.md`](docs/MAKING_A_COGAME.md) is the template guide for authoring a cogame from scratch.
- [`docs/TECHNICAL_MANUAL.md`](docs/TECHNICAL_MANUAL.md) is the cogames technical manual.
- [`docs/mettagrid/`](docs/mettagrid) contains mettagrid API references.

## Non-Negotiables

1. **Run the code.** If a change is local and reversible, run tests or lint to verify it. Do not ask permission for local reversible operations.
2. **Do not paper over errors.** Let exceptions crash with full tracebacks. Avoid `try/except` that hides broken invariants.
3. **Minimal diffs, root-cause fixes.** Write the smallest change that actually solves the problem. If the real fix touches adjacent files, touch them.
4. **No backwards-compat shims.** This package is the standalone game surface. Update callers to the current shape instead of layering aliases.
5. **Prefer pydantic models over raw dicts.** `MettaGridConfig` and related config types are pydantic models, so use typed fields directly.
