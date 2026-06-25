# Metta Games

Game definitions and runtime packages for Coworld-style environments.

This repository is the consolidation point for scattered Metta-AI game packages. The initial import preserves each
game's existing source layout under `games/<name>/` and keeps the old source repositories untouched.

> **Status:** shared or staged game source inside `Metta-AI/coworld-tools`. A complete game-specific Coworld should
> still live in `Metta-AI/coworld-<slug>` with its manifest and game-local pieces. Use this tree for imported shared
> game packages, templates, and staging while assigning a game its canonical `coworld-*` owner.

## Layout

- `games/`: game packages and Coworld runtimes.
- `templates/`: reusable game templates.
- `docs/`: shared inventory, migration notes, and game-authoring guidance.

## Current Inventory

See [docs/inventory.md](docs/inventory.md) for the imported game list, source provenance, runtime type, and candidates
that were intentionally left out.

## Coworld Guidance

- [docs/COWORLD_REFERENCE.md](docs/COWORLD_REFERENCE.md) maps this repo to the canonical Coworld sources in metta.
- [docs/GAME_DESIGN.md](docs/GAME_DESIGN.md) explains how this repo should differ from the role repos like
  `players`, `reporters`, `diagnosers`, `commissioners`, and `optimizers`.

## Python Workspace

The root `pyproject.toml` defines a `uv` workspace for self-contained Python game packages:

```bash
uv run --package hungercog pytest games/hungercog/tests
uv run --package cogame-euchre pytest games/euchre/tests
```

JavaScript, TypeScript, Nim, and container-first Coworld games keep their local toolchains inside their game
directories. Python packages that are consumed as Coworld build-context sources, such as CogsGuard for Cogs vs Clips,
also keep their package metadata local instead of sharing the root workspace lock with older imported packages.

## Migration Notes

See [docs/migration-plan.md](docs/migration-plan.md). In short:

1. Preserve imported game behavior.
2. Normalize package metadata and shared docs.
3. Update downstream `cogames` and Metta optional-game metadata to point at this repo's subdirectories.
4. Certify container-first Coworld games from their local manifests before live uploads.
