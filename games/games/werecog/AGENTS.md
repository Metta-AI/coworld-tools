# AGENTS.md

Guidance for AI assistants working inside Werecog.

## Start Here

Werecog is a standalone MettaGrid / CoGames social-deduction game derived from
the shared [`Metta-AI/cogame`](https://github.com/Metta-AI/cogame) template.
This repository intentionally keeps a merge parent from `cogame/main` so template
documentation and authoring skills can be merged forward into downstream games.

## Quick Commands

```bash
pytest
werecog play --mission werecog --policy werecog --cogs 8 --render none
metta play werecog render=none max_steps=120 autostart=true
```

Use `./install.sh` when you need a branch-pinned Metta checkout with the
`werecog` extra installed.

## Architecture

- [`src/werecog/game.py`](src/werecog/game.py) defines the base mission and
  MettaGrid config.
- [`src/werecog/cogame.py`](src/werecog/cogame.py) registers Werecog with
  `cogames` and exposes the direct env factory.
- [`src/werecog/recipe.py`](src/werecog/recipe.py) owns the Metta play recipe
  that the Metta monorepo bridges to.
- [`src/werecog/variants/`](src/werecog/variants) contains the Werecog variant
  tree.
- [`src/werecog/policy.py`](src/werecog/policy.py) contains the scripted
  baseline policy.
- [`src/werecog/sdk/`](src/werecog/sdk) contains semantic-surface helpers.

## Template Sync

`cogame/main` is available as a merge parent. To pull future template updates:

```bash
git fetch cogame
git merge cogame/main
```

Do not push to `Metta-AI/cogame` from this repository. Resolve template merges by
keeping Werecog game code authoritative and accepting template changes only for
shared docs, skills, metadata, and broadly applicable scaffolding.

## Local Reference Documentation

- [`docs/MAKING_A_COGAME.md`](docs/MAKING_A_COGAME.md)
- [`docs/TECHNICAL_MANUAL.md`](docs/TECHNICAL_MANUAL.md)
- [`docs/mettagrid/`](docs/mettagrid)
- [`skills/cg.game.new-game/SKILL.md`](skills/cg.game.new-game/SKILL.md)
- [`skills/cg.game.build-game/SKILL.md`](skills/cg.game.build-game/SKILL.md)
- [`skills/cg.game.core-mechanics/SKILL.md`](skills/cg.game.core-mechanics/SKILL.md)
- [`skills/cg.game.variant-tree/SKILL.md`](skills/cg.game.variant-tree/SKILL.md)
- [`skills/cg.game.generate-assets/SKILL.md`](skills/cg.game.generate-assets/SKILL.md)

## Non-Negotiables

1. Run local, reversible checks instead of asking whether to run them.
2. Let unexpected errors crash with a real traceback.
3. Keep diffs minimal and fix root causes.
4. Do not add backwards-compatibility shims.
5. Prefer typed pydantic config objects over raw dict plumbing.
