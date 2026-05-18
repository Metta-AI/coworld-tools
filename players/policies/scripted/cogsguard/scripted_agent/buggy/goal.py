"""Goal base class and evaluation logic for Planky policy."""

from __future__ import annotations

from typing import TYPE_CHECKING

from policies.scripted.cogsguard.scripted_agent.common.goal import Goal
from policies.scripted.cogsguard.scripted_agent.common.goal import evaluate_goals as _evaluate_goals
from mettagrid.simulator import Action

if TYPE_CHECKING:
    from .context import PlankyContext


def evaluate_goals(goals: list[Goal], ctx: PlankyContext) -> Action:
    return _evaluate_goals(goals, ctx)


__all__ = ["Goal", "evaluate_goals"]
