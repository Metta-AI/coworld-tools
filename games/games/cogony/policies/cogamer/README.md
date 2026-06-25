# Cogony Cogamer Policy

A Cogony (Claude vs Claude) policy for [CoGames](https://github.com/Metta-AI/cogames).

This package was imported from the archived `Metta-AI/cogamer-policy-cogony` repo and now lives under
`Metta-AI/games` with the rest of the Cogony game sources.

## Quick Start

```bash
cd games/cogony/policies/cogamer

# Install
pip install -e ".[llm]"

# Play a game
softmax cogames play -m machina_1 -p class=cogony_policy.cogamer_policy.CogonyPolicy --render=gui

# Evaluate
softmax cogames eval -m machina_1 -p class=cogony_policy.cogamer_policy.CogonyPolicy -e 10 --format json

# Submit
cogames upload -p class=cogony_policy.cogamer_policy.CogonyPolicy -n my-policy --setup-script setup_policy.py
```

## Migration Status

The core policy unit tests run under the current package dependencies. The legacy scenario harness still references the
removed `cogames.games.cogs_vs_clips` mission namespace and needs a follow-up port to current `cogony.CogonyMission`
scenarios before the full archived test suite can pass.

## Architecture

The policy is a program table with 32 programs operating on `GameState`:

- **Query programs** — read game state (HP, position, inventory, junctions)
- **Action programs** — movement via A* pathfinding
- **Decision programs** — compose queries + actions (role selection, mining, combat)
- **LLM program** — periodic Claude calls for strategic analysis

See `docs/architecture.md` for details.

## Structure

```
src/cogony_policy/          # Policy implementation
  cogamer_policy.py      # CogonyPolicy entry point
  programs.py            # Program table (32 programs)
  game_state.py          # Observation processing + state
  agent/                 # Engine: roles, targeting, navigation, etc.
docs/                    # Architecture and strategy reference
tests/                   # Unit tests
setup_policy.py          # Setup script for cogames upload
```
