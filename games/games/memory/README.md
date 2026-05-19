# memory

A starter template for a **new MettaGrid game** that builds on the full
[`cogames`](https://github.com/Metta-AI/metta/tree/main/packages/cogames)
variant framework.

This template gives you:

- a Python package (`src/cogame/`) with a runnable placeholder mission,
- a variant tree wired into `cogames.variants.VariantRegistry` (with dependency
  resolution, topological configure order, and the standard
  `PUBLIC / HIDDEN / resolve_variant_selection` layout),
- a game registration available through `cogames.game.get_game("memory")` after import,
- a standalone `memory-play` CLI for quick local sanity checks,
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

```bash
# 1. Create a virtualenv (Python 3.12)
python3.12 -m venv .venv
source .venv/bin/activate

# 2. Install in editable mode with dev extras
pip install -e '.[dev]'

# 3. Run the tests (all four suites should pass)
pytest

# 4. Run a quick headless episode
memory-play --render none --max-steps 20

# 5. Stack variants
memory-play --render none --max-steps 10 -v easy -v big_map
```

## Variants shipped

| name      | visibility | effect                                                     |
|-----------|------------|------------------------------------------------------------|
| `easy`    | public     | Larger HP/ore caps, agents start with more HP.             |
| `hard`    | public     | Halved `max_steps`, tighter ore cap.                       |
| `big_map` | public     | 13×13 arena with four corner spawns, scales to 4 agents.   |
| `full`    | hidden     | Interface variant: requires `hard` + `big_map`, halves `max_steps` again. |

`full` is the canonical *interface variant* pattern: requesting it via
`memory-play -v full` automatically pulls `hard` and `big_map` into the `VariantRegistry` through
`Deps(required=[...])`, configures them in topological order, and then runs
`FullVariant.modify_env` on top.

## Rename checklist

Before committing the template to your new game, rename:

1. `pyproject.toml` — `name`, `description`, URLs, and the script entry point
   `[project.scripts] memory-play = ...`.
2. `src/cogame/` → `src/<your_game>/` (update every import accordingly).
3. `cogame.game.MyCoGame.name = "memory"` → your game's registration name.
4. `cogame.game.MyMission` → `YourMissionName`.
5. `tests/` — search/replace `cogame` → `<your_game>`.
6. `README.md`, `AGENTS.md` — update references.

Once renamed, bootstrap your content via [`skills/cg.game.new-game/SKILL.md`](skills/cg.game.new-game/SKILL.md).

## Repository layout

```
cogame/
├── src/cogame/           # game.py, variants/, missions/, cli.py
├── tests/                # registration, play, dependencies, stacking
├── docs/                 # MAKING_A_COGAME.md + TECHNICAL_MANUAL.md + mettagrid/*
├── skills/               # 5 cg.game.* game-authoring skills
├── .claude/skills → ../skills
├── .codex/skills → ../skills
└── pyproject.toml
```

See [`AGENTS.md`](AGENTS.md) for the AI-agent entry point.
