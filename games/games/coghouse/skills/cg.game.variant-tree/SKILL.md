---
name: cg.game.variant-tree
description:
  Use when a CoGames-style game already works visually and mechanically and now needs to be split into a composable
  variant registry, dependency tree, and optional curriculum tree without regressing the default game.
---

# Variant Tree

## Overview

Factor the finished game into variants only after the default experience is already working. The target is a typed,
dependency-closed variant tree whose default path still produces the same game the player just validated.

**Announce at start:** "I’m using cg.game.variant-tree: I’ll preserve the working game, factor it into a clean variant
registry, and prove the default/full paths still agree."

## Workflow

1. Freeze the baseline first. Start from a game that already passes `cg.game.core-mechanics` and
   `cg.game.generate-assets`. Do not refactor a broken or placeholder game into variants.

2. Define the interface and slices. Create one game-local `full` interface variant plus smaller mechanic or layout
   variants with explicit dependencies. Keep the slices meaningful: roles, tasks, meetings, recipe bundles, difficulty,
   layout, observability.

3. Preserve the default game. The zero-variant/default experience should still match the validated full game. Add tests
   that compare the default env surface against `variants=["full"]`.

4. Add dependency and labeling coverage. Follow the patterns from
   `tests/metta/games/overcooked/test_mechanics_variants.py`, `tests/metta/games/among_us/test_variants.py`, and
   `tests/metta/games/diplomacy/test_tree_curriculum.py`. Verify dependency closure, configured order, deduping, and
   that labels only include explicitly requested variants.

5. Expose the tree deliberately. Keep the registry game-local, and add a tree or curriculum layer only if it helps
   training or auditing. The tree should be inspectable through tests and CLI surfaces such as:

   ```bash
   cogame-play -v full
   cogame-play -v <variant_name> -- render=none max_steps=200
   ```

## Exit Criteria

- The default game still matches the previously validated experience.
- The game has a local variant registry with explicit dependency tests.
- `full` is an interface variant, not an excuse to hide unstructured mechanics.
- Focused variant/tree tests pass.
- CLI or audit entrypoints can exercise both the default game and at least one non-trivial slice.

## Integration

**Uses:** `cogame-play -v <variant>` (for local variant testing), `t.run-tests`, `cf.bop-it`

**Called by:** `cg.game.build-game`, `cg.game.new-game`

**Pairs with:** `cg.game.core-mechanics`, `cg.game.generate-assets`
