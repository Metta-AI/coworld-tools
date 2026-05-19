# AGENTS.md

Guidance for AI assistants (Claude Code, Codex) working inside HungerCog.

## Start here

This repo is a downstream fork of [`Metta-AI/cogame`](https://github.com/Metta-AI/cogame)
for the standalone HungerCog game. HungerCog is the extracted Hunger survival
game that used to live in the Metta monorepo.

1. Read [`skills/cg.game.new-game/SKILL.md`](skills/cg.game.new-game/SKILL.md)
   first when designing a new game-sized mechanic or replacing the core game.
2. Then [`skills/cg.game.core-mechanics/SKILL.md`](skills/cg.game.core-mechanics/SKILL.md)
   to lock the rules, map, roles, and play loop before writing code.
3. Then [`skills/cg.game.build-game/SKILL.md`](skills/cg.game.build-game/SKILL.md)
   when you're ready to implement mechanics.
4. Use [`skills/cg.game.variant-tree/SKILL.md`](skills/cg.game.variant-tree/SKILL.md)
   once the base game works and you need to factor variants.
5. Use [`skills/cg.game.generate-assets/SKILL.md`](skills/cg.game.generate-assets/SKILL.md)
   once the game plays and you want real art and atlas entries.

Player-authoring skills (`build-player`, `audit-complete-episode`,
`profile-complete-episode`, `leaderboard-gap`, `scrimmage-gauntlet`,
`log-mine-player-design`, `map-mechanics`) are **not** shipped with this
template — they belong with the game's player/policy repo, not the game
repo. Grab them from `metta-ai/metta/skills/` if you end up building a
policy in this same checkout.

## Quick commands

```bash
uv run pytest tests -q
./install.sh
metta play hungercog render=none max_steps=20 autostart=true
```

## Architecture

- [`src/hungercog/game.py`](src/hungercog/game.py) defines the game and
  registers it with `cogames`.
- [`src/hungercog/variants/`](src/hungercog/variants) holds the HungerCog
  variant tree.
- [`src/hungercog/recipe.py`](src/hungercog/recipe.py) exposes the `play` and
  `train` recipe entrypoints used by Metta.
- [`src/hungercog/agent/`](src/hungercog/agent) contains the built-in scripted
  policy.

## Reference documentation (local)

- [`docs/MAKING_A_COGAME.md`](docs/MAKING_A_COGAME.md) — step-by-step guide
  for authoring a cogame from scratch.
- [`docs/TECHNICAL_MANUAL.md`](docs/TECHNICAL_MANUAL.md) — the cogames
  technical manual.
- [`docs/mettagrid/`](docs/mettagrid) — mettagrid API references
  (actions, capabilities, observations, simulator API, territory).

## Non-negotiables

1. **Run the code.** If a change is local and reversible, run `pytest`,
   `cogame-play --render none`, or `cogames play` to verify. Don't ask
   permission for local, reversible operations.
2. **Don't paper over errors.** Let exceptions crash with a full traceback.
   `try/except` that swallows errors silently is worse than no handling at all.
3. **Minimal diffs, root-cause fixes.** Write the smallest change that
   actually solves the problem. If the fix needs to touch adjacent files,
   touch them.
4. **No backwards-compat shims.** This is a standalone game repo. There is no legacy
   surface to preserve. Rewrite, don't layer.
5. **Prefer pydantic models over raw dicts.** `MettaGridConfig` and its
   children are pydantic — use them directly, not via `dict.get(..., None)`.

## Where to make changes

- **Mechanics** - update [`src/hungercog/game.py`](src/hungercog/game.py) and
  focused variant modules.
- **Variants** - add modules under `src/hungercog/variants/` and register them
  in [`src/hungercog/variants/__init__.py`](src/hungercog/variants/__init__.py).
- **Recipe surface** - update [`src/hungercog/recipe.py`](src/hungercog/recipe.py)
  when Metta CLI entrypoints change.
- **Policy** - update [`src/hungercog/agent/`](src/hungercog/agent) and cover
  behavior with regression tests.
