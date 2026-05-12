# Cyborg Policy Framework — Architecture & Pipeline

A generalizable self-improving policy framework for game-playing AI agents. The system
runs a closed-loop pipeline: play a game, analyze performance, evolve the code, repeat.

## Architecture Overview

```
                    ┌─────────────────────┐
                    │  continuous_loop.sh  │  ← outer loop, runs forever
                    └──────────┬──────────┘
                               │
              ┌────────────────▼────────────────┐
              │         1. PLAY A GAME           │
              │  Your game engine + policy.py    │
              └────────────────┬────────────────┘
                               │
              ┌────────────────▼────────────────┐
              │    2. POST-GAME ANALYSIS         │
              │  LLM reviews memory dump         │
              │  → *_learnings.json              │
              └────────────────┬────────────────┘
                               │
              ┌────────────────▼────────────────┐
              │    3. CODE EVOLUTION             │
              │  LLM agent edits brain.py, wiki/ │
              │  → git commit + PR               │
              └────────────────┬────────────────┘
                               │
              ┌────────────────▼────────────────┐
              │    4. SCORE & ESCALATE           │
              │  Track scores, increase steps    │
              │  when performance plateaus       │
              └────────────────┬────────────────┘
                               │
                               └──→ back to step 1
```

## Step 1: Playing a Game

### What Happens

1. **`BasePolicy`** creates a brain and (optionally) an LLM harness
2. Every tick, the agent runs: perceive → decide → execute
3. The harness detects strategic events and calls the LLM when triggers fire
4. LLM directives override the brain's role, target, and strategy

### Key Components

| Component | Base Class | Purpose |
|---|---|---|
| `policy.py` | `BasePolicy` | Game loop wrapper, perceive/execute bridge |
| `brain.py` | `BaseBrain` | Per-tick decision engine |
| `harness.py` | `BaseHarness` | Background LLM thread, event detection, directives |
| `triggers.py` | `BaseEventDetector` | When to consult the LLM |

### Outputs

At game end, the harness writes:
- **`runs/{game}/*_memory.json`** — full game state dump

## Step 2: Post-Game Analysis

An analysis LLM (typically a strong model) reviews the memory dump and produces:

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

Output: **`runs/{game}/*_learnings.json`**

### Cross-Game Learning

Prior games' learnings are injected into the LLM system prompt. A persistent
`cross_game_memory.json` tracks recurring failures, successful strategies,
accumulated rules, and rolling score history.

## Step 3: Code Evolution

The evolution agent receives learnings, source files, and memory, then uses
`str_replace` to make 1-3 surgical edits to the brain and wiki.

### What It Can Edit

Defined per game in `game_config.py`. Typically:

| File Type | Typical Edits |
|---|---|
| `brain.py` | Thresholds, guard clauses, decision conditions |
| `wiki/skills/*.md` | Role-specific guidance |
| `wiki/strategy/*.md` | Strategic guidance, mistake patterns |

Infrastructure files (framework code, providers, evolution code) are excluded.

### Git Workflow

1. `git add` changed policy files
2. `git commit` with game ID and score
3. Push to remote `evolution/{game_id}` branch
4. Create PR via `gh pr create`
5. Auto-merge for tracking
6. Rebase local to stay in sync

## Step 4: Score Tracking & Escalation

`scripts/record_score.py` manages persistent score history. When the last 5
consecutive games all score >= 8/10, the step count increases (longer, harder games):

```
2500 steps → 3500 steps → 4500 steps → ...
```

## File Map

```
cyborg-policy-framework/
├── framework/                  # Game-agnostic infrastructure
│   ├── types.py                # Generic Command, Directive, GameConfig
│   ├── base_brain.py           # ABC: decide(snapshot) → Command
│   ├── base_policy.py          # Abstract perceive → decide → execute loop
│   ├── base_harness.py         # LLM daemon thread, directive mailbox
│   ├── base_triggers.py        # Priority-based event detection
│   ├── base_memory.py          # 3-tier memory (episodic, strategic, working)
│   ├── base_evolution.py       # str_replace tool loop, git workflow
│   ├── base_analysis.py        # Post-game scoring pipeline
│   ├── score_tracker.py        # History, rolling avg, escalation
│   ├── providers.py            # LLM provider abstraction
│   └── wiki/                   # Transferable knowledge base
│       ├── skills/             # Frame parsing, movement, memory, LLM integration
│       ├── strategy/           # Opening, resources, adaptation, mistakes
│       └── mechanics/          # Evolution loop, triggers, memory tiers
│
├── games/                      # Per-game plugins
│   └── new_game/               # Template — copy to create a new game
│       ├── brain.py            # Decision engine stub
│       ├── triggers.py         # Event detection stub
│       ├── harness.py          # LLM harness stub
│       ├── policy.py           # Control loop stub
│       ├── game_config.py      # Evolution config
│       └── wiki/               # Game-specific knowledge
│
├── scripts/                    # Pipeline orchestration
│   ├── continuous_loop.sh      # Outer loop template
│   ├── record_score.py         # Score tracking + escalation
│   ├── policy_manager.py       # Weekly fork/reset lifecycle
│   ├── reporting_agent.py      # Change documentation
│   └── promote_patterns.py     # Pattern promotion pipeline
│
├── runs/                       # Runtime data (gitignored)
│   └── {game}/                 # Per-game: memory dumps, learnings, scores
│
└── docs/
    └── POLICY_GENERATION.md    # This file
```

## Adding a New Game

1. `cp -r games/new_game/ games/your_game/`
2. Implement `brain.py` — your per-tick decision logic
3. Implement `triggers.py` — game events that trigger LLM consultation
4. Implement `harness.py` — LLM context building and directive parsing
5. Implement `policy.py` — bridge to your game engine's observation/action interface
6. Configure `game_config.py` — editable files, system prompts
7. Add `wiki/` markdown — initial game knowledge for the LLM
8. Update `continuous_loop.sh` with your game engine's run command
9. Run: `./scripts/continuous_loop.sh your_game`

## Weekly Policy Lifecycle

```
Week N:
  1. Fork:    python scripts/policy_manager.py fork --game your_game
  2. Play:    ./scripts/continuous_loop.sh your_game
  3. Report:  python scripts/reporting_agent.py --game your_game
  4. Promote: python scripts/promote_patterns.py --game your_game
  5. Reset:   python scripts/policy_manager.py reset --game your_game

Week N+1:
  Base branch now includes promoted patterns from week N.
  Fresh fork starts with improved framework wiki but clean game code.
```

## LLM Provider Configuration

The framework supports multiple LLM providers:

```
bedrock                                      # AWS Bedrock (default)
bedrock:us.anthropic.claude-sonnet-4-20250514   # Bedrock, specific model
openrouter                                   # OpenRouter
openrouter:anthropic/claude-haiku            # OpenRouter, specific model
anthropic                                    # Direct Anthropic API
```

Two separate providers are created:
- **In-game provider** — real-time strategic consultations (~512 max tokens)
- **Analysis provider** — post-game review (~2048 max tokens)

## Transferable Skills

The framework wiki documents skills that transfer across games:

| Skill | What It Teaches |
|---|---|
| Frame Parsing | Turning raw observations into typed snapshot dicts |
| Movement | Pathfinding (A*), frontier exploration, stuck detection |
| Memory Management | Using the three-tier memory system effectively |
| LLM Integration | When to consult, system prompts, context building |
| Role Selection | Role switching patterns, hysteresis, interrupt handling |

These are loaded into the LLM system prompt and evolve alongside the game-specific wiki.
