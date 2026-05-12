---
name: cyborg-brain
description: >-
  Create or modify a game brain (decision engine) that subclasses BaseBrain.
  Use when implementing per-tick decision logic, adding roles, tuning thresholds,
  or writing the decide() method for a new game plugin. Triggers on "brain",
  "decide", "role", "threshold", "heuristic", "decision logic".
---

# Implementing a Game Brain

The brain is the per-tick decision engine. It runs every game tick (fast, deterministic)
and returns a `Command` telling the agent what to do.

## Base Class

Subclass `framework.base_brain.BaseBrain` and implement four methods:

```python
from framework.base_brain import BaseBrain
from framework.types import Command, CommandKind, Directive, GameConfig

class MyGameBrain(BaseBrain):
    def prepare(self, config: GameConfig) -> None:
        """Called once at game start. Store config, init state."""

    def decide(self, snapshot: dict) -> Command:
        """Called every tick. Return a Command."""

    def apply_directive(self, directive: Directive) -> None:
        """Called when the LLM issues a new directive."""

    def debug_state(self) -> dict:
        """Return current internal state for logging."""
```

## Command Types

Return one of these from `decide()`:

| CommandKind | When to use |
|---|---|
| `NAVIGATE_TO` | Move toward a target `(row, col)` |
| `EXPLORE` | Discover unknown map areas |
| `GATHER` | Collect a resource |
| `BUILD` | Construct something |
| `ATTACK` | Engage an opponent |
| `DEFEND` | Hold a position |
| `FLEE` | Retreat from danger |
| `INTERACT` | Generic interaction (trade, talk, use) |
| `IDLE` | Do nothing this tick |

## Role-Based Decision Pattern

Most brains use a role switch:

```python
def decide(self, snapshot: dict) -> Command:
    self._update_role(snapshot)  # scripted role check
    if self.role == "gatherer":
        return self._decide_gatherer(snapshot)
    elif self.role == "builder":
        return self._decide_builder(snapshot)
    elif self.role == "attacker":
        return self._decide_attacker(snapshot)
    return Command(kind=CommandKind.EXPLORE, reason="default")
```

## Key Patterns

1. **Scripted role check runs BEFORE the LLM** — handles urgent transitions
   (low HP → flee, enemy nearby → defend) without waiting for LLM latency.

2. **Hysteresis** — don't switch roles unless you've been in the current role
   for at least N ticks. Prevents oscillation.

3. **Thresholds as constants at the top of the file** — makes them easy for
   the evolution agent to find and tune.

4. **Guard clauses first** — check for death, stuck, out-of-bounds before
   running role-specific logic.

## Template

See `games/new_game/brain.py` for the starter template.

## Wiki References

- `framework/wiki/skills/role-selection.md` — role switching patterns
- `framework/wiki/skills/movement.md` — pathfinding and navigation
- `framework/wiki/strategy/opening.md` — early-game decision structure
