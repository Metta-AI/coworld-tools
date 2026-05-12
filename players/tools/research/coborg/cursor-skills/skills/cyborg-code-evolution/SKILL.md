---
name: cyborg-code-evolution
description: >-
  Configure or run the self-improving code evolution pipeline. Use when
  setting up evolution for a new game, customizing editable files, tuning
  the evolution prompt, running manual evolution, or managing the weekly
  fork/reset lifecycle. Triggers on "evolution", "evolve", "self-improving",
  "str_replace", "fork", "reset", "promote", "weekly cycle".
---

# Code Evolution Pipeline

The evolution agent makes surgical code edits after each game based on
post-game analysis. Over hundreds of games, small changes compound.

## Setup for a New Game

### 1. Define editable files in `game_config.py`

```python
from framework.base_evolution import GameEvolutionConfig

EDITABLE_FILES = [
    "games/my_game/brain.py",
    "games/my_game/wiki/strategy/opening.md",
    "games/my_game/wiki/strategy/common-mistakes.md",
]

GAME_EVOLUTION_CONFIG = GameEvolutionConfig(
    game_name="my_game",
    editable_files=EDITABLE_FILES,
    system_prompt_template=EVOLUTION_SYSTEM_PROMPT,
    policy_dir_glob="games/my_game/",
)
```

### 2. Write the evolution system prompt

Tell the evolution agent about your game's architecture:

```python
EVOLUTION_SYSTEM_PROMPT = """\
You are a game AI policy engineer improving a {game_name} agent.

## Rules
1. Only tool: str_replace. Make 1-3 SURGICAL changes.
2. Only edit: {editable_files}
3. Write a ONE PARAGRAPH summary after changes.

## Architecture
- brain.py: per-tick decision engine with role-based dispatch
- wiki/: strategy knowledge loaded into the LLM prompt
- Thresholds are constants at the top of brain.py

Game: {game_name} | Game ID: {game_id}
"""
```

### 3. Wire into the harness

In `_run_post_game_background()`, call evolution after analysis.

## Evolution Modes

| Mode | How |
|---|---|
| `tool_use` | Multi-round `str_replace` tool loop (up to 10 rounds) |
| `json` | Single-shot JSON response with all edits |

Both use `framework.base_evolution`:
- `run_tool_use_evolution()` — multi-round with tool executor
- `run_json_evolution()` — single-shot JSON parse

## Git Workflow

After edits, `commit_and_track()` handles:
1. `git add` changed files
2. `git commit` with game ID and score
3. Push to `evolution/{game_id}` branch
4. Create PR via `gh pr create`
5. Auto-merge and rebase

## Weekly Lifecycle

```bash
# Fork a weekly branch
python scripts/policy_manager.py fork --game my_game

# Run the evolution loop
./scripts/continuous_loop.sh my_game

# Generate change report
python scripts/reporting_agent.py --game my_game

# Promote successful patterns to framework wiki
python scripts/promote_patterns.py --game my_game

# Reset to base at week end
python scripts/policy_manager.py reset --game my_game
```

## Pattern Promotion

`scripts/promote_patterns.py` scans learnings for high-scoring games,
extracts rules that appeared multiple times, filters out patterns that
also appear in failure lists, and appends winners to
`framework/wiki/strategy/promoted-patterns.md`.

## Safety

- **Git-based** — all changes are uncommitted; `git checkout -- .` reverts
- **File-scoped** — only files in `EDITABLE_FILES` can be edited
- **Logged** — `*_evolution.json` tracks files changed, tokens, cost

## Key Files

| File | Purpose |
|---|---|
| `framework/base_evolution.py` | str_replace executor, git workflow, cross-game memory |
| `scripts/policy_manager.py` | Fork/reset weekly branches |
| `scripts/reporting_agent.py` | Auto-document changes |
| `scripts/promote_patterns.py` | Extract and promote successful patterns |
| `scripts/continuous_loop.sh` | Outer loop template |
