"""Richardborg — a Player-SDK agent that plays Crewrift.

``build_runtime`` assembles the ``AgentRuntime`` from richardborg's six type
parameters, three pure functions, modes, and the rule-based strategy. See
``design.md`` for the full architecture and ``AGENTS.md`` for orientation.
"""

from __future__ import annotations

from players.crewrift.richardborg.agent_tracking import update_agent_tracking
from players.crewrift.richardborg.action import resolve_action
from players.crewrift.richardborg.events import RichardborgEventTracer
from players.crewrift.richardborg.map import MapData, load_croatoan_map
from players.crewrift.richardborg.modes import (
    AttendMeetingMode,
    DickMode,
    EvadeMode,
    FleeMode,
    HuntMode,
    IdleMode,
    NormalMode,
    PretendMode,
    ReportBodyMode,
    SearchMode,
)
from players.crewrift.richardborg.strategy import (
    RuleBasedStrategy,
    update_event_log,
    update_suspicion,
)
from players.crewrift.richardborg.types import (
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
    """Assemble the richardborg ``AgentRuntime``.

    The inner loop runs ``perceive -> update_belief (+ agent tracking + event log
    + suspicion) -> mode.decide -> resolve_action`` each tick; the rule-based
    strategy publishes mode directives via ``SynchronousStrategyRunner``. The
    per-agent location tracker, per-player event log (design §5.2), and suspicion
    scoring (§10.1) are folded into belief right after perception so the strategy
    snapshot sees current search and ``believed_imposters`` state. The static map
    is baked once here (design §6) — ``map_data`` overrides the vendored
    ``croatoan`` bake (tests).
    Registers all modes: idle / normal / attend_meeting / dick_mode / report_body / flee
    (crewmate) and evade / pretend / search / hunt (imposter). A ``RichardborgEventTracer``
    is wired as the runtime's ``on_step_complete`` hook so richardborg emits its
    ``domain.*`` trace events through the configured sinks (design §11): the
    phase / sighting / objective / kill / vote outcomes *and* the knowledge layer
    behind them (per-player event log + suspicion posteriors, with a
    ``suspicion_snapshot`` each meeting; ``RICHARDBORG_TRACE=debug`` adds a per-tick
    dump).
    """

    registry: ModeRegistry[Belief, ActionState, Intent] = ModeRegistry()
    registry.register(IdleMode)
    registry.register(NormalMode)
    registry.register(AttendMeetingMode)
    registry.register(DickMode)
    registry.register(ReportBodyMode)
    registry.register(FleeMode)
    registry.register(EvadeMode)
    registry.register(HuntMode)
    registry.register(PretendMode)
    registry.register(SearchMode)

    if map_data is None:
        map_data = load_croatoan_map()

    def fold_belief(belief: Belief, percept: Percept) -> None:
        """Fast-loop belief update: perception, tracking, event log, then suspicion."""

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
            mode="idle", source="default", reason="default idle"
        ),
        strategy_runner=SynchronousStrategyRunner(
            RuleBasedStrategy(),
            trace_sink=trace_sink,
            metrics_sink=metrics_sink,
        ),
        on_step_complete=RichardborgEventTracer(),
        trace_sink=trace_sink,
        metrics_sink=metrics_sink,
    )
