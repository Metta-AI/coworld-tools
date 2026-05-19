"""Coborg-based Among Them agent (P0 scaffold).

The agent plugs ``perceive -> update_belief -> mode decide -> action resolve``
into :class:`players_lib.coborg.AgentRuntime` and ships as a
single Docker image consumed by the Coworld tournament runner. P0 wires a
deterministic noop policy through the full stack; subsequent phases land
perception, crewmate, meetings, and imposter behavior.

See ``PLAN.md`` and ``DESIGN.md`` in this directory for the implementation
plan and durable architecture notes.
"""

from __future__ import annotations

from players_lib.coborg import (
    AgentRuntime,
    ModeDirective,
    ModeRegistry,
    SynchronousStrategyRunner,
    TraceSink,
)
from players_lib.coborg.trace import MetricsSink

from players.among_them.coborg.action import (
    resolve_action,
)
from players.among_them.coborg.modes.idle import (
    IdleMode,
)
from players.among_them.coborg.strategy.rule_based import (
    RuleBasedStrategy,
)
from players.among_them.coborg.types import (
    AmongThemBelief,
    AmongThemCommand,
    AmongThemIntent,
    AmongThemObservation,
    AmongThemPercept,
    ActionState,
    perceive,
    update_belief,
)

__all__ = [
    "ActionState",
    "AmongThemBelief",
    "AmongThemCommand",
    "AmongThemIntent",
    "AmongThemObservation",
    "AmongThemPercept",
    "IdleMode",
    "RuleBasedStrategy",
    "build_runtime",
]


def build_runtime(
    *,
    trace_sink: TraceSink | None = None,
    metrics_sink: MetricsSink | None = None,
) -> AgentRuntime[
    AmongThemObservation,
    AmongThemPercept,
    AmongThemBelief,
    ActionState,
    AmongThemIntent,
    AmongThemCommand,
]:
    """Assemble the P0 coborg runtime: idle-only, deterministic noop output."""

    registry: ModeRegistry[AmongThemBelief, ActionState, AmongThemIntent] = (
        ModeRegistry()
    )
    registry.register(IdleMode)

    return AgentRuntime(
        belief=AmongThemBelief(),
        action_state=ActionState(),
        perceive=perceive,
        update_belief=update_belief,
        resolve_action=resolve_action,
        mode_registry=registry,
        default_directive=ModeDirective(
            mode="idle", source="default", reason="P0 noop"
        ),
        strategy_runner=SynchronousStrategyRunner(RuleBasedStrategy()),
        trace_sink=trace_sink,
        metrics_sink=metrics_sink,
    )
