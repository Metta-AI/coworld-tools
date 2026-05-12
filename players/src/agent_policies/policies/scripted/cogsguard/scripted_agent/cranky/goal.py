"""Goal base class and evaluation logic for Cogas policy."""

from __future__ import annotations

from typing import TYPE_CHECKING

from agent_policies.policies.scripted.cogsguard.scripted_agent.common.goal import Goal
from agent_policies.policies.scripted.cogsguard.scripted_agent.common.goal import evaluate_goals as _evaluate_goals
from mettagrid.simulator import Action

if TYPE_CHECKING:
    from .context import CogasContext


def evaluate_goals(goals: list[Goal], ctx: CogasContext) -> Action:
    directions = ["north", "east", "south", "west"]
    return _evaluate_goals(
        goals,
        ctx,
        fallback_action=lambda: ctx.navigator.explore(
            ctx.state.position,
            ctx.map,
            direction_bias=directions[ctx.agent_id % 4],
        ),
    )


__all__ = ["Goal", "evaluate_goals"]
