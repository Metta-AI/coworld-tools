"""Stem goal — select a role based on map and team state."""

from __future__ import annotations

from typing import TYPE_CHECKING

from policies.scripted.cogsguard.scripted_agent.buggy.goal import Goal
from mettagrid.simulator import Action

if TYPE_CHECKING:
    from policies.scripted.cogsguard.scripted_agent.buggy.context import PlankyContext


class SelectRoleGoal(Goal):
    """Evaluate map + team hub inventory to select a role.

    Once a role is selected, the agent's goal list is replaced with
    the selected role's goal list. This is a one-time decision.
    """

    name = "SelectRole"

    def __init__(self) -> None:
        self._selected = False

    def is_satisfied(self, ctx: PlankyContext) -> bool:
        return self._selected

    def execute(self, ctx: PlankyContext) -> Action:
        role = self._select_role(ctx)
        ctx.blackboard["selected_role"] = role
        ctx.blackboard["change_role"] = role
        self._selected = True

        if ctx.trace:
            ctx.trace.activate(self.name, f"selected={role}")

        return Action(name="noop")

    def _select_role(self, ctx: PlankyContext) -> str:
        """Distribute roles by agent_id: 5 miners, 5 aligners."""
        agent_id = ctx.agent_id
        if agent_id < 5:
            return "miner"
        return "aligner"
