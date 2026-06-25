"""Context and state snapshot for Planky policy."""

from __future__ import annotations

from dataclasses import dataclass

from players.cogsguard._shared.common.context import (
    ScriptedAgentContext,
    StateSnapshot,
)


@dataclass
class PlankyContext(ScriptedAgentContext):
    """Passed to all goals, bundles everything needed for decision-making."""


__all__ = ["PlankyContext", "StateSnapshot"]
