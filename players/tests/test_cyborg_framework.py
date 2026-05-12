from __future__ import annotations

from cogames_agents.cyborg import (
    ActionCommand,
    ActionIntent,
    AgentRuntime,
    EmptyModeParams,
    ListTraceSink,
    ManualStrategyRunner,
    Mode,
    ModeDirective,
    ModeParams,
    ModeRegistry,
    OverwriteBuffer,
    RuntimeContext,
    StrategyResult,
    SynchronousStrategyRunner,
)
from cogames_agents.cyborg.types import BeliefSnapshot


class Observation:
    def __init__(
        self,
        position: int = 0,
        target: int = 0,
        danger: bool = False,
    ) -> None:
        self.position = position
        self.target = target
        self.danger = danger


class Percept:
    def __init__(self, position: int, target: int, danger: bool, tick: int) -> None:
        self.position = position
        self.target = target
        self.danger = danger
        self.tick = tick


class Belief:
    def __init__(self) -> None:
        self.position = 0
        self.target = 0
        self.danger = False
        self.inferences: dict = {}


class ActionState:
    def __init__(self) -> None:
        self.last_action = "noop"
        self.enters: list[str] = []
        self.exits: list[str] = []


class MoveParams(ModeParams):
    target: int


class IdleMode(Mode[Belief, ActionState, ActionIntent]):
    name = "idle"
    params_type = EmptyModeParams

    def on_enter(self, belief: Belief, action_state: ActionState) -> None:
        del belief
        action_state.enters.append("idle")

    def on_exit(
        self,
        belief: Belief,
        action_state: ActionState,
        next_directive: ModeDirective,
    ) -> None:
        del belief, next_directive
        action_state.exits.append("idle")

    def decide(self, belief: Belief, action_state: ActionState) -> ActionIntent:
        del belief, action_state
        return ActionIntent(reason="idle")


class MoveMode(Mode[Belief, ActionState, ActionIntent]):
    name = "move"
    params_type = MoveParams

    def __init__(self, params: ModeParams | None = None) -> None:
        super().__init__(params)
        self.decisions = 0

    def on_enter(self, belief: Belief, action_state: ActionState) -> None:
        del belief
        action_state.enters.append("move")

    def on_exit(
        self,
        belief: Belief,
        action_state: ActionState,
        next_directive: ModeDirective,
    ) -> None:
        del belief, next_directive
        action_state.exits.append("move")

    def decide(self, belief: Belief, action_state: ActionState) -> ActionIntent:
        del belief, action_state
        self.decisions += 1
        params = self.params
        assert isinstance(params, MoveParams)
        return ActionIntent(semantic="move", target=(params.target, 0))


class FleeMode(Mode[Belief, ActionState, ActionIntent]):
    name = "flee"
    params_type = EmptyModeParams

    def decide(self, belief: Belief, action_state: ActionState) -> ActionIntent:
        del belief, action_state
        return ActionIntent(semantic="flee")


class MoveStrategy:
    def decide(self, snapshot: BeliefSnapshot[Belief, ActionState]) -> ModeDirective:
        return ModeDirective(
            mode="move",
            params=MoveParams(target=snapshot.belief.target),
            ttl_ticks=5,
            source="strategy",
        )


class InferenceStrategy:
    def decide(self, snapshot: BeliefSnapshot[Belief, ActionState]) -> StrategyResult:
        return StrategyResult(inferences={"tick_seen": snapshot.tick})


def perceive(observation: Observation, tick: int) -> Percept:
    return Percept(
        position=observation.position,
        target=observation.target,
        danger=observation.danger,
        tick=tick,
    )


def update_belief(belief: Belief, percept: Percept) -> None:
    belief.position = percept.position
    belief.target = percept.target
    belief.danger = percept.danger


def resolve_action(intent: ActionIntent, belief: Belief, action_state: ActionState) -> ActionCommand:
    if intent.semantic == "flee":
        action_state.last_action = "flee"
        return ActionCommand(action="flee")
    if intent.semantic == "move" and intent.target is not None:
        target = intent.target[0]
        if belief.position < target:
            action_state.last_action = "right"
            return ActionCommand(action="right")
        if belief.position > target:
            action_state.last_action = "left"
            return ActionCommand(action="left")
    action_state.last_action = "noop"
    return ActionCommand()


