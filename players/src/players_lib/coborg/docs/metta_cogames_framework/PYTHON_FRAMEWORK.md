# Python Framework Quickstart

The reusable implementation lives in
[`src/players_lib/coborg`](../..).

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
- `SharedMemory` and `BeliefSnapshot`: lock-protected live belief/action-state
  access for strategy code.
- `Mode`: deterministic symbolic local policy.
- `ModeDecision`: optional mode return wrapper for completion or stalling.
- `ModeRegistry`: validates directives and instantiates modes.
- `AgentRuntime`: non-blocking per-tick inner-loop orchestrator.
- `SynchronousStrategyRunner`: deterministic rule/LLM-adapter runner for tests
  and simple agents.
- `ThreadedStrategyRunner`: background latest-snapshot strategy runner for
  blocking strategy clients.
- `AsyncStrategyRunner`: event-loop runner for async LLM clients; construct it
  inside the running loop or pass the loop explicitly.
- `ManualStrategyRunner`: test harness runner where callers publish directives.
- `ListTraceSink`: in-memory trace sink for tests and examples.
- `ListMetricsSink`: in-memory counter/histogram/gauge sink for tests.

## Minimal Agent Shape

```python
from dataclasses import dataclass

from players_lib.coborg import (
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
        with snapshot.read() as memory:
            position = memory.belief.position
            target = memory.belief.target
        if position == target:
            return ModeDirective(mode="idle")
        return ModeDirective(
            mode="move",
            params=MoveParams(target=target),
            ttl_ticks=120,
        )
```

See
[`examples/toy_grid_agent.py`](examples/toy_grid_agent.py)
for a complete runnable example.

For the full API-level breakdown of runtime, directives, modes, strategy
runners, reflexes, fallbacks, and tracing, see the Framework Reference section
in
[`README.md`](README.md).

## Design Rules

- Keep observations and raw frames out of belief.
- Make belief the only interface to strategy.
- Keep mode params typed.
- Let modes emit symbolic intents, not transport actions.
- Put movement, cursor timing, chat buffers, and UI mechanics in the action
  resolver.
- Keep `snapshot.read()`/`snapshot.write()` scopes short; never hold the shared
  memory lock across an LLM or network call.
- Use reflexes for urgent events that cannot wait for the strategy loop.
- Use TTLs and default directives so the agent stays live when strategy stalls.
- Return `ModeDecision.complete(...)` or `ModeDecision.stalled(...)` when a mode
  has finished or cannot make progress.
- Validate directives in `ModeRegistry` before installing them.
- Trace every boundary and emit metrics for mode runs, fallbacks, strategy
  latency, directive age, and step latency while developing a new game agent.
