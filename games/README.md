# Metta Games

Game definitions and runtime packages for Coworld-style environments.

This repository is the consolidation point for scattered Metta-AI game packages. The initial import preserves each
game's existing source layout under `games/<name>/` and keeps the old source repositories untouched.

## Layout

- `games/`: game packages and Coworld runtimes.
- `templates/`: reusable game templates.
- `docs/`: shared inventory and migration notes.

## Current Inventory

See [docs/inventory.md](docs/inventory.md) for the imported game list, source provenance, runtime type, and candidates
that were intentionally left out.

## Python Workspace

The root `pyproject.toml` defines a `uv` workspace for self-contained Python game packages:

```bash
uv run --package hungercog pytest games/hungercog/tests
uv run --package cogame-euchre pytest games/euchre/tests
```

JavaScript, TypeScript, Nim, and container-first Coworld games keep their local toolchains inside their game
directories.

## Migration Notes

See [docs/migration-plan.md](docs/migration-plan.md). In short:

1. Preserve imported game behavior.
2. Normalize package metadata and shared docs.
3. Update downstream `cogames` and Metta optional-game metadata to point at this repo's subdirectories.
4. Certify container-first Coworld games from their local manifests before live uploads.
