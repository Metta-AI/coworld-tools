"""Strategy layer for the coborg Among Them agent.

P0 ships :class:`RuleBasedStrategy`, a placeholder that always issues the
``idle`` directive. P2 expands this into a real crewmate planner; P4 adds
role-aware imposter branching. An LLM strategy is explicitly deferred (PLAN §6
"Out of scope").
"""

from __future__ import annotations

from agent_policies.policies.cyborg.bitworld.coborg_among_them.strategy.rule_based import (
    RuleBasedStrategy,
)

__all__ = ["RuleBasedStrategy"]
