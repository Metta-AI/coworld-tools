from __future__ import annotations

import asyncio

from players.player_sdk import (
    ActionCommand,
    ActionIntent,
    AgentRuntime,
    AsyncStrategyRunner,
    EmptyModeParams,
    ListMetricsSink,
    ListTraceSink,
    ManualStrategyRunner,
    Mode,
    ModeDecision,
    ModeDirective,
    ModeParams,
    ModeRegistry,
    OverwriteBuffer,
    ReflexRule,
    RuntimeContext,
    StepContext,
    StrategyResult,
    SynchronousStrategyRunner,
)
from players.player_sdk.types import BeliefSnapshot


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
        with snapshot.read() as memory:
            target = memory.belief.target
        return ModeDirective(
            mode="move",
            params=MoveParams(target=target),
            ttl_ticks=5,
            source="strategy",
        )


class InferenceStrategy:
    def decide(self, snapshot: BeliefSnapshot[Belief, ActionState]) -> StrategyResult:
        with snapshot.read() as memory:
            del memory
            return StrategyResult(inferences={"tick_seen": snapshot.tick})


class SharedMemoryStrategy:
    def __init__(self) -> None:
        self.seen_belief: Belief | None = None

    def decide(self, snapshot: BeliefSnapshot[Belief, ActionState]) -> StrategyResult | None:
        with snapshot.write() as memory:
            self.seen_belief = memory.belief
            memory.belief.inferences["outer_tick"] = snapshot.tick
        return None


class CompleteWhenArrivedMode(Mode[Belief, ActionState, ActionIntent]):
    name = "complete_when_arrived"
    params_type = MoveParams

    def decide(self, belief: Belief, action_state: ActionState) -> ModeDecision[ActionIntent]:
        del action_state
        params = self.params
        assert isinstance(params, MoveParams)
        if belief.position == params.target:
            return ModeDecision.complete(ActionIntent(reason="arrived"), reason="target reached")
        return ModeDecision.running(ActionIntent(semantic="move", target=(params.target, 0)))


class EmitMode(Mode[Belief, ActionState, ActionIntent]):
    name = "emit"
    params_type = EmptyModeParams

    def decide(self, belief: Belief, action_state: ActionState) -> ActionIntent:
        del belief, action_state
        self.emit.event("attack_attempted", {"target": "blue"})
        self.emit.event("domain.attack_landed", {"target": "blue"})
        self.emit.counter("attack_attempts", tags={"target": "blue"})
        self.emit.gauge("threat_level", 2.0, tags={"phase": "combat"})
        self.emit.histogram("decision_ms", 4.5)
        return ActionIntent(semantic="emit")


class PostStepMode(Mode[Belief, ActionState, ActionIntent]):
    name = "post_step"
    params_type = EmptyModeParams

    def decide(self, belief: Belief, action_state: ActionState) -> ActionIntent:
        del action_state
        belief.inferences["post_decide"] = "available"
        return ActionIntent(semantic="flee", reason="post-step context")


class AsyncMoveStrategy:
    async def decide(self, snapshot: BeliefSnapshot[Belief, ActionState]) -> ModeDirective:
        await asyncio.sleep(0)
        with snapshot.read() as memory:
            target = memory.belief.target
        return ModeDirective(
            mode="move",
            params=MoveParams(target=target),
            ttl_ticks=5,
            source="async",
        )


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
    result.register(CompleteWhenArrivedMode)
    result.register(EmitMode)
    result.register(PostStepMode)
    return result


