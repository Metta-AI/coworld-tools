---
name: cg.game.build-game
description:
  Use when implementing or overhauling a CoGames-style game once the target contract is known, including scaffold,
  registration, mechanics, assets, and variant factoring.
---

# Build Game

## Overview

`cg.game.build-game` is the shared implementation loop for the `cg.game` suite. Use it once the target game contract is
known: for blank-sheet games after `cg.game.new-game`, or directly for existing-game fixes and overhauls. For a new
game, this means turning the rules contract into `game.py`, `map.py`, tests, a recipe entrypoint, and a playable default
path. The order stays the same: mechanics first, art second, variant factoring last.

**Announce at start:** "I’m using cg.game.build-game: I’ll lock mechanics first, then generate/namescape assets, then
factor the stable game into a variant tree."

## Entrypoint Rules

- Start with `cg.game.new-game` if the game does not exist yet or the design/engine mapping is still fuzzy.
- Start with `cg.game.build-game` if the target loop is already known and the work is implementation or overhaul.
- Start with `cg.game.build-player` if the rules are stable and only the player/policy behavior is changing.

## Workflow

1. Lock the contract first. If this is a net-new game, finish `cg.game.new-game` phase 1 and phase 2 before editing. If
   this is an overhaul, derive the same contract from the current game, README/CONTEXT, prompt, and tests.

2. Run `cg.game.core-mechanics`. Create or tighten the package scaffold, register the entrypoint, match the real game or
   prompt, shrink/fix the map if needed, and get focused tests plus headless/GUI play smokes green.

3. Run `cg.game.generate-assets`. Generate or reuse the right visual entities, namespace the outputs to the game, and
   prove the atlas/render path is clean.

4. Run `cg.game.variant-tree`. Only after the default game works, extract `full` plus meaningful slices into a
   dependency-closed local registry and, if needed, a curriculum tree.

5. Finish with bop-it discipline. Re-run the smallest relevant test and play/audit suite, lint the touched files, then
   commit/push/PR with the state of the game and the exact commands that passed.

## Implementation Checklist

- Keep the written rules contract close to the code and make the live game match it.
- For new games, create the game-local package, focused tests, and recipe entrypoint before broadening the scope.
- Prove the base/default game works before splitting into variants or polishing visuals.
- Use GUI play to catch readability/layout problems and headless play to catch rule/config regressions quickly.

## Stop Conditions

- Do not start implementation without a written contract.
- Do not generate polished art for a mechanically wrong game.
- Do not split variants while the default game is still unstable.
- Do not claim ship-readiness from screenshots alone; require headless or audit evidence.
- If the user wants reviewable work, keep the phases in separate commits or stacked PRs instead of one giant diff.

## Exit Criteria

- The real-game fidelity concerns are addressed in mechanics and layout.
- The game package, tests, and recipe entrypoint exist and run.
- The game-specific art is namespaced and rendered cleanly.
- The stable game exists both as the default experience and as an explicit variant tree.
- Tests, play smokes, and any available audit/headless loops are recorded in the PR.

## Integration

**Uses:** `cg.game.core-mechanics`, `cg.game.generate-assets`, `cg.game.variant-tree`, `cf.bop-it`

**Pairs with:** `cg.game.new-game`, `pr.summary`, `pr.check-ci`
