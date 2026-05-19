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

Follow-up work for Python games:

1. Update package URLs from old standalone repos to `Metta-AI/games`.
2. Move shared template docs and skills out of individual game packages when they are duplicated.
3. Update `Metta-AI/metta` and `Metta-AI/cogames` optional game metadata to point at this repo's subdirectories.
4. Add targeted smoke tests per game from inside this repo.

## Coworld Games

Coworld games are kept as container-first packages. They do not need to be Python workspace members.

Follow-up work for Coworld games:

1. Normalize manifests to the current `coworld_manifest_schema.json` shape.
2. Keep `certification.game_config` short and separate from production league variants.
3. Build and certify images from each game directory before uploading or seeding leagues.
4. Move shared Coworld protocol docs to `docs/` only after the package-local manifests link to stable public docs.

## Template Cleanup

The old `cogame` repo has been copied to `templates/mettagrid-python`. Future game repos should start from this
template in-place or via a generator, rather than cloning a standalone template repository.
