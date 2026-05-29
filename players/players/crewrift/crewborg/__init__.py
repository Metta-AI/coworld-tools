"""Crewborg — a Player-SDK agent that plays Crewrift.

``build_runtime`` assembles the ``AgentRuntime`` from crewborg's six type
parameters, three pure functions, modes, and the rule-based strategy. See
``design.md`` for the full architecture and ``AGENTS.md`` for orientation.
"""

from __future__ import annotations

from players.crewrift.crewborg.action import resolve_action
from players.crewrift.crewborg.map import MapData, load_croatoan_map
from players.crewrift.crewborg.modes import (
    AttendMeetingMode,
    FleeMode,
    IdleMode,
    NormalMode,
    ReportBodyMode,
)
from players.crewrift.crewborg.strategy import RuleBasedStrategy
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

    The inner loop runs ``perceive -> update_belief -> mode.decide ->
    resolve_action`` each tick; the rule-based strategy publishes mode directives
    via ``SynchronousStrategyRunner``. The static map is baked once here (design
    §6) — ``map_data`` overrides the vendored ``croatoan`` bake (used in tests).
    P3 registers idle / normal / attend_meeting / report_body / flee.
    """

    registry: ModeRegistry[Belief, ActionState, Intent] = ModeRegistry()
    registry.register(IdleMode)
    registry.register(NormalMode)
    registry.register(AttendMeetingMode)
    registry.register(ReportBodyMode)
    registry.register(FleeMode)

    if map_data is None:
        map_data = load_croatoan_map()

    return AgentRuntime(
        belief=Belief(map=map_data),
        action_state=ActionState(),
        perceive=perceive,
        update_belief=update_belief,
        resolve_action=resolve_action,
        mode_registry=registry,
        default_directive=ModeDirective(mode="idle", source="default", reason="default idle"),
        strategy_runner=SynchronousStrategyRunner(
            RuleBasedStrategy(),
            trace_sink=trace_sink,
            metrics_sink=metrics_sink,
        ),
        trace_sink=trace_sink,
        metrics_sink=metrics_sink,
    )
