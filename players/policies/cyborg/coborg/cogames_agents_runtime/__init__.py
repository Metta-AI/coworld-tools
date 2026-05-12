"""Reusable two-loop cyborg-agent framework.

The package implements the architecture documented in ``coborg_framework``:
a fast symbolic inner loop connected to a slower strategy loop through typed
mode directives.
"""

from cogames_agents.cyborg.buffers import OverwriteBuffer
from cogames_agents.cyborg.modes import DirectiveValidationError, Mode, ModeRegistry
from cogames_agents.cyborg.runtime import AgentRuntime, Reflex, ReflexRule, RuntimeContext
from cogames_agents.cyborg.strategy import (
    AsyncStrategy,
    AsyncStrategyRunner,
    ManualStrategyRunner,
    Strategy,
    StrategyRunner,
    SynchronousStrategyRunner,
    ThreadedStrategyRunner,
)
from cogames_agents.cyborg.trace import (
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
from cogames_agents.cyborg.types import (
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
