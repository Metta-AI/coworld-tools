# Cogony Policy

Minimal LLM+Python policy for CoGames submission. Skills and tooling live in the cogamer repo.

## Commands

```bash
pip install -e ".[llm]"                    # Install with LLM support
pytest tests/ -v                           # Run all tests

# Play
softmax cogames play -m machina_1 -p class=cogony_policy.cogamer_policy.CogonyPolicy --render=gui

# Evaluate
softmax cogames eval -m machina_1 -p class=cogony_policy.cogamer_policy.CogonyPolicy -e 10 --format json

# Submit
scripts/submit.sh                         # default: daveey.cogony_policy @ beta-cvc
scripts/submit.sh <name> <season>         # custom name and season
```

## Key Files

- `src/cogony_policy/cogamer_policy.py` — CogonyPolicy entry point, LLM↔Python bridge
- `src/cogony_policy/programs.py` — program table (32 programs, main evolvable surface)
- `src/cogony_policy/game_state.py` — observation processing, state management
- `src/cogony_policy/agent/main.py` — CvcEngine decision tree
- `src/cogony_policy/agent/roles.py` — role-specific actions (miner, aligner, scrambler)
- `src/cogony_policy/agent/targeting.py` — target selection and scoring
- `src/cogony_policy/agent/pressure.py` — role budgets and retreat thresholds
- `docs/architecture.md` — architecture reference with alpha.0 comparison

## Game Modes

Cogony is a **fully cooperative** game. All policies on the map are on the same team — there are no opponents. The score reflects how well the team performs together.

- **Single-team (default, e.g. `machina_1`)**: 8 agents, all same team, playing against the environment. Tournament matches pair your policy with another policy's agents on the same team.
- **Multi-team (e.g. `four_score` variant)**: Multiple teams compete. Not the default tournament format.

When evaluating policy changes, remember that tournament score depends on how well your agents cooperate with *unknown teammate policies*. Resources (extractors) are shared — teammates will drain extractors you've seen, so stale world model data matters.

## Non-Negotiables

1. Let it crash — no try/except for error hiding
2. Minimal diffs — smallest change that fixes the root cause
3. Fix root causes, not symptoms
