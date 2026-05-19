"""Deterministic rule-based strategy.

P0 emits an ``idle`` directive on every snapshot. The runtime's default
directive (also idle) covers cases where the strategy returns ``None``, so
this class is mainly here to exercise the strategy-runner boundary and prove
that traces include ``snapshot_submitted`` events.
"""

from __future__ import annotations

from agent_policies.frameworks.coborg import ModeDirective, StrategyResult
from agent_policies.frameworks.coborg.types import BeliefSnapshot

from players.among_them.coborg.types import (
    ActionState,
    AmongThemBelief,
)


class RuleBasedStrategy:
    """Always-idle strategy. Replace in P2+."""

    def decide(
        self,
        snapshot: BeliefSnapshot[AmongThemBelief, ActionState],
    ) -> StrategyResult | ModeDirective | None:
        del snapshot  # P0 ignores belief; later phases consult it here
        return ModeDirective(mode="idle", source="strategy", reason="P0 noop strategy")
