---
name: cyborg-harness
description: >-
  Create or modify an LLM harness that subclasses BaseHarness. Use when
  implementing LLM context building, directive parsing, system prompts,
  or post-game analysis hooks for a game plugin. Triggers on "harness",
  "LLM context", "system prompt", "directive", "narrator", "advisor".
---

# Implementing a Game Harness

The harness is a background daemon thread that monitors the game and consults
the LLM when triggers fire. It builds context, calls the LLM, and parses
the response into a Directive the brain can follow.

## Base Class

Subclass `framework.base_harness.BaseHarness` and implement four methods:

```python
from framework.base_harness import BaseHarness
from framework.base_memory import GameMemory
from framework.types import Directive

class MyGameHarness(BaseHarness):
    def parse_directive(self, data: dict, tick: int) -> Directive:
        """Parse LLM JSON response into a Directive."""

    def build_context(self, memory: GameMemory, trigger: str,
                      operator_notes: list[str] | None = None) -> str:
        """Build the user message for the LLM consultation."""

    def get_system_prompt(self, prior_learnings: str = "") -> str:
        """Return the LLM system prompt."""

    def _run_post_game_background(self, dump, filepath, trigger):
        """Called at game end for analysis (optional)."""
```

## parse_directive()

The LLM responds with JSON. Validate and convert it:

```python
def parse_directive(self, data: dict, tick: int) -> Directive:
    role = data.get("role", "default")
    if role not in VALID_ROLES:
        role = "default"
    return Directive(
        role=role,
        command=data.get("command"),
        target=self._parse_coord(data.get("target")),
        reasoning=data.get("reasoning", ""),
        issued_tick=tick,
        expires_tick=tick + 300,
    )
```

## build_context()

Structure the context for scannability:

```
[TRIGGER: {trigger_name}]
[CURRENT STATE]
  Position, HP, resources, score...
[RECENT EVENTS]
  Last 10-15 episodic events
[STRATEGIC FACTS]
  Active facts from strategic memory
[ACTIVE DIRECTIVE]
  Current directive, age, status
[PERFORMANCE]
  Rates and trends from perf windows
```

Tips:
- Front-load the most important info (LLMs attend more to the start)
- Truncate long lists (last 15 events, not all 500)
- Include deltas: "resources +20 since last consult"

## get_system_prompt()

Structure:

```
1. Identity: "You are a strategic advisor for a {game} agent"
2. Game rules: compact mechanics summary
3. Available actions: roles and commands the LLM can issue
4. Response format: strict JSON schema with examples
5. Cross-game learnings: injected via prior_learnings param
6. Wiki knowledge: loaded from game's wiki/ directory
```

Keep under 4000 tokens. Put the JSON format last (closest to generation).

## Constructor

```python
harness = MyGameHarness(
    provider=llm_provider,
    analysis_provider=opus_provider,  # optional, for post-game
    event_detector=my_trigger_detector,
    game_name="my_game",
    game_id="abc123",
    max_steps=2500,
    seed=42,
    runs_dir="runs/my_game",
)
```

## Wiki References

- `framework/wiki/skills/llm-integration.md` — consultation model, token budgets
- `framework/wiki/skills/memory-management.md` — what to include from each tier
- `framework/wiki/mechanics/memory-tiers.md` — memory tier technical reference
