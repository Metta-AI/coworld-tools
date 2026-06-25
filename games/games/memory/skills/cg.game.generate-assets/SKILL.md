---
name: cg.game.generate-assets
description:
  Use when a CoGames-style game is mechanically working but still has missing, placeholder, wrongly themed, or
  non-namespaced art, terrain, or atlas entries.
---

# Generate Assets

## Overview

Generate or reuse art only after the game already plays. The target is a game-local, namespaced asset set that matches
the intended theme and renders cleanly in Mettascope without `unknown` placeholders.

**Announce at start:** "I’m using cg.game.generate-assets: I’ll generate or namespace the game’s art, then prove the
atlas and render path are clean before moving on."

## Workflow

1. Start from the live game, not the prompt list. Run the current play command first and note exactly which entities are
   visually wrong: missing stations, wrong biome, placeholder sprites, mixed folders, or unreadable terrain.

2. Read the merged ArtGen docs before touching prompts: `packages/mettagrid/nim/mettascope/tools/art/artgen.md`.
   Prefer the folder-driven ArtGen pipeline that Andre merged to `main`, not the older prompt-TSV image scripts.
   The current source of truth is:

   ```text
   tools/art/<game>/artin/
   tools/art/<game>/arttmp/
   tools/art/<game>/artout/
   ```

   Shared style and render defaults should live in inherited `_.md` files, with optional shared inspiration sheets such
   as `_.png`.

3. Find the game-local generation and promotion workflow. Prefer checked-in ArtGen trees and sync scripts that already
   live with the game. Example:

   ```bash
   cd packages/mettagrid/nim/mettascope
   nim r -d:release tools/art/artgen.nim \
     --input=tools/art/overcogged/artin \
     --output=tools/art/overcogged/artout \
     --keepConcept \
     --keep3d \
     --verbose

   python3 scripts/assetgen/sync_overcogged_artgen_assets.py

   cd packages/mettagrid/nim/mettascope
   nim r -d:release tools/gen_atlas.nim
   ```

4. Namespace the assets per game. Keep assets under a game-specific folder such as `data/amongus`, `data/overcooked`, or
   `data/diplomacy`. Do not mix new sprites into shared generic folders if the game is supposed to own them.

5. Reuse nearby art when it is genuinely the right fit. Borrow or adapt existing scripts/assets from similar games when
   that keeps the visual language coherent, but localize the prompts, paths, and output names to the target game.

6. When tuning style, preserve the shipped ArtGen defaults unless there is concrete evidence they are wrong. Start by
   aligning the target game's shared `_.md` and shared inspiration sheet with the merged stock profiles under
   `packages/mettagrid/nim/mettascope/tools/art/artin/`. Do not thrash render-light settings just because a result
   looks bad; first determine whether the problem is:

   - prompt or inspiration quality
   - model generation / conversion quality
   - final local sprite render

7. Verify the render path immediately. Add focused asset tests near `tests/metta/games/<game>/test_assets.py`, rerun
   the game-local promotion script, rebuild the atlas, then run a headless and GUI smoke check. Fail the pass if the
   world still looks like the wrong game or if atlas warnings fall back to unknown placeholders.

## Exit Criteria

- Asset generation commands are checked in or documented at the game-local path.
- The checked-in workflow uses the merged ArtGen folder pipeline where appropriate, not an obsolete prompt-TSV flow.
- Source assets and atlas entries are namespaced to the target game.
- Focused asset tests pass.
- Promotion script and atlas rebuild succeed for the touched asset set.
- GUI/headless play shows the right biome, stations, and entities for the game.
- No `unknown` / placeholder atlas fallback remains in the target surface.

## Integration

**Uses:** `cf.bop-it`, `t.run-tests`, `db.agent-browser-layout-debug`

**Called by:** `cg.game.build-game`, `cg.game.new-game`

**Pairs with:** `cg.game.core-mechanics`, `cg.game.variant-tree`
