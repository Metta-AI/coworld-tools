"""Scout goals — explore the map."""

from __future__ import annotations

from typing import TYPE_CHECKING

from agent_policies.policies.scripted.cogsguard.scripted_agent.cranky.goal import Goal
from mettagrid.simulator import Action

from .gear import GetGearGoal

if TYPE_CHECKING:
    from agent_policies.policies.scripted.cogsguard.scripted_agent.cranky.context import CogasContext


class GetScoutGearGoal(GetGearGoal):
    """Get scout gear (costs C1 O1 G1 S3 from team hub)."""

    def __init__(self) -> None:
        super().__init__(
            gear_attr="scout_gear",
            station_type="scout",
            goal_name="GetScoutGear",
            gear_cost={"carbon": 1, "oxygen": 1, "germanium": 1, "silicon": 3},
        )


class ExploreGoal(Goal):
    """Explore the map by navigating to frontier cells."""

    name = "Explore"

    def is_satisfied(self, ctx: CogasContext) -> bool:
        # Never satisfied — always explore
        return False

    def execute(self, ctx: CogasContext) -> Action:
        directions = ["north", "east", "south", "west"]
        direction_bias = directions[ctx.agent_id % 4]
        return ctx.navigator.explore(ctx.state.position, ctx.map, direction_bias=direction_bias)
