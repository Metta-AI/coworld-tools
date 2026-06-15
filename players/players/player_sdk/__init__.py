"""Coworld Player SDK — reusable two-loop cyborg-agent framework.

The package implements the Coborg architecture documented under
``players/player_sdk/docs/metta_cogames_framework``: a fast symbolic
inner loop connected to a slower strategy loop through typed mode
directives.
"""

from players.player_sdk.buffers import OverwriteBuffer
from players.player_sdk.message_bridge import (
    ClosePolicy,
    MessageHandler,
    exit_zero_on_unclean_close,
    run_message_bridge,
)
from players.player_sdk.modes import DirectiveValidationError, Mode, ModeRegistry
from players.player_sdk.runtime import (
    AgentRuntime,
    Reflex,
    ReflexRule,
    RuntimeContext,
    StepCompleteHook,
    StepContext,
)
from players.player_sdk.strategy import (
    AsyncStrategy,
    AsyncStrategyRunner,
    ManualStrategyRunner,
    Strategy,
    StrategyRunner,
    SynchronousStrategyRunner,
    ThreadedStrategyRunner,
)
from players.player_sdk.trace import (
    EventEmitter,
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
from players.player_sdk.trace_outputs import TraceOutputSpec, TraceOutputs, parse_trace_output_specs
from players.player_sdk.types import (
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
    "ClosePolicy",
    "DirectiveValidationError",
    "EmptyModeParams",
    "EventEmitter",
    "ListMetricsSink",
    "ListTraceSink",
    "LoggingMetricsSink",
    "LoggingTraceSink",
    "ManualStrategyRunner",
    "MessageHandler",
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
    "StepCompleteHook",
    "StepContext",
    "Strategy",
    "StrategyResult",
    "StrategyRunner",
    "SynchronousStrategyRunner",
    "ThreadedStrategyRunner",
    "TraceEvent",
    "TraceOutputSpec",
    "TraceOutputs",
    "TraceSink",
    "WandbMetricsSink",
    "exit_zero_on_unclean_close",
    "parse_trace_output_specs",
    "run_message_bridge",
]
