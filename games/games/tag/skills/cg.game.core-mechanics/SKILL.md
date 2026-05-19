---
name: cg.game.core-mechanics
description:
  Use when designing or repairing a CoGames-style game and the main risk is that the rules, map, roles, or play loop do
  not yet match the real game or prompt closely enough.
---

# Core Mechanics

## Overview

Lock the game loop before art or variant factoring. The target is a mechanically faithful, fully playtested slice that
matches the real game, prompt, and expected map/theme in headless and GUI play.

**Announce at start:** "I’m using cg.game.core-mechanics: I’ll match the real game loop first and prove it with focused
playtests before touching art or variant factoring."

## Workflow

1. Ground the target. Read the current game README/CONTEXT, recipe entrypoints, nearby tests, old Codex logs, and the
   real game or prompt. Write down the concrete loop you must preserve: roles, stations, win conditions, map/layout
   expectations, and what players should obviously see on screen. For net-new games, this contract should come from
   `cg.game.new-game`; for overhauls, derive it before editing.

2. Check the existing entrypoint immediately. Use the repo-native play command before editing:

   ```bash
   metta play among_us -- render=none max_steps=200
   ./tools/run.py play overcooked max_steps=40 render=none autostart=true seed=7
   metta play mafia render=none max_steps=60 seed=7
   ```

3. Fix the actual mechanics first. Add the nearest focused tests, then implement the smallest playable loop that proves
   the game works. Prefer interaction tests near `tests/metta/games/<game>/` and recipe-entrypoint checks near
   `tests/tools/`.

4. Match the real game, not the placeholder. If the map is too large, the roles do not create the right pressure, or the
   world still looks like the wrong biome (space asteroid instead of kitchen, ship, or village), stop and correct
   layout/terrain/mechanics before adding more systems.

5. Run both headless and GUI smoke loops. Headless catches rule regressions fast; GUI catches obvious feel/layout
   problems. Re-run until the game is readable without explanation.

6. Ship this stage only when the loop is stable. Do not split variants yet. Do not spend time polishing assets beyond
   what is necessary to verify the mechanics.

## Exit Criteria

- The canonical play command works.
- Focused mechanics tests pass.
- Headless smoke runs complete without obvious rule failures.
- GUI play shows the intended game shape clearly enough to judge the design.
- The current README/CONTEXT and the actual game behavior agree.

## Integration

**Uses:** `cf.bop-it`, `t.run-tests`, `cg.play`, `tr.cogames-variant-debug`

**Called by:** `cg.game.build-game`, `cg.game.new-game`

**Pairs with:** `cg.game.generate-assets`, `cg.game.variant-tree`
