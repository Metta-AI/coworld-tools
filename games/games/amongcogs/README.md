# AmongCogs

Standalone home for the social-deduction game formerly developed in the Metta monorepo.

This repository is downstream of [`Metta-AI/cogame`](https://github.com/Metta-AI/cogame), the shared standalone-game template. Template docs, skills, and agent guidance live here so future template updates can be merged into AmongCogs without copying files by hand.

## Status

This repo contains the game-specific code, assets, scripted agents, and focused tests. Engine and platform hooks still live in `mettagrid`, `cogames`, and `cog-cyborg`; until those changes are merged and released, this repo pins those dependencies to the Metta commit it was extracted from.

## Install

```bash
uv sync
```

## Run

Headless smoke run:

```bash
uv run amongcogs-headless --num-agents 8 --max-steps 120 --episodes 1 --output summary
```

Direct Python usage:

```python
from amongcogs.runtime import make_game

env = make_game("amongcogs", num_agents=8, max_steps=120)
```

Metta play bridge:

```bash
uv run --extra amongcogs metta play amongcogs render=none max_steps=8 cogs=6 seed=0
```

## Tests

```bash
uv run pytest tests/amongcogs -q
```

## Layout

- `src/amongcogs/` game package
- `src/amongcogs/agent/` scripted and cyborg policies
- `src/amongcogs/game/` mechanic variants
- `src/amongcogs/missions/` base mission wiring
- `src/amongcogs/assets/` art prompts and derivation scripts
- `tests/amongcogs/` focused regression tests
- `docs/` and `skills/` shared game-authoring references inherited from `Metta-AI/cogame`