def registry() -> ModeRegistry[Belief, ActionState, ActionIntent]:
    result: ModeRegistry[Belief, ActionState, ActionIntent] = ModeRegistry()
    result.register(IdleMode)
    result.register(MoveMode)
    result.register(FleeMode)
    return result


def runtime(
    *,
    strategy_runner=None,
    reflexes=(),
    trace=None,
    apply_inferences=None,
) -> AgentRuntime[Observation, Percept, Belief, ActionState, ActionIntent, ActionCommand]:
    return AgentRuntime(
        belief=Belief(),
        action_state=ActionState(),
        perceive=perceive,
        update_belief=update_belief,
        resolve_action=resolve_action,
        mode_registry=registry(),
        default_directive=ModeDirective(mode="idle", source="default"),
        strategy_runner=strategy_runner,
        reflexes=reflexes,
        trace_sink=trace,
        apply_inferences=apply_inferences,
    )


def test_runtime_installs_strategy_directive_and_resolves_action() -> None:
    trace = ListTraceSink()
    agent = runtime(
        strategy_runner=SynchronousStrategyRunner(MoveStrategy()),
        trace=trace,
    )

    command = agent.step(Observation(position=0, target=2))

    assert command.action == "right"
    assert agent.active_mode_name == "move"
    assert "snapshot_submitted" in trace.names()
    assert "mode_entered" in trace.names()


def test_reaffirmed_directive_preserves_mode_instance_state() -> None:
    agent = runtime(strategy_runner=SynchronousStrategyRunner(MoveStrategy()))

    agent.step(Observation(position=0, target=2))
    first_mode = agent.active_mode
    assert isinstance(first_mode, MoveMode)
    agent.step(Observation(position=1, target=2))

    assert agent.active_mode is first_mode
    assert first_mode.decisions == 2
    assert agent.action_state.enters.count("move") == 1


def test_ttl_expiry_installs_default_directive() -> None:
    manual: ManualStrategyRunner[Belief, ActionState] = ManualStrategyRunner()
    agent = runtime(strategy_runner=manual)
    manual.publish(
        ModeDirective(
            mode="move",
            params=MoveParams(target=3),
            ttl_ticks=1,
            source="manual",
        )
    )

    first = agent.step(Observation(position=0, target=3))
    second = agent.step(Observation(position=1, target=3))

    assert first.action == "right"
    assert second.action == "noop"
    assert agent.active_mode_name == "idle"


def test_reflex_overrides_current_mode_for_urgent_state() -> None:
    def danger_reflex(
        context: RuntimeContext[Belief, ActionState],
    ) -> ModeDirective | None:
        if context.belief.danger:
            return ModeDirective(mode="flee", source="reflex")
        return None

    agent = runtime(reflexes=(danger_reflex,))

    command = agent.step(Observation(position=0, target=0, danger=True))

    assert command.action == "flee"
    assert agent.active_mode_name == "flee"


def test_invalid_directive_is_rejected_without_switching_modes() -> None:
    trace = ListTraceSink()
    manual: ManualStrategyRunner[Belief, ActionState] = ManualStrategyRunner()
    agent = runtime(strategy_runner=manual, trace=trace)
    manual.publish(ModeDirective(mode="move", source="manual"))

    command = agent.step(Observation(position=0, target=3))

    assert command.action == "noop"
    assert agent.active_mode_name == "idle"
    rejected = [event for event in trace.events if event.name == "directive_rejected"]
    assert rejected
    assert "expected params MoveParams" in rejected[0].data["error"]


def test_strategy_inferences_can_be_applied_to_belief() -> None:
    def apply_inferences(belief: Belief, inferences: dict) -> None:
        belief.inferences.update(inferences)

    agent = runtime(
        strategy_runner=SynchronousStrategyRunner(InferenceStrategy()),
        apply_inferences=apply_inferences,
    )

    agent.step(Observation())

    assert agent.belief.inferences == {"tick_seen": 1}
    assert agent.latest_inferences == {"tick_seen": 1}


def test_overwrite_buffer_keeps_only_latest_value() -> None:
    buffer: OverwriteBuffer[int] = OverwriteBuffer()

    buffer.publish(1)
    buffer.publish(2)

    assert buffer.take() == 2
    assert buffer.take() is None
