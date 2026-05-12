---
name: cyborg-policy
description: >-
  Create or modify the game policy (control loop) that subclasses BasePolicy.
  Use when implementing perceive() to parse game engine observations, execute()
  to convert commands to game actions, or wiring brain + harness together.
  Triggers on "policy", "perceive", "execute", "control loop", "game engine bridge".
---

# Implementing a Game Policy

The policy is the outermost wrapper that connects the framework to your game engine.
It implements `perceive()` (raw observation → snapshot dict) and `execute()`
(Command → game action).

## Base Class

Subclass `framework.base_policy.BasePolicy`:

```python
from framework.base_policy import BasePolicy
from framework.base_brain import BaseBrain
from framework.base_harness import BaseHarness
from framework.types import Command, GameConfig

class MyGamePolicy(BasePolicy):
    def create_brain(self) -> BaseBrain:
        """Instantiate your game's brain."""

    def create_harness(self) -> BaseHarness | None:
        """Instantiate your game's harness (None = no LLM)."""

    def perceive(self, raw_observation) -> dict:
        """Convert engine observation to snapshot dict."""

    def execute(self, command: Command):
        """Convert a Command into the engine's action format."""
```

## perceive() — Observation Parsing

This is where you translate your game engine's raw output into a typed dict:

```python
def perceive(self, raw_observation) -> dict:
    grid = raw_observation["grid"]
    return {
        "tick": raw_observation["tick"],
        "position": (raw_observation["row"], raw_observation["col"]),
        "hp": raw_observation["health"],
        "resources": self._parse_resources(grid),
        "visible_entities": self._parse_entities(grid),
        "score": raw_observation.get("score", 0),
        "phase": self._detect_phase(raw_observation),
    }
```

Rules:
- Parse EVERY tick (brain expects a fresh snapshot)
- Keep parsing stateless — no frame-to-frame memory here
- Handle unknown/fog tokens explicitly
- Include `tick` so the brain knows when this state is from

## execute() — Action Translation

Convert framework Commands into your engine's action format:

```python
def execute(self, command: Command):
    if command.kind == CommandKind.NAVIGATE_TO and command.target:
        return self._pathfind_step(command.target)
    elif command.kind == CommandKind.GATHER:
        return "harvest"
    elif command.kind == CommandKind.ATTACK:
        return "attack"
    elif command.kind == CommandKind.FLEE:
        return self._pathfind_step(self.spawn_pos)
    return "noop"
```

## The step() Loop (provided by BasePolicy)

You get `step()` for free — it runs: `perceive → decide → execute`:

```python
action = policy.step(raw_observation)
# Returns whatever execute() returns
```

The harness (if present) runs in a background thread, processing snapshots
asynchronously and issuing directives to the brain.

## GameConfig

Pass config at construction:

```python
config = GameConfig(
    game_id="abc123",
    max_steps=2500,
    seed=42,
    run_dir="runs/my_game",
)
policy = MyGamePolicy(agent_id=0, config=config, provider=llm)
```

## Wiki References

- `framework/wiki/skills/frame-parsing.md` — observation → snapshot patterns
- `framework/wiki/skills/movement.md` — pathfinding in execute()
