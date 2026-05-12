"""Reusable two-loop cyborg-agent framework.

The package implements the architecture documented in ``coborg_framework``:
a fast symbolic inner loop connected to a slower strategy loop through typed
mode directives.
"""

from agent_policies.frameworks.coborg.buffers import OverwriteBuffer
from agent_policies.frameworks.coborg.modes import DirectiveValidationError, Mode, ModeRegistry
from agent_policies.frameworks.coborg.runtime import AgentRuntime, Reflex, ReflexRule, RuntimeContext
from agent_policies.frameworks.coborg.strategy import (
    AsyncStrategy,
    AsyncStrategyRunner,
    ManualStrategyRunner,
    Strategy,
    StrategyRunner,
    SynchronousStrategyRunner,
    ThreadedStrategyRunner,
)
from agent_policies.frameworks.coborg.trace import (
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
from agent_policies.frameworks.coborg.types import (
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
