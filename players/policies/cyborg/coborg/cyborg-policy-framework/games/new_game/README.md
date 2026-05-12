# New Game Template

Copy this directory to create a new game plugin: `cp -r new_game/ your_game/`

## Quick Start

```bash
# 1. Fork a weekly policy branch
python scripts/policy_manager.py fork --game your_game

# 2. Run games (update continuous_loop.sh call for your engine)
./scripts/continuous_loop.sh your_game

# 3. Check progress
python scripts/policy_manager.py status --game your_game

# 4. Generate a change report
python scripts/reporting_agent.py --game your_game

# 5. Promote successful patterns to the base policy
python scripts/promote_patterns.py --game your_game

# 6. Reset at end of week
python scripts/policy_manager.py reset --game your_game
```

## Files to Implement

| File | Purpose | Framework Base |
|---|---|---|
| `brain.py` | Per-tick decision logic | `BaseBrain` |
| `triggers.py` | Event detection for LLM consultation | `BaseEventDetector` |
| `harness.py` | LLM context building and directive parsing | `BaseHarness` |
| `policy.py` | `perceive()` and `execute()` bridge to engine | `BasePolicy` |
| `game_config.py` | Editable files, prompts, evolution config | `GameEvolutionConfig` |

## Framework Wiki (read these first)

Transferable skills — apply to any game:
- `framework/wiki/skills/frame-parsing.md` — how to parse observations into snapshots
- `framework/wiki/skills/movement.md` — pathfinding, exploration, stuck detection
- `framework/wiki/skills/memory-management.md` — three-tier memory system
- `framework/wiki/skills/llm-integration.md` — when/how to consult the LLM
- `framework/wiki/skills/role-selection.md` — role switching patterns

Universal strategy:
- `framework/wiki/strategy/opening.md` — first 10-20% of any game
- `framework/wiki/strategy/resource-management.md` — acquire/store/convert/deploy
- `framework/wiki/strategy/adaptation.md` — mid-game strategy shifts
- `framework/wiki/strategy/common-mistakes.md` — failure patterns to avoid
- `framework/wiki/strategy/promoted-patterns.md` — proven patterns from other games

Mechanics reference:
- `framework/wiki/mechanics/evolution-loop.md` — the self-improvement pipeline
- `framework/wiki/mechanics/trigger-system.md` — event detection and LLM scheduling
- `framework/wiki/mechanics/memory-tiers.md` — working/episodic/strategic memory

## Game-Specific Wiki

Add your own wiki pages under `wiki/` in your game directory:
- `wiki/strategy/` — game-specific strategy docs
- `wiki/mechanics/` — game-specific mechanics docs
- `wiki/skills/` — game-specific skills docs

These get loaded into the LLM system prompt and are editable by the evolution agent.

## Weekly Lifecycle

```
Week N:
  1. Fork from base → policy/{game}/2026-W17
  2. Run games + evolution (brain.py and wiki/ evolve)
  3. Reporting agent documents all changes
  4. Promotion pipeline extracts successful patterns
  5. Reset to base branch

Week N+1:
  1. Fork from base (which now includes promoted patterns)
  2. Start fresh — no accumulated tech debt from last week
  3. But framework wiki has new knowledge from last week's promotions
```
