"""Crewborg — a Player-SDK agent that plays Crewrift.

``build_runtime`` assembles the ``AgentRuntime`` from crewborg's six type
parameters, three pure functions, modes, and the rule-based strategy. See
``design.md`` for the full architecture and ``AGENTS.md`` for orientation.
"""

from __future__ import annotations

from players.crewrift.crewborg.action import resolve_action
from players.crewrift.crewborg.events import CrewborgEventTracer
from players.crewrift.crewborg.map import MapData, load_croatoan_map
from players.crewrift.crewborg.modes import (
    AttendMeetingMode,
    EvadeMode,
    FleeMode,
    HuntMode,
    IdleMode,
    NormalMode,
    PretendMode,
    ReportBodyMode,
)
from players.crewrift.crewborg.strategy import RuleBasedStrategy, update_suspicion
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
    """Assemble the crewborg ``AgentRuntime``.

    The inner loop runs ``perceive -> update_belief (+ suspicion) -> mode.decide
    -> resolve_action`` each tick; the rule-based strategy publishes mode
    directives via ``SynchronousStrategyRunner``. Suspicion scoring is folded into
    belief right after perception so the strategy snapshot sees a current
    ``believed_imposters`` (design §10.1). The static map is baked once here
    (design §6) — ``map_data`` overrides the vendored ``croatoan`` bake (tests).
    Registers all modes: idle / normal / attend_meeting / report_body / flee
    (crewmate) and hunt / pretend / evade (imposter). A ``CrewborgEventTracer``
    is wired as the runtime's ``on_step_complete`` hook so crewborg emits its
    ``domain.*`` trace events (phase / sighting / objective / kill / vote)
    through the configured sinks (design §11).
    """

    registry: ModeRegistry[Belief, ActionState, Intent] = ModeRegistry()
    registry.register(IdleMode)
    registry.register(NormalMode)
    registry.register(AttendMeetingMode)
    registry.register(ReportBodyMode)
    registry.register(FleeMode)
    registry.register(HuntMode)
    registry.register(PretendMode)
    registry.register(EvadeMode)

    if map_data is None:
        map_data = load_croatoan_map()

    def fold_belief(belief: Belief, percept: Percept) -> None:
        """Fast-loop belief update: perception folding then suspicion scoring."""

        update_belief(belief, percept)
        update_suspicion(belief)

    return AgentRuntime(
        belief=Belief(map=map_data),
        action_state=ActionState(),
        perceive=perceive,
        update_belief=fold_belief,
        resolve_action=resolve_action,
        mode_registry=registry,
        default_directive=ModeDirective(mode="idle", source="default", reason="default idle"),
        strategy_runner=SynchronousStrategyRunner(
            RuleBasedStrategy(),
            trace_sink=trace_sink,
            metrics_sink=metrics_sink,
        ),
        on_step_complete=CrewborgEventTracer(),
        trace_sink=trace_sink,
        metrics_sink=metrics_sink,
    )
