# Migration Plan

## Goals

- Make `Metta-AI/games` the canonical source tree for game definitions and game runtime packages.
- Leave legacy repositories untouched until humans decide how to retire or mirror them.
- Keep each game's current package shape runnable during migration instead of forcing one runtime model.

## Repository Shape

- `games/<game>/`: imported game package or Coworld runtime.
- `templates/<template>/`: reusable game-authoring templates.
- `docs/`: shared migration notes, inventory, and game-authoring conventions.

See [`GAME_DESIGN.md`](GAME_DESIGN.md) for the repo-level conventions that distinguish `games`
from the role repos, and [`COWORLD_REFERENCE.md`](COWORLD_REFERENCE.md) for navigation into the
canonical Coworld sources in metta.

## Python Games

Python game packages are listed in the root `uv` workspace when their package layout is already self-contained. The
workspace is for repository-level discovery and lightweight package checks; each game still owns its own tests,
entrypoints, and dependency details.

First-wave standalone Coworld migrations are complete for `amongcogs`, `hungercog`, `overcogged`, `diplomacog`, and
`werecog`. Their renamed `Metta-AI/coworld-*` repositories are now the source of truth for certifiable runtime work;
this aggregate repo keeps matching snapshots while the standalone-per-game and aggregate-repo models are both under
consideration.

Follow-up work for Python games:

1. Update remaining package URLs from old standalone repos to their current source-of-truth location.
2. Move shared template docs and skills out of individual game packages when they are duplicated.
3. Update `Metta-AI/metta` and `Metta-AI/cogames` optional game metadata to point at current game sources.
4. Add targeted smoke tests per game from inside this repo.
5. Rename template-shaped imports that still expose `src/cogame` before adding them to the root `uv` workspace.

## Coworld Games

Coworld games are kept as container-first packages. They do not need to be Python workspace members.

Follow-up work for Coworld games:

1. Keep `certification.game_config` short and separate from production league variants.
2. Build and certify images from each game directory before uploading or seeding leagues.
3. Move shared Coworld protocol docs to `docs/` only after the package-local manifests link to stable public docs.
4. For private `coworld-*` repos, use SSH `source_url` values for game/player runnables so certification does not rely
   on unauthenticated GitHub API access to private repositories.

When testing the first-wave Coworld mirrors from this aggregate checkout, prefer isolated per-package `uv run` commands
from inside the game directory. The root workspace still includes older games with older `cogames` pins, so its shared
lock is not a reliable verification environment for these upgraded mirrors yet.

## Template Cleanup

The old `cogame` repo has been copied to `templates/mettagrid-python`. Future game repos should start from this
template in-place or via a generator, rather than cloning a standalone template repository.