def runtime(
    *,
    strategy_runner=None,
    reflexes=(),
    trace=None,
    metrics=None,
    apply_inferences=None,
    on_step_complete=None,
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
        metrics_sink=metrics,
        apply_inferences=apply_inferences,
        on_step_complete=on_step_complete,
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

    agent = runtime(reflexes=(ReflexRule(name="danger", priority=100, callback=danger_reflex),))

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


def test_strategy_uses_shared_thread_safe_memory_without_copying() -> None:
    strategy = SharedMemoryStrategy()
    agent = runtime(strategy_runner=SynchronousStrategyRunner(strategy))

    agent.step(Observation(position=0, target=2))

    assert strategy.seen_belief is agent.belief
    assert agent.belief.inferences == {"outer_tick": 1}


def test_async_strategy_runner_uses_existing_event_loop() -> None:
    async def scenario() -> None:
        agent = runtime(strategy_runner=AsyncStrategyRunner(AsyncMoveStrategy()))

        first = agent.step(Observation(position=0, target=2))
        await asyncio.sleep(0.01)
        second = agent.step(Observation(position=0, target=2))

        assert first.action == "noop"
        assert second.action == "right"
        assert agent.active_mode_name == "move"
        agent.close()

    asyncio.run(scenario())


def test_mode_decision_completion_traces_and_falls_back() -> None:
    trace = ListTraceSink()
    manual: ManualStrategyRunner[Belief, ActionState] = ManualStrategyRunner()
    agent = runtime(strategy_runner=manual, trace=trace)
    manual.publish(
        ModeDirective(
            mode="complete_when_arrived",
            params=MoveParams(target=0),
            source="manual",
        )
    )

    command = agent.step(Observation(position=0, target=0))

    assert command.action == "noop"
    assert agent.active_mode_name == "idle"
    completed = [event for event in trace.events if event.name == "mode_completed"]
    assert completed
    assert completed[0].data["reason"] == "target reached"


def test_mode_emits_domain_trace_and_metrics() -> None:
    trace = ListTraceSink()
    metrics = ListMetricsSink()
    manual: ManualStrategyRunner[Belief, ActionState] = ManualStrategyRunner()
    agent = runtime(strategy_runner=manual, trace=trace, metrics=metrics)
    manual.publish(ModeDirective(mode="emit", source="manual"))

    agent.step(Observation())

    domain_events = [event for event in trace.events if event.name == "domain.attack_attempted"]
    assert domain_events
    assert domain_events[0].tick == 1
    assert domain_events[0].data == {"target": "blue"}
    already_prefixed = [event for event in trace.events if event.name == "domain.attack_landed"]
    assert already_prefixed
    assert already_prefixed[0].tick == 1

    domain_metrics = [sample for sample in metrics.samples if sample.name == "domain.attack_attempts"]
    assert domain_metrics
    assert domain_metrics[0].value == 1.0
    assert domain_metrics[0].tags == {"target": "blue"}

    gauges = [sample for sample in metrics.samples if sample.name == "domain.threat_level"]
    assert gauges
    assert gauges[0].kind == "gauge"
    assert gauges[0].value == 2.0
    assert gauges[0].tags == {"phase": "combat"}

    histograms = [sample for sample in metrics.samples if sample.name == "domain.decision_ms"]
    assert histograms
    assert histograms[0].kind == "histogram"
    assert histograms[0].value == 4.5
    assert histograms[0].tags == {}


def test_mode_emitter_defaults_to_noop_outside_runtime() -> None:
    mode = EmitMode()

    intent = mode.decide(Belief(), ActionState())

    assert intent.semantic == "emit"


def test_on_step_complete_receives_resolved_end_of_tick_context() -> None:
    contexts: list[StepContext[Belief, ActionState, ActionIntent, ActionCommand]] = []
    trace = ListTraceSink()
    manual: ManualStrategyRunner[Belief, ActionState] = ManualStrategyRunner()
    agent = runtime(
        strategy_runner=manual,
        trace=trace,
        on_step_complete=contexts.append,
    )
    manual.publish(ModeDirective(mode="post_step", source="manual"))

    command = agent.step(Observation())

    assert command.action == "flee"
    assert len(contexts) == 1
    context = contexts[0]
    assert context.tick == 1
    assert context.intent.semantic == "flee"
    assert context.command.action == "flee"
    assert context.belief.inferences["post_decide"] == "available"
    assert context.action_state.last_action == "flee"
    assert context.active_mode_name == "post_step"

    context.emit.event("step_observed")
    observed = [event for event in trace.events if event.name == "domain.step_observed"]
    assert observed
    assert observed[0].tick == 1


def test_on_step_complete_completion_tick_sees_post_fallback_state() -> None:
    contexts: list[StepContext[Belief, ActionState, ActionIntent, ActionCommand]] = []
    manual: ManualStrategyRunner[Belief, ActionState] = ManualStrategyRunner()
    agent = runtime(strategy_runner=manual, on_step_complete=contexts.append)
    manual.publish(
        ModeDirective(
            mode="complete_when_arrived",
            params=MoveParams(target=0),
            source="manual",
        )
    )

    command = agent.step(Observation(position=0, target=0))

    assert command.action == "noop"
    assert agent.active_mode_name == "idle"
    assert len(contexts) == 1
    context = contexts[0]
    assert context.active_mode_name == "complete_when_arrived"
    assert context.intent.reason == "arrived"
    assert context.command.action == "noop"
    assert context.action_state.enters[-1] == "idle"
    assert context.action_state is agent.action_state
    assert context.belief is agent.belief


def test_reflex_priority_wins_and_records_evaluation_order() -> None:
    def low_priority_reflex(
        context: RuntimeContext[Belief, ActionState],
    ) -> ModeDirective | None:
        if context.belief.danger:
            return ModeDirective(mode="move", params=MoveParams(target=9), source="low")
        return None

    def high_priority_reflex(
        context: RuntimeContext[Belief, ActionState],
    ) -> ModeDirective | None:
        if context.belief.danger:
            return ModeDirective(mode="flee", source="high")
        return None

    trace = ListTraceSink()
    agent = runtime(
        reflexes=(
            ReflexRule(name="low", priority=10, callback=low_priority_reflex),
            ReflexRule(name="high", priority=100, callback=high_priority_reflex),
        ),
        trace=trace,
    )

    command = agent.step(Observation(position=0, target=0, danger=True))

    assert command.action == "flee"
    assert agent.active_mode_name == "flee"
    evaluations = [event for event in trace.events if event.name == "reflex_evaluated"]
    assert evaluations
    checks = evaluations[0].data["checks"]
    assert [check["name"] for check in checks] == ["high"]
    assert evaluations[0].data["winner"] == "high"


def test_runtime_emits_metrics_for_modes_strategy_and_steps() -> None:
    metrics = ListMetricsSink()
    agent = runtime(
        strategy_runner=SynchronousStrategyRunner(MoveStrategy(), metrics_sink=metrics),
        metrics=metrics,
    )

    agent.step(Observation(position=0, target=2))

    names = [sample.name for sample in metrics.samples]
    assert "cyborg.mode.ran" in names
    assert "cyborg.step.latency_ms" in names
    assert "cyborg.strategy.observe_ms" in names
    assert "cyborg.strategy.decide_ms" in names
    assert "cyborg.mode.duration_ticks" in names


def test_overwrite_buffer_keeps_only_latest_value() -> None:
    buffer: OverwriteBuffer[int] = OverwriteBuffer()

    buffer.publish(1)
    buffer.publish(2)

    assert buffer.take() == 2
    assert buffer.take() is None
