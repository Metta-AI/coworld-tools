"""Reusable two-loop cyborg-agent framework.

The package implements the architecture documented in ``coborg_framework``:
a fast symbolic inner loop connected to a slower strategy loop through typed
mode directives.
"""

from cogames_agents.cyborg.buffers import OverwriteBuffer
from cogames_agents.cyborg.modes import DirectiveValidationError, Mode, ModeRegistry
from cogames_agents.cyborg.runtime import AgentRuntime, Reflex, RuntimeContext
from cogames_agents.cyborg.strategy import (
    ManualStrategyRunner,
    Strategy,
    StrategyRunner,
    SynchronousStrategyRunner,
    ThreadedStrategyRunner,
)
from cogames_agents.cyborg.trace import ListTraceSink, NullTraceSink, TraceEvent, TraceSink
from cogames_agents.cyborg.types import (
    ActionCommand,
    ActionIntent,
    BeliefSnapshot,
    EmptyModeParams,
    ModeDirective,
    ModeParams,
    StrategyResult,
)

__all__ = [
    "ActionCommand",
    "ActionIntent",
    "AgentRuntime",
    "BeliefSnapshot",
    "DirectiveValidationError",
    "EmptyModeParams",
    "ListTraceSink",
    "ManualStrategyRunner",
    "Mode",
    "ModeDirective",
    "ModeParams",
    "ModeRegistry",
    "NullTraceSink",
    "OverwriteBuffer",
    "Reflex",
    "RuntimeContext",
    "Strategy",
    "StrategyResult",
    "StrategyRunner",
    "SynchronousStrategyRunner",
    "ThreadedStrategyRunner",
    "TraceEvent",
    "TraceSink",
]
