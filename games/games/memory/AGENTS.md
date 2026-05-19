# AGENTS.md

Guidance for AI assistants (Claude Code, Codex) working inside this template.

## Start here

This is a **template** for a new MettaGrid game. The placeholder game is a
trivial 2-agent ore-mining loop designed to compile, play, and pass tests on a
fresh clone so you can see every wire before rewriting the interior.

1. Read [`skills/cg.game.new-game/SKILL.md`](skills/cg.game.new-game/SKILL.md)
   first — it's the design-first workflow for turning this scaffold into a
   real game.
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
pytest                                        # full test suite
memory-play --render none --max-steps 20      # standalone sanity check
memory-play -v easy                            # standalone CLI
```

## Architecture

- [`src/cogame/game.py`](src/cogame/game.py) — the `MyMission` + `MyCoGame`
  classes. `register_game(MyCoGame())` at the bottom wires the game into
  `cogames`' global registry at import time.
- [`src/cogame/variants/`](src/cogame/variants) — the variant tree. Every
  variant subclasses `cogames.core.CoGameMissionVariant`. `FullVariant` in
  `mechanics.py` demonstrates `dependencies()` + `configure(deps)`.
- [`src/cogame/variants/__init__.py`](src/cogame/variants/__init__.py) —
  exports `PUBLIC_VARIANT_TYPES`, `HIDDEN_VARIANT_TYPES`, and
  `resolve_variant_selection()` following the overcogged convention.
- [`src/cogame/cli.py`](src/cogame/cli.py) — the `memory-play` console script.
- [`src/cogame/__init__.py`](src/cogame/__init__.py) — side-effect imports
  that register the game with `cogames`.

## Reference documentation (local)

- [`docs/MAKING_A_COGAME.md`](docs/MAKING_A_COGAME.md) — step-by-step guide
  for authoring a cogame from scratch.
- [`docs/TECHNICAL_MANUAL.md`](docs/TECHNICAL_MANUAL.md) — the cogames
  technical manual.
- [`docs/mettagrid/`](docs/mettagrid) — mettagrid API references
  (actions, capabilities, observations, simulator API, territory).

## Non-negotiables

1. **Run the code.** If a change is local and reversible, run `pytest`,
   `memory-play --render none`, or `cogames play` to verify. Don't ask
   permission for local, reversible operations.
2. **Don't paper over errors.** Let exceptions crash with a full traceback.
   `try/except` that swallows errors silently is worse than no handling at all.
3. **Minimal diffs, root-cause fixes.** Write the smallest change that
   actually solves the problem. If the fix needs to touch adjacent files,
   touch them.
4. **No backwards-compat shims.** This is a template — there is no legacy
   surface to preserve. Rewrite, don't layer.
5. **Prefer pydantic models over raw dicts.** `MettaGridConfig` and its
   children are pydantic — use them directly, not via `dict.get(..., None)`.

## Where to make changes

- **Mechanics** — rewrite `MyMission.make_base_env` in
  [`src/cogame/game.py`](src/cogame/game.py) and the objects/actions block.
- **Maps** — replace `DEFAULT_MAP` in `game.py` and add new
  `AsciiMapBuilder.Config` helpers in variant modules.
- **Variants** — add new modules under `src/cogame/variants/` and register
  their classes in `PUBLIC_VARIANT_TYPES` / `HIDDEN_VARIANT_TYPES`.
- **Missions** — add factories under `src/cogame/missions/` and include
  their output in `MyCoGame._ensure_loaded`.
