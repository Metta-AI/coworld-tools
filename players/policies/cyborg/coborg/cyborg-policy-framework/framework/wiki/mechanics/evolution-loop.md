# Evolution Loop

How the self-improving code pipeline works.

## The Cycle

```
Play a game
  → Memory dump ({game_id}_memory.json)
  → Post-game analysis by LLM ({game_id}_learnings.json)
  → Code evolution: LLM edits brain.py and wiki/ based on learnings
  → Git commit + PR for tracking
  → Score recorded, escalation checked
  → Repeat
```

## Post-Game Analysis

After each game, an analysis LLM (typically a strong model like Opus/Sonnet) reviews
the full memory dump and produces structured learnings:

```json
{
  "score": 7,
  "what_worked": ["gathered resources efficiently in the opening"],
  "what_failed": ["didn't transition to building phase until too late"],
  "actionable_rules": ["IF resources > 50 AND tick > 200 THEN switch to builder"],
  "biggest_mistake": "stayed in gatherer mode until tick 400",
  "recommended_next_game_strategy": "Transition earlier, build more aggressively"
}
```

This schema is the same for every game. The analysis prompt is game-specific
(defined in `game_config.py`), but the output format is universal.

## Code Evolution

The evolution agent receives:
1. The learnings (score, mistakes, rules)
2. All editable source files (full text)
3. The memory dump (raw game data)
4. Cross-game memory (accumulated patterns)

It uses `str_replace` to make 1-3 surgical edits:
- **Change a constant**: raise/lower a threshold
- **Add a guard clause**: new condition at the top of a function
- **Update wiki guidance**: reflect a new insight

The editable files list is defined per game in `game_config.py`. Infrastructure
files (providers, evolution code itself) are never editable.

## Git Workflow

After edits:
1. `git add` the changed policy files
2. `git commit` with game ID and score in the message
3. Push to a remote `evolution/{game_id}` branch
4. Create a PR via `gh pr create` with the game summary
5. Auto-merge the PR for tracking
6. Rebase local to stay in sync

This creates a full audit trail of every change the evolution agent makes.

## Score Tracking & Escalation

`ScoreTracker` maintains a persistent score history. When the last N games
(default: 5) all score above a threshold (default: 8/10), the game difficulty
increases (more steps, harder opponents, larger maps).

This creates a natural curriculum:
```
Easy (2500 steps) → Medium (3500 steps) → Hard (4500 steps) → ...
```

## Cross-Game Memory

A persistent JSON file accumulates learnings across games:
- **Recurring failures**: mistakes that keep happening with frequency counts
- **Successful strategies**: what worked in high-scoring games
- **Accumulated rules**: "IF X THEN Y" patterns proven across multiple games
- **Score history**: rolling average to detect improvement or regression

This memory is injected into both the in-game LLM (as cross-game intelligence)
and the evolution agent (as context for what has/hasn't been tried).
