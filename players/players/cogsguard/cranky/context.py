"""Context and state snapshot for Cogas policy."""

from __future__ import annotations

from dataclasses import dataclass

from players.cogsguard._shared.common.context import (
    ScriptedAgentContext,
    StateSnapshot,
)


@dataclass
class CogasContext(ScriptedAgentContext):
    """Passed to all goals, bundles everything needed for decision-making."""

    my_team: str = "cogs"


__all__ = ["CogasContext", "StateSnapshot"]
