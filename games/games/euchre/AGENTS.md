# AGENTS.md

Guidance for AI assistants (Claude Code, Codex) working inside `cogame-euchre`.

## What this repo is

A standalone [cogame](https://github.com/Metta-AI/cogame) implementation of
**Euchre** (4-player trick-taking card game) built on the
[MettaGrid](https://github.com/Metta-AI/mettagrid) engine. All mechanics are
expressed as declarative mettagrid config — handlers, events, mutations,
filters. No Python wrapper or controller runs during simulation.

The game was ported from the `claude/implement-euchre-game-LGCS6` branch of
`metta-ai/metta` into this standalone repository, using `metta-ai/cogame` as
the template.

## Quick commands

```bash
pytest                                            # full test suite
euchre-play --render none --max-steps 200         # standalone sanity check
```

## Architecture

- [`src/cogame_euchre/game.py`](src/cogame_euchre/game.py) — the entire game.
  - Card resources (`CARD_RESOURCES`, 24 cards), per-suit count resources,
    state resources (`card_power`, `led_suit`, `trick_count_a/b`, etc.)
  - `compute_card_power(card, trump)` — trick-taking power (right bower = 106,
    left bower = 105, trump A = 104 … 9 = 100, non-trump A = 14 … 9 = 9)
  - Map layout — 13×15 ASCII grid, 4 players × 5 card slots, 4 play slots,
    central controller
  - `_card_slot_config(...)` — per-card `FirstMatch` handler with
    follow-suit filters (`play_card_lead`, `play_card_follow`,
    `play_card_void_{1..4}`)
  - `_game_flow_events(...)` — init, turn wrap-around, trick evaluation,
    end-of-hand scoring
  - `EuchreMission(CoGameMission)` — the mission class with `make_base_env`
  - `EuchreCoGame(CoGame)` — framework game handle
  - `register_game(EuchreCoGame())` at module bottom
- [`src/cogame_euchre/variants/`](src/cogame_euchre/variants) — variant tree.
  Empty in v1; add new `CoGameMissionVariant` subclasses here.
- [`src/cogame_euchre/missions/`](src/cogame_euchre/missions) — mission
  factories (`make_default_mission`).
- [`src/cogame_euchre/cli.py`](src/cogame_euchre/cli.py) — `euchre-play`
  console script.
- [`src/cogame_euchre/__init__.py`](src/cogame_euchre/__init__.py) —
  side-effect imports that register the game with the local framework.
- [`src/cogame_euchre/_asset_shim.py`](src/cogame_euchre/_asset_shim.py) —
  `EuchreRenderer` builds a merged data dir at GUI startup that overlays
  [`src/cogame_euchre/assets/`](src/cogame_euchre/assets) sprites on top of
  mettagrid's bundled mettascope data. Drop a PNG at
  `assets/objects/<name>.png` and mettascope picks it up.
- [`tools/build_card_sprites.py`](tools/build_card_sprites.py) — regenerate
  the 24 card faces, back, hand/play slot frames, and controller marker.

## Reference documentation (local)

- [`docs/MAKING_A_COGAME.md`](docs/MAKING_A_COGAME.md) — step-by-step guide
  for authoring a cogame from scratch.
- [`docs/TECHNICAL_MANUAL.md`](docs/TECHNICAL_MANUAL.md) — the technical
  manual.
- [`docs/mettagrid/`](docs/mettagrid) — mettagrid API references
  (actions, capabilities, observations, simulator API, territory).

## Non-negotiables

1. **Run the code.** If a change is local and reversible, run `pytest`,
   `euchre-play --render none` to verify. Don't ask
   permission for local, reversible operations.
2. **Don't paper over errors.** Let exceptions crash with a full traceback.
   `try/except` that swallows errors silently is worse than no handling at all.
3. **Minimal diffs, root-cause fixes.** Write the smallest change that
   actually solves the problem. If the fix needs to touch adjacent files,
   touch them.
4. **No backwards-compat shims.** Rewrite, don't layer.
5. **Prefer pydantic models over raw dicts.** `MettaGridConfig` and its
   children are pydantic — use them directly, not via `dict.get(..., None)`.

## Where to make changes

- **Mechanics** — rewrite handlers / events in
  [`src/cogame_euchre/game.py`](src/cogame_euchre/game.py). Read the
  `cg.game.core-mechanics` skill first if you're reshaping the rules.
- **New variants** — add a module under `src/cogame_euchre/variants/`,
  subclass `CoGameMissionVariant`, and register in `PUBLIC_VARIANT_TYPES` /
  `HIDDEN_VARIANT_TYPES`. See `skills/cg.game.variant-tree/SKILL.md`.
- **New missions** — add a factory under `src/cogame_euchre/missions/` and
  include its output in `EuchreCoGame._ensure_loaded`.
- **Tests** — `tests/test_card_logic.py` for pure card logic;
  `tests/test_interactions.py` for end-to-end simulation.

## Known limitations (v1)

- Single hand per episode (5 tricks), no multi-hand play-to-10 loop.
- Trump is fixed at deal time from the kitty; no bidding / dealer-pick-up /
  going-alone phase.
