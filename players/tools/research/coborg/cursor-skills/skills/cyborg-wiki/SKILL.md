---
name: cyborg-wiki
description: >-
  Create or update wiki knowledge pages for a game plugin or the framework.
  Use when writing strategy docs, skill guides, mechanics references, or
  updating the transferable knowledge base. Triggers on "wiki", "strategy doc",
  "skill doc", "mechanics doc", "game knowledge", "write documentation".
---

# Writing Wiki Pages

Wiki pages are markdown files that get loaded into the LLM's system prompt.
They teach the LLM about game mechanics, strategy, and skills.

## Two Wiki Layers

### Framework Wiki (`framework/wiki/`)

Game-agnostic knowledge that transfers across all games:
- `skills/` — frame parsing, movement, memory, LLM integration, role selection
- `strategy/` — opening, resources, adaptation, common mistakes, promoted patterns
- `mechanics/` — evolution loop, trigger system, memory tiers

**Only edit framework wiki to add universal patterns** — not game-specific tips.

### Game Wiki (`games/{game}/wiki/`)

Game-specific knowledge:
- `strategy/opening.md` — this game's opening strategy
- `strategy/common-mistakes.md` — this game's failure patterns
- `skills/` — game-specific skills (e.g., trading, combat, deception)
- `mechanics/` — game-specific mechanics (e.g., card types, map rules)

## Writing Style

Wiki pages are consumed by LLMs. Optimize for token efficiency:

1. **Be concise** — one idea per paragraph, no filler
2. **Use tables** for structured data (LLMs parse tables well)
3. **Use IF-THEN rules** — `IF resources > 50 AND tick > 200 THEN switch to builder`
4. **Include numbers** — concrete thresholds, not vague guidance
5. **Negative examples** — "Do NOT mine oxygen when carbon is at 0"
6. **No headers without content** — every section must have substance

## Page Template

```markdown
# Page Title

Brief one-line summary of what this page covers.

## Section 1

Concise explanation with concrete examples.

| Condition | Action | Why |
|---|---|---|
| HP < 20 | Flee | Survival override |
| Resources full | Deposit | Don't waste carrying capacity |

## Common Mistakes

- **Mistake name**: What goes wrong and how to fix it
```

## Evolution-Editable Wiki

Wiki files listed in `game_config.py`'s `EDITABLE_FILES` can be modified by
the evolution agent. The evolution agent updates wiki pages based on post-game
analysis, adding new rules and correcting outdated guidance.

Typical editable wiki files:
```python
EDITABLE_FILES = [
    "games/my_game/brain.py",
    "games/my_game/wiki/strategy/opening.md",
    "games/my_game/wiki/strategy/common-mistakes.md",
    "games/my_game/wiki/skills/combat.md",
]
```

## Pattern Promotion

Successful patterns from game-specific wiki get promoted to the framework
wiki via `scripts/promote_patterns.py`. This makes them available to all
future games.

## Wiki References

- `framework/wiki/strategy/promoted-patterns.md` — patterns promoted from games
- `framework/wiki/strategy/common-mistakes.md` — universal failure patterns
