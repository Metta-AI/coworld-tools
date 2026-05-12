"""Scrambler goals — neutralize enemy junctions."""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from agent_policies.policies.scripted.cogsguard.scripted_agent.cranky.goal import Goal
from agent_policies.policies.scripted.cogsguard.scripted_agent.cranky.navigator import _manhattan
from agent_policies.policies.scripted.cogsguard.scripted_agent.utils import move_toward
from mettagrid.simulator import Action

from .gear import GetGearGoal

if TYPE_CHECKING:
    from agent_policies.policies.scripted.cogsguard.scripted_agent.cranky.context import CogasContext

JUNCTION_AOE_RANGE = 10


class GetScramblerGearGoal(GetGearGoal):
    """Get scrambler gear (costs C1 O3 G1 S1 from team hub)."""

    def __init__(self) -> None:
        super().__init__(
            gear_attr="scrambler_gear",
            station_type="scrambler",
            goal_name="GetScramblerGear",
            gear_cost={"carbon": 1, "oxygen": 3, "germanium": 1, "silicon": 1},
        )


class ScrambleJunctionGoal(Goal):
    """Find and scramble enemy (clips) junctions.

    Tracks attempts per junction to avoid getting stuck.
    """

    name = "ScrambleJunction"
    MAX_ATTEMPTS_PER_TARGET = 5
    MAX_NAV_STEPS_PER_TARGET = 40  # Give up navigating to a target after this many steps
    COOLDOWN_STEPS = 50

    def is_satisfied(self, ctx: CogasContext) -> bool:
        # Can't scramble without gear and a heart
        if not ctx.state.scrambler_gear:
            if ctx.trace:
                ctx.trace.skip(self.name, "no gear")
            return True
        if ctx.state.heart < 1:
            if ctx.trace:
                ctx.trace.skip(self.name, "no heart")
            return True
        return False

    def execute(self, ctx: CogasContext) -> Optional[Action]:
        # Track navigation steps toward current target to detect stuck
        nav_key = "_scramble_nav_steps"
        nav_target_key = "_scramble_nav_target"
        nav_steps = ctx.blackboard.get(nav_key, 0) + 1
        ctx.blackboard[nav_key] = nav_steps

        target = self._find_best_target(ctx)
        if target is None:
            ctx.blackboard[nav_key] = 0
            return ctx.navigator.explore(
                ctx.state.position,
                ctx.map,
                direction_bias=["north", "east", "south", "west"][ctx.agent_id % 4],
            )

        # Reset nav counter if target changed
        prev_target = ctx.blackboard.get(nav_target_key)
        if prev_target != target:
            ctx.blackboard[nav_key] = 0
            nav_steps = 0
        ctx.blackboard[nav_target_key] = target

        # If we've been navigating too long, mark target as failed
        if nav_steps > self.MAX_NAV_STEPS_PER_TARGET:
            failed_key = f"scramble_failed_{target}"
            ctx.blackboard[failed_key] = ctx.step
            ctx.blackboard[nav_key] = 0
            if ctx.trace:
                ctx.trace.activate(self.name, f"nav timeout on {target}")
            return ctx.navigator.explore(
                ctx.state.position,
                ctx.map,
                direction_bias=["north", "east", "south", "west"][ctx.agent_id % 4],
            )

        if ctx.trace:
            ctx.trace.nav_target = target

        dist = _manhattan(ctx.state.position, target)
        if dist <= 1:
            # Track attempts on this specific junction
            attempts_key = f"scramble_attempts_{target}"
            attempts = ctx.blackboard.get(attempts_key, 0) + 1
            ctx.blackboard[attempts_key] = attempts

            if attempts > self.MAX_ATTEMPTS_PER_TARGET:
                # Mark this junction as failed temporarily
                failed_key = f"scramble_failed_{target}"
                ctx.blackboard[failed_key] = ctx.step
                ctx.blackboard[attempts_key] = 0
                if ctx.trace:
                    ctx.trace.activate(self.name, f"giving up on {target}")
                return ctx.navigator.explore(
                    ctx.state.position,
                    ctx.map,
                    direction_bias=["north", "east", "south", "west"][ctx.agent_id % 4],
                )

            if ctx.trace:
                ctx.trace.activate(self.name, f"bump {attempts}/{self.MAX_ATTEMPTS_PER_TARGET}")
            return _move_toward(ctx.state.position, target)

        # Not adjacent - reset attempts for this target
        attempts_key = f"scramble_attempts_{target}"
        ctx.blackboard[attempts_key] = 0
        return ctx.navigator.get_action(ctx.state.position, target, ctx.map, reach_adjacent=True)

    def _find_best_target(self, ctx: CogasContext) -> tuple[int, int] | None:
        """Find enemy junction to scramble, prioritized by blocking count."""
        pos = ctx.state.position

        def recently_failed(p: tuple[int, int]) -> bool:
            failed_step = ctx.blackboard.get(f"scramble_failed_{p}", -9999)
            return ctx.step - failed_step < self.COOLDOWN_STEPS

        # Get clips junctions
        enemy: list[tuple[tuple[int, int], dict]] = []
        for jpos, e in ctx.map.find(type_contains="junction", property_filter={"alignment": "clips"}):
            if not recently_failed(jpos):
                enemy.append((jpos, e.properties))
        for cpos, e in ctx.map.find(type_contains="junction", property_filter={"alignment": "clips"}):
            if not recently_failed(cpos):
                enemy.append((cpos, e.properties))

        if not enemy:
            return None

        # Get neutral junctions for scoring
        neutral_positions: list[tuple[int, int]] = []
        for jpos, e in ctx.map.find(type_contains="junction"):
            if e.properties.get("alignment") is None:
                neutral_positions.append(jpos)
        for cpos, e in ctx.map.find(type_contains="junction"):
            if e.properties.get("alignment") is None:
                neutral_positions.append(cpos)

        # Score by: how many neutrals this enemy blocks, then by distance
        scored: list[tuple[int, int, tuple[int, int]]] = []
        for epos, _ in enemy:
            blocked = sum(1 for np in neutral_positions if _manhattan(epos, np) <= JUNCTION_AOE_RANGE)
            dist = _manhattan(pos, epos)
            scored.append((-blocked, dist, epos))  # Negative blocked for descending sort

        scored.sort()
        return scored[0][2]


_move_toward = move_toward
