# Werecog

Standalone home for the Werecog social-deduction game.

This repo owns the game-specific mission, variants, scripted baseline policy, semantic SDK helpers, and source art.
Core engine and CLI functionality stay in upstream packages such as `mettagrid` and `cogames`. Semantic-surface helpers still import `mettagrid-sdk` when that checkout is available.

## Current Status

This extraction was cut from `Metta-AI/metta` branch `relh/werewolf-single-pr`.
Standalone games now install into metta through optional extras on `cogames` instead of carrying branch-pinned upstream sources inside their own `pyproject.toml`. `metta play werecog` expects a `metta` checkout or install from the matching branch until the shared upstream support is released.

This repository carries `Metta-AI/cogame` as an upstream template merge parent.
Future template updates can be merged from `cogame/main` without rewriting
Werecog's game history.

## Install

```bash
pip install -e .
```

To install the branch-pinned stack needed for `metta play werecog`, create a virtualenv and run:

```bash
./install.sh
```

That clones the matching Metta branch, syncs the active virtualenv against the cloned Metta lockfile with the `werecog` extra enabled, then overlays the current Werecog checkout editable.

## Usage

Sync the repo and use the wrapper CLI:

```bash
uv sync
uv run werecog missions
uv run werecog play --mission werecog --policy werecog --cogs 8 --render unicode
```

To drive the same game through `metta play`, install the optional extra in a `metta` checkout on `relh/werewolf-single-pr`:

```bash
cd /path/to/metta
uv sync --extra werecog
uv run metta play werecog max_steps=120 render=none autostart=true
```

If you are actively editing the local Werecog checkout, you can still override the installed package with an editable install into the metta venv.

The package registers the Werecog game on import, owns the `werecog.play(...)` Metta recipe entrypoint, and the wrapper CLI delegates to the normal `cogames` CLI.

## Layout

- `src/werecog/game.py`: base mission definition
- `src/werecog/cogame.py`: CoGames registration and direct env factory
- `src/werecog/recipe.py`: Metta play recipe entrypoint
- `src/werecog/variants/`: mechanic variants and dependency graph
- `src/werecog/policy.py`: scripted baseline policy
- `src/werecog/sdk/`: optional semantic-surface helpers
- `src/werecog/assets/`: source art and asset-generation script

## Dev Validation

Focused tests live under `tests/`.
`uv sync` installs the declared package dependencies. If you need unreleased upstream `cogames` or `mettagrid` changes while developing locally, provide those via your metta checkout or local `uv` source overrides. The semantic-surface tests additionally need a local `mettagrid-sdk` checkout on `PYTHONPATH` until that package is published.

## Template Sync

This checkout has a local `cogame` remote for `https://github.com/Metta-AI/cogame.git`.
Do not push to that remote. To merge future template updates:

```bash
git fetch cogame
git merge cogame/main
```

Keep Werecog's `src/werecog` package authoritative and accept template changes
only where they improve shared docs, skills, metadata, or reusable scaffolding.
