# archive/

Retired code, kept only for recovery. Nothing here is part of the active
`players` distribution, and pytest is configured to skip this tree
(`norecursedirs` in `pyproject.toml`). Paths mirror their original location
in the repo so a move back is mechanical.

## Contents

### `players/among_them/` — BitWorld "Among Them" (archived 2026-05-28)

The entire Among Them player tree, no longer in use. This was archived
immediately after the S4 coborg perception port landed (PR #19), so the
archived `coborg/` includes the full perception pipeline as of schema v5:

- `coborg/` — the Player SDK ("Coborg") example player: the perception port
  (`frame`, `sprite_match`, `actors`, `geometry`, `ignore`, `interstitial`,
  `localize`, `ocr`, `tasks`), the Nim-oracle parity harness and fixtures,
  and the Coworld policy bridge.
- `scripted/` — the `BitWorldAmongThem*` scripted policies.
- `starter/` — the Nim starter player.

Its validation suite moved with it:

- `validation/players-tests/among_them/` — per-game image-lifecycle tests.
- `validation/players-tests/test_bitworld_among_them_policy.py` — scripted
  policy behavior tests.

These import `players.among_them.*`, which no longer resolves while the code
lives under `archive/`. They are retained for reference, not execution.

> Not to be confused with `users/james/personal_cogs/among_them/` (the
> `guided_bot` Nim league bot), which is a separate, still-active project and
> was **not** archived.

## Restoring

Move the tree back to its original path and undo the reference removals:

```sh
git mv archive/players/among_them players/among_them
git mv archive/validation/players-tests/among_them validation/players-tests/among_them
git mv archive/validation/players-tests/test_bitworld_among_them_policy.py \
       validation/players-tests/test_bitworld_among_them_policy.py
```

Then re-add `"among_them"` to `players/__init__.py`'s `__all__` and restore the
layout/import references in `README.md`, `players/README.md`, and `docs/`
(see the archiving commit for the exact lines).
