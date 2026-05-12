# Python Framework Quickstart

The reusable implementation lives in
[`cogames_agents.cyborg`](/Users/jamesboggs/coding/metta/cogames-agents/src/cogames_agents/cyborg).

Use it when building a new game agent with the Cyborg pattern:

```text
perceive -> update belief -> mode decide -> action resolve
                     ^
                     |
        strategy snapshot -> ModeDirective
```

## Main Pieces

- `ModeParams`: Pydantic base class for typed mode parameters.
- `ModeDirective`: mode name, typed params, source, TTL, reason, metadata.
- `Mode`: deterministic symbolic local policy.
- `ModeRegistry`: validates directives and instantiates modes.
- `AgentRuntime`: non-blocking per-tick inner-loop orchestrator.
- `SynchronousStrategyRunner`: deterministic rule/LLM-adapter runner for tests
  and simple agents.
- `ThreadedStrategyRunner`: background latest-snapshot strategy runner.
- `ManualStrategyRunner`: test harness runner where callers publish directives.
- `ListTraceSink`: in-memory trace sink for tests and examples.

## Minimal Agent Shape

```python
from dataclasses import dataclass

from cogames_agents.cyborg import (
    ActionCommand,
    ActionIntent,
    AgentRuntime,
    EmptyModeParams,
    Mode,
    ModeDirective,
    ModeParams,
    ModeRegistry,
    SynchronousStrategyRunner,
)


@dataclass
class Belief:
    position: int = 0
    target: int = 0


@dataclass
class ActionState:
    last_action: str = "noop"


class MoveParams(ModeParams):
    target: int


class IdleMode(Mode[Belief, ActionState, ActionIntent]):
    name = "idle"
    params_type = EmptyModeParams

    def decide(self, belief: Belief, action_state: ActionState) -> ActionIntent:
        return ActionIntent()


class MoveMode(Mode[Belief, ActionState, ActionIntent]):
    name = "move"
    params_type = MoveParams

    def decide(self, belief: Belief, action_state: ActionState) -> ActionIntent:
        params = self.params
        assert isinstance(params, MoveParams)
        return ActionIntent(semantic="move", target=(params.target, 0))
```

The game supplies three functions:

- `perceive(observation, tick) -> percept`
- `update_belief(belief, percept) -> None`
- `resolve_action(intent, belief, action_state) -> command`

The strategy supplies directives:

```python
class Strategy:
    def decide(self, snapshot):
        if snapshot.belief.position == snapshot.belief.target:
            return ModeDirective(mode="idle")
        return ModeDirective(
            mode="move",
            params=MoveParams(target=snapshot.belief.target),
            ttl_ticks=120,
        )
```

See
[`examples/toy_grid_agent.py`](/Users/jamesboggs/coding/metta/cogames-agents/coborg_framework/examples/toy_grid_agent.py)
for a complete runnable example.

For the full API-level breakdown of runtime, directives, modes, strategy
runners, reflexes, fallbacks, and tracing, see the Framework Reference section
in
[`README.md`](/Users/jamesboggs/coding/metta/cogames-agents/coborg_framework/README.md).

## Design Rules

- Keep observations and raw frames out of belief.
- Make belief the only interface to strategy.
- Keep mode params typed.
- Let modes emit symbolic intents, not transport actions.
- Put movement, cursor timing, chat buffers, and UI mechanics in the action
  resolver.
- Use reflexes for urgent events that cannot wait for the strategy loop.
- Use TTLs and default directives so the agent stays live when strategy stalls.
- Validate directives in `ModeRegistry` before installing them.
- Trace every boundary while developing a new game agent.
