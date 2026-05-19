# coghouse

A starter template for a **new [MettaGrid](https://github.com/Metta-AI/mettagrid)
game** with a self-contained variant framework. The framework classes
(`CoGameMission`, `CoGameMissionVariant`, `VariantRegistry`, `CoGame`,
`register_game`, `get_game`) live under [`src/cogame/framework/`](src/cogame/framework/),
so a repo based on this template depends only on `mettagrid` and
`pydantic` at runtime.

This template gives you:

- a Python package (`src/cogame/`) with a runnable placeholder mission,
- a self-contained variant framework (`src/cogame/framework/`) with dependency
  resolution, topological configure order, and the standard
  `PUBLIC / HIDDEN / resolve_variant_selection` layout,
- a standalone `coghouse-play` CLI for quick local sanity checks,
- the game-authoring [`cg.game.*`](skills/) skills (5 skills: `new-game`,
  `build-game`, `core-mechanics`, `variant-tree`, `generate-assets`) copied
  from `metta-ai/metta`, so AI agents have the same guidance inside a fresh
  `cogame` clone as they do inside the main monorepo. Player-authoring
  skills (profiling, leaderboard-gap, scrimmage-gauntlet, etc.) are
  intentionally excluded — this template is for building a new *game*, not
  for building a policy against an existing one.
- a full copy of `MAKING_A_COGAME.md`, `TECHNICAL_MANUAL.md`, and the five
  mettagrid API reference documents under [`docs/`](docs/).

## Quickstart

Install [`uv`](https://docs.astral.sh/uv/) first. It reads `.python-version`
and the `requires-python` constraint in `pyproject.toml` to install and pin
CPython 3.12 automatically — you don't need a system Python 3.12.

```bash
# 1. Create the env (uv installs Python 3.12 if missing) and sync deps.
uv sync --extra dev

# 2. Run the tests (all four suites should pass)
uv run pytest

# 3. Run a quick headless episode
uv run coghouse-play --render none --max-steps 20

# 4. Stack variants
uv run coghouse-play --render none --max-steps 10 -v easy -v big_map
```

If you prefer pip, activate the uv-managed venv and use pip:

```bash
uv venv                   # creates .venv with pinned Python 3.12
source .venv/bin/activate
pip install -e '.[dev]'
pytest
```

## Variants shipped

| name      | visibility | effect                                                     |
|-----------|------------|------------------------------------------------------------|
| `easy`    | public     | Larger HP/ore caps, agents start with more HP.             |
| `hard`    | public     | Halved `max_steps`, tighter ore cap.                       |
| `big_map` | public     | 13×13 arena with four corner spawns, scales to 4 agents.   |
| `full`    | hidden     | Interface variant: requires `hard` + `big_map`, halves `max_steps` again. |

`full` is the canonical *interface variant* pattern: requesting it via
`coghouse-play -v full` automatically pulls `hard` and `big_map` into the
`VariantRegistry` through `Deps(required=[...])`, configures them in
topological order, and then runs `FullVariant.modify_env` on top.

## Rename checklist

Before committing the template to your new game, rename:

1. `pyproject.toml` — `name`, `description`, URLs, and the script entry point
   `[project.scripts] coghouse-play = ...`.
2. `src/cogame/` → `src/<your_game>/` (update every import accordingly,
   including the `cogame.framework` references).
3. `cogame.game.MyCoGame.name = "coghouse"` → your game's registration name.
4. `cogame.game.MyMission` → `YourMissionName`.
5. `tests/` — search/replace `cogame` → `<your_game>`.
6. `README.md`, `AGENTS.md` — update references.

Once renamed, bootstrap your content via [`skills/cg.game.new-game/SKILL.md`](skills/cg.game.new-game/SKILL.md).

## Repository layout

```
cogame/
├── src/cogame/
│   ├── framework/        # Self-contained variant framework (core/variants/registry)
│   ├── game.py           # MyMission + MyCoGame, register_game(...) at module bottom
│   ├── variants/         # difficulty, layout, mechanics + variant tree wiring
│   ├── missions/         # mission factories
│   └── cli.py            # coghouse-play console script
├── tests/                # registration, play, dependencies, stacking
├── docs/                 # MAKING_A_COGAME.md + TECHNICAL_MANUAL.md + mettagrid/*
├── skills/               # 5 cg.game.* game-authoring skills
├── .claude/skills → ../skills
├── .codex/skills → ../skills
└── pyproject.toml
```

See [`AGENTS.md`](AGENTS.md) for the AI-agent entry point.
