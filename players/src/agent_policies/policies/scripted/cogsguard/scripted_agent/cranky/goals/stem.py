"""Stem goal — select a role based on map and team state."""

from __future__ import annotations

from typing import TYPE_CHECKING

from agent_policies.policies.scripted.cogsguard.scripted_agent.cranky.goal import Goal
from mettagrid.simulator import Action

if TYPE_CHECKING:
    from agent_policies.policies.scripted.cogsguard.scripted_agent.cranky.context import CogasContext


class SelectRoleGoal(Goal):
    """Evaluate map + team hub inventory to select a role.

    Once a role is selected, the agent's goal list is replaced with
    the selected role's goal list. This is a one-time decision.
    """

    name = "SelectRole"

    def __init__(self) -> None:
        self._selected = False

    def is_satisfied(self, ctx: CogasContext) -> bool:
        return self._selected

    def execute(self, ctx: CogasContext) -> Action:
        role = self._select_role(ctx)
        ctx.blackboard["selected_role"] = role
        ctx.blackboard["change_role"] = role
        self._selected = True

        if ctx.trace:
            ctx.trace.activate(self.name, f"selected={role}")

        # Return change_vibe action to immediately start the new role
        return Action(name=f"change_vibe_{role}")

    def _select_role(self, ctx: CogasContext) -> str:
        """Distribute roles: 3 miners + 5 aligners.

        For small teams, prioritize mining since resources are needed for hearts.
        Pattern is tiled across agent IDs.
        """
        agent_id = ctx.agent_id

        pattern_size = 8  # 3 miners + 5 aligners
        pattern_index = agent_id % pattern_size

        if pattern_index < 3:
            return "miner"
        return "aligner"
