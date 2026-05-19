"""Reusable two-loop cyborg-agent framework.

The package implements the Coborg architecture documented under
``src/players_lib/coborg/docs/metta_cogames_framework``: a fast symbolic
inner loop connected to a slower strategy loop through typed mode
directives.
"""

from players_lib.coborg.buffers import OverwriteBuffer
from players_lib.coborg.modes import DirectiveValidationError, Mode, ModeRegistry
from players_lib.coborg.runtime import AgentRuntime, Reflex, ReflexRule, RuntimeContext
from players_lib.coborg.strategy import (
    AsyncStrategy,
    AsyncStrategyRunner,
    ManualStrategyRunner,
    Strategy,
    StrategyRunner,
    SynchronousStrategyRunner,
    ThreadedStrategyRunner,
)
from players_lib.coborg.trace import (
    ListMetricsSink,
    ListTraceSink,
    LoggingMetricsSink,
    LoggingTraceSink,
    MetricSample,
    MetricsSink,
    NullMetricsSink,
    NullTraceSink,
    TraceEvent,
    TraceSink,
    WandbMetricsSink,
)
from players_lib.coborg.types import (
    ActionCommand,
    ActionIntent,
    BeliefSnapshot,
    EmptyModeParams,
    ModeDecision,
    ModeDirective,
    ModeParams,
    SharedMemory,
    SharedMemoryView,
    StrategyResult,
)

__all__ = [
    "ActionCommand",
    "ActionIntent",
    "AgentRuntime",
    "AsyncStrategy",
    "AsyncStrategyRunner",
    "BeliefSnapshot",
    "DirectiveValidationError",
    "EmptyModeParams",
    "ListMetricsSink",
    "ListTraceSink",
    "LoggingMetricsSink",
    "LoggingTraceSink",
    "ManualStrategyRunner",
    "MetricSample",
    "MetricsSink",
    "Mode",
    "ModeDecision",
    "ModeDirective",
    "ModeParams",
    "ModeRegistry",
    "NullMetricsSink",
    "NullTraceSink",
    "OverwriteBuffer",
    "Reflex",
    "ReflexRule",
    "RuntimeContext",
    "SharedMemory",
    "SharedMemoryView",
    "Strategy",
    "StrategyResult",
    "StrategyRunner",
    "SynchronousStrategyRunner",
    "ThreadedStrategyRunner",
    "TraceEvent",
    "TraceSink",
    "WandbMetricsSink",
]
