"""Richardborg: Crewborg with meeting memory summaries for Crewrift."""

from __future__ import annotations

from players.crewrift.crewborg.agent_tracking import update_agent_tracking
from players.crewrift.crewborg.action import resolve_action
from players.crewrift.crewborg.events import CrewborgEventTracer
from players.crewrift.crewborg.map import MapData, load_croatoan_map
from players.crewrift.crewborg.modes import (
    EvadeMode,
    FleeMode,
    HuntMode,
    IdleMode,
    NormalMode,
    PretendMode,
    ReportBodyMode,
    SearchMode,
)
from players.crewrift.crewborg.strategy import (
    RuleBasedStrategy,
    update_event_log,
    update_suspicion,
)
from players.crewrift.crewborg.types import (
    ActionState,
    Belief,
    Command,
    Intent,
    Observation,
    Percept,
    perceive,
    update_belief,
)
from players.crewrift.richardborg.modes import AttendMeetingMode
from players.player_sdk import (
    AgentRuntime,
    MetricsSink,
    ModeDirective,
    ModeRegistry,
    SynchronousStrategyRunner,
    TraceSink,
)

__all__ = ["build_runtime"]


def build_runtime(
    *,
    trace_sink: TraceSink | None = None,
    metrics_sink: MetricsSink | None = None,
    map_data: MapData | None = None,
) -> AgentRuntime[Observation, Percept, Belief, ActionState, Intent, Command]:
    registry: ModeRegistry[Belief, ActionState, Intent] = ModeRegistry()
    registry.register(IdleMode)
    registry.register(NormalMode)
    registry.register(AttendMeetingMode)
    registry.register(ReportBodyMode)
    registry.register(FleeMode)
    registry.register(EvadeMode)
    registry.register(HuntMode)
    registry.register(PretendMode)
    registry.register(SearchMode)

    if map_data is None:
        map_data = load_croatoan_map()

    def fold_belief(belief: Belief, percept: Percept) -> None:
        update_belief(belief, percept)
        update_agent_tracking(belief)
        update_event_log(belief)
        update_suspicion(belief)

    return AgentRuntime(
        belief=Belief(map=map_data),
        action_state=ActionState(),
        perceive=perceive,
        update_belief=fold_belief,
        resolve_action=resolve_action,
        mode_registry=registry,
        default_directive=ModeDirective(
            mode="idle", source="default", reason="richardborg default idle"
        ),
        strategy_runner=SynchronousStrategyRunner(
            RuleBasedStrategy(),
            trace_sink=trace_sink,
            metrics_sink=metrics_sink,
        ),
        on_step_complete=CrewborgEventTracer(),
        trace_sink=trace_sink,
        metrics_sink=metrics_sink,
    )
