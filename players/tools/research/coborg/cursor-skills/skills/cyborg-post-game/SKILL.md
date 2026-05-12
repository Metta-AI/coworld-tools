---
name: cyborg-post-game
description: >-
  Run or configure post-game analysis on completed game memory dumps.
  Use when setting up the analysis pipeline, customizing the analysis prompt,
  reviewing learnings files, or running manual analysis. Triggers on "analyze",
  "post-game", "learnings", "score", "review game", "what went wrong".
---

# Post-Game Analysis

After each game, an analysis LLM reviews the memory dump and produces
structured learnings that feed back into the next game.

## How It Works

```
Game ends → memory dump (JSON) → analysis LLM → learnings.json
Next game loads learnings → enriched system prompt → better decisions
```

## Analysis Output Schema

Every game produces the same JSON schema:

```json
{
  "score": 7,
  "what_worked": ["gathered resources efficiently"],
  "what_failed": ["didn't transition roles early enough"],
  "actionable_rules": ["IF resources > 50 AND tick > 200 THEN switch role"],
  "biggest_mistake": "stayed in gatherer mode until tick 400",
  "recommended_next_game_strategy": "transition earlier"
}
```

## Customizing the Analysis Prompt

In your `game_config.py`, set `ANALYSIS_SYSTEM_PROMPT`:

```python
ANALYSIS_SYSTEM_PROMPT = """\
You are analyzing a completed {game_name} game.

Review the memory dump and assess:
1. Resource management efficiency
2. Role transition timing
3. Map exploration coverage
4. Response to opponent actions

Respond with JSON (no markdown fences):
{{
  "score": 7,
  "what_worked": ["..."],
  "what_failed": ["..."],
  "actionable_rules": ["IF x THEN y"],
  "biggest_mistake": "...",
  "recommended_next_game_strategy": "..."
}}
"""
```

## Running Analysis

### Automatic (via harness)

Set up `_run_post_game_background()` in your harness:

```python
def _run_post_game_background(self, dump, filepath, trigger):
    from framework.base_analysis import run_post_game_analysis
    run_post_game_analysis(
        dump, self._analysis_provider,
        memory_dump_path=filepath,
        system_prompt=ANALYSIS_SYSTEM_PROMPT,
    )
```

### Manual

```bash
python -c "
from framework.base_analysis import run_post_game_analysis
from framework.providers import create_analysis_provider
import json

provider = create_analysis_provider('bedrock')
with open('runs/my_game/abc123_memory.json') as f:
    dump = json.load(f)
run_post_game_analysis(dump, provider, memory_dump_path='runs/my_game/abc123_memory.json')
"
```

## Cross-Game Memory

`framework.base_evolution.accumulate_cross_game_memory()` tracks patterns
across games in `runs/cross_game_memory.json`:
- Recurring failures with frequency counts
- Successful strategies from high-scoring games
- Accumulated IF-THEN rules

## Score Tracking

```bash
python scripts/record_score.py --record --steps 2500 --game my_game
python scripts/record_score.py --avg 5 --game my_game
python scripts/record_score.py --history --game my_game
```

## Key Files

| File | Purpose |
|---|---|
| `framework/base_analysis.py` | Analysis runner, prompt builder, synthesis |
| `framework/score_tracker.py` | Score history, rolling avg, escalation |
| `scripts/record_score.py` | CLI for score tracking |
