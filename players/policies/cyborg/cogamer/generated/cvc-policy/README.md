# CvC Policy

A CvC (Claude vs Claude) policy for [CoGames](https://github.com/Metta-AI/cogames). Clone this repo, improve the policy, and submit to compete.

## Quick Start

```bash
# Clone
git clone https://github.com/Metta-AI/cogamer-policy-cvc.git
cd cogamer-policy-cvc

# Install
pip install -e ".[llm]"

# Play a game
softmax cogames play -m machina_1 -p class=cvc_policy.cogamer_policy.CvCPolicy --render=gui

# Evaluate
softmax cogames eval -m machina_1 -p class=cvc_policy.cogamer_policy.CvCPolicy -e 10 --format json

# Submit
cogames upload -p class=cvc_policy.cogamer_policy.CvCPolicy -n my-policy --setup-script setup_policy.py
```

## Architecture

The policy is a program table with 32 programs operating on `GameState`:

- **Query programs** — read game state (HP, position, inventory, junctions)
- **Action programs** — movement via A* pathfinding
- **Decision programs** — compose queries + actions (role selection, mining, combat)
- **LLM program** — periodic Claude calls for strategic analysis

See `docs/architecture.md` for details.

## Structure

```
src/cvc_policy/          # Policy implementation
  cogamer_policy.py      # CvCPolicy entry point
  programs.py            # Program table (32 programs)
  game_state.py          # Observation processing + state
  agent/                 # Engine: roles, targeting, navigation, etc.
docs/                    # Architecture and strategy reference
tests/                   # Unit tests
setup_policy.py          # Setup script for cogames upload
```
