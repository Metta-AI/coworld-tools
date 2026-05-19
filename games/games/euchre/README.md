# cogame-euchre

**Euchre** — a 4-player trick-taking card game — built as a standalone
[cogame](https://github.com/Metta-AI/cogame) on the
[MettaGrid](https://github.com/Metta-AI/mettagrid) engine.

All game logic is declarative mettagrid config (handlers, events, mutations,
filters). No Python wrapper or controller runs during simulation — the rules
are enforced by the engine itself.

## Gameplay

- **4 players**, 2 teams (P0+P2 vs P1+P3), sitting at the corners of the table
- **24-card deck**: 9, 10, J, Q, K, A × ♠ ♥ ♦ ♣
- **5 tricks per hand**, one hand per episode (v1)
- **Fixed trump** chosen at deal time from the kitty
- **Right bower** (J of trump) is the highest card, **left bower** (J of same
  color) is second highest
- **Follow-suit enforced** via per-suit agent counts — a player void in the led
  suit may play any card
- **Scoring**: 3+ tricks = 1 point, all 5 (march) = 2 points

Agents play a card by moving onto one of their five card slots. Play slots
accumulate the cards played this trick; the engine evaluates the winner at
`cards_played == 4` and resets for the next lead.

## Quickstart

Install [`uv`](https://docs.astral.sh/uv/) first. It reads `.python-version`
and the `requires-python` constraint in `pyproject.toml` to install and pin
CPython 3.12 automatically — you don't need a system Python 3.12.

```bash
# 1. Create the env (uv installs Python 3.12 if missing) and sync deps.
uv sync --extra dev

# 2. Run the tests
uv run pytest

# 3. Run a quick headless episode
uv run euchre-play --render none --max-steps 200
```

If you prefer pip, activate the uv-managed venv and use pip:

```bash
uv venv                   # creates .venv with pinned Python 3.12
source .venv/bin/activate
pip install -e '.[dev]'
pytest
```

## Variants

Euchre ships without variants in v1. The variant tree under
`src/cogame_euchre/variants/` is wired but empty; add new variants there as
new `CoGameMissionVariant` subclasses (e.g. `fixed_trump`, `stick_the_dealer`,
`go_alone`, `play_to_10`).

## Repository layout

```
cogame-euchre/
├── src/cogame_euchre/
│   ├── game.py             # EuchreMission, EuchreCoGame, all game mechanics
│   ├── cli.py              # euchre-play console script
│   ├── missions/default.py # make_default_mission()
│   └── variants/           # (empty) variant registry
├── tests/
│   ├── test_card_logic.py   # card power / deck setup
│   ├── test_interactions.py # integration: turns, card play, tricks
│   ├── test_registration.py # registration smoke test
│   └── test_default_play.py # 10-tick headless episode
├── docs/                   # MAKING_A_COGAME.md + TECHNICAL_MANUAL.md + mettagrid/*
├── skills/                 # cg.game.* game-authoring skills
└── pyproject.toml
```

See [`AGENTS.md`](AGENTS.md) for the AI-agent entry point.

## Origin

Ported from `claude/implement-euchre-game-LGCS6` in `metta-ai/metta` into a
standalone cogame repository, using `metta-ai/cogame` as the template.
