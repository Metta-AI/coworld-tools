"""GetGearGoal — navigate to a station to acquire gear."""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from policies.scripted.cogsguard.scripted_agent.buggy.goal import Goal
from policies.scripted.cogsguard.scripted_agent.buggy.navigator import _manhattan
from policies.scripted.cogsguard.scripted_agent.utils import move_toward
from mettagrid.simulator import Action

if TYPE_CHECKING:
    from policies.scripted.cogsguard.scripted_agent.buggy.context import PlankyContext


class GetGearGoal(Goal):
    """Navigate to a station to acquire gear for a role.

    If the team lacks resources to produce gear, the station won't give any.
    Checks team hub resources before attempting, to avoid wasting time bumping
    a station that can't dispense gear.
    """

    # How many bump attempts at dist=1 before exploring for another route
    MAX_BUMPS_AT_STATION = 5
    # How many total steps trying to get gear before giving up temporarily
    MAX_TOTAL_ATTEMPTS = 80
    # How many steps to wait before trying again
    RETRY_INTERVAL = 150

    def __init__(
        self,
        gear_attr: str,
        station_type: str,
        goal_name: str,
        gear_cost: dict[str, int] | None = None,
    ) -> None:
        self.name = goal_name
        self._gear_attr = gear_attr  # e.g. "miner_gear"
        self._station_type = station_type  # e.g. "miner"
        self._gear_cost = gear_cost or {}
        self._bb_attempts_key = f"{goal_name}_total_attempts"
        self._bb_giveup_step_key = f"{goal_name}_giveup_step"
        self._bb_bump_count_key = f"{goal_name}_bump_count"
        self._bb_last_dist_key = f"{goal_name}_last_dist"

    # Minimum team hub resource reserve.
    #
    # CogsGuard starts with limited resources; being too conservative here can
    # prevent most of the team from ever getting gear (and therefore influence).
    RESOURCE_RESERVE = 0

    def _team_can_afford(self, ctx: PlankyContext) -> bool:
        """Check if the team hub can afford gear while maintaining reserves."""
        if not self._gear_cost:
            return True
        s = ctx.state
        team_resources = {
            "carbon": s.team_carbon,
            "oxygen": s.team_oxygen,
            "germanium": s.team_germanium,
            "silicon": s.team_silicon,
        }
        # Must have cost + reserve for each resource
        return all(team_resources.get(res, 0) >= amt + self.RESOURCE_RESERVE for res, amt in self._gear_cost.items())

    def is_satisfied(self, ctx: PlankyContext) -> bool:
        # Satisfied if we have the gear
        if getattr(ctx.state, self._gear_attr, False):
            # Got gear - reset attempts for next time
            ctx.blackboard[self._bb_attempts_key] = 0
            ctx.blackboard[self._bb_bump_count_key] = 0
            return True
        # Also "satisfied" (skip) if we gave up recently
        giveup_step = ctx.blackboard.get(self._bb_giveup_step_key, -9999)
        if ctx.step - giveup_step < self.RETRY_INTERVAL:
            return True
        # Skip if team hub can't afford this gear
        if not self._team_can_afford(ctx):
            if ctx.trace:
                ctx.trace.skip(self.name, "team hub lacks resources")
            return True
        return False

    def execute(self, ctx: PlankyContext) -> Optional[Action]:
        # Track total attempts regardless of distance
        attempts = ctx.blackboard.get(self._bb_attempts_key, 0) + 1
        ctx.blackboard[self._bb_attempts_key] = attempts

        if attempts > self.MAX_TOTAL_ATTEMPTS:
            # Give up - team probably lacks resources or station unreachable
            ctx.blackboard[self._bb_giveup_step_key] = ctx.step
            ctx.blackboard[self._bb_attempts_key] = 0
            ctx.blackboard[self._bb_bump_count_key] = 0
            if ctx.trace:
                ctx.trace.activate(self.name, "giving up after max attempts")
            return None  # Skip to next goal

        # Find station by type
        result = ctx.map.find_nearest(ctx.state.position, type=self._station_type)
        if result is None:
            # Station not discovered yet — navigate toward hub (spawn) where stations are
            from policies.scripted.cogsguard.scripted_agent.buggy.policy import SPAWN_POS  # noqa: PLC0415

            hub_dist = _manhattan(ctx.state.position, SPAWN_POS)
            if ctx.trace:
                ctx.trace.activate(self.name, f"exploring for {self._station_type} (hub dist={hub_dist})")
            if hub_dist > 3:
                # Navigate toward hub
                return ctx.navigator.get_action(ctx.state.position, SPAWN_POS, ctx.map, reach_adjacent=True)
            # At hub — explore nearby to find the station
            return ctx.navigator.explore(ctx.state.position, ctx.map)

        station_pos, _ = result
        dist = _manhattan(ctx.state.position, station_pos)

        if ctx.trace:
            ctx.trace.nav_target = station_pos

        # Track if we're making progress toward the station
        last_dist = ctx.blackboard.get(self._bb_last_dist_key, 999)
        ctx.blackboard[self._bb_last_dist_key] = dist

        if dist <= 1:
            # Adjacent to station — try to bump into it
            bump_count = ctx.blackboard.get(self._bb_bump_count_key, 0) + 1
            ctx.blackboard[self._bb_bump_count_key] = bump_count

            if bump_count > self.MAX_BUMPS_AT_STATION:
                # Stuck at dist=1 - explore to find another path
                ctx.blackboard[self._bb_bump_count_key] = 0
                if ctx.trace:
                    ctx.trace.activate(self.name, "stuck at dist=1, exploring")
                # Clear navigator cache and explore a random direction
                ctx.navigator._cached_path = None
                ctx.navigator._cached_target = None
                return ctx.navigator.explore(ctx.state.position, ctx.map)

            if ctx.trace:
                ctx.trace.activate(self.name, f"bump {bump_count}/{self.MAX_BUMPS_AT_STATION}")
            return _move_toward(ctx.state.position, station_pos)

        # Not adjacent yet - navigate toward station
        ctx.blackboard[self._bb_bump_count_key] = 0

        # If we're not making progress (dist not decreasing), clear cache and try fresh path
        if dist >= last_dist and attempts > 10:
            ctx.navigator._cached_path = None
            ctx.navigator._cached_target = None

        return ctx.navigator.get_action(ctx.state.position, station_pos, ctx.map, reach_adjacent=True)


_move_toward = move_toward
