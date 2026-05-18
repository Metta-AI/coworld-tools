"""Aligner goals — align neutral junctions."""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from policies.scripted.cogsguard.scripted_agent.cranky.goal import Goal
from policies.scripted.cogsguard.scripted_agent.cranky.navigator import _manhattan
from policies.scripted.cogsguard.scripted_agent.utils import move_toward
from mettagrid.simulator import Action

from .gear import GetGearGoal

if TYPE_CHECKING:
    from policies.scripted.cogsguard.scripted_agent.cranky.context import CogasContext

JUNCTION_AOE_RANGE = 10


class GetAlignerGearGoal(GetGearGoal):
    """Get aligner gear (costs C3 O1 G1 S1 from team hub)."""

    def __init__(self) -> None:
        super().__init__(
            gear_attr="aligner_gear",
            station_type="aligner",
            goal_name="GetAlignerGear",
            gear_cost={"carbon": 3, "oxygen": 1, "germanium": 1, "silicon": 1},
        )


class AlignJunctionGoal(Goal):
    """Find and align a neutral junction to cogs.

    Tracks attempts per junction to avoid getting stuck on one that
    can't be captured (e.g., already aligned but map hasn't updated).
    """

    name = "AlignJunction"
    MAX_ATTEMPTS_PER_TARGET = 15  # Increased from 5 - 55% move fail needs more attempts
    MAX_NAV_STEPS_PER_TARGET = 80  # Increased from 40 - give more time to navigate
    COOLDOWN_STEPS = 30  # Reduced from 50 - try junctions again sooner

    def is_satisfied(self, ctx: CogasContext) -> bool:
        # Can't align without gear and a heart
        if not ctx.state.aligner_gear:
            if ctx.trace:
                ctx.trace.skip(self.name, "no gear")
            return True
        if ctx.state.heart < 1:
            if ctx.trace:
                ctx.trace.skip(self.name, "no heart")
            return True
        return False

    def execute(self, ctx: CogasContext) -> Optional[Action]:
        nav_key = "_align_nav_steps"
        nav_target_key = "_align_nav_target"
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

        # Nav timeout — mark target as failed
        if nav_steps > self.MAX_NAV_STEPS_PER_TARGET:
            failed_key = f"align_failed_{target}"
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
            attempts_key = f"align_attempts_{target}"
            attempts = ctx.blackboard.get(attempts_key, 0) + 1
            ctx.blackboard[attempts_key] = attempts

            if attempts > self.MAX_ATTEMPTS_PER_TARGET:
                # Mark this junction as failed temporarily
                failed_key = f"align_failed_{target}"
                ctx.blackboard[failed_key] = ctx.step
                ctx.blackboard[attempts_key] = 0
                if ctx.trace:
                    ctx.trace.activate(self.name, f"giving up on {target}")
                # Clear and try a different junction next tick
                return ctx.navigator.explore(
                    ctx.state.position,
                    ctx.map,
                    direction_bias=["north", "east", "south", "west"][ctx.agent_id % 4],
                )

            if ctx.trace:
                ctx.trace.activate(self.name, f"bump {attempts}/{self.MAX_ATTEMPTS_PER_TARGET}")
            return _move_toward(ctx.state.position, target)

        # Not adjacent - reset attempts for this target
        attempts_key = f"align_attempts_{target}"
        ctx.blackboard[attempts_key] = 0
        return ctx.navigator.get_action(ctx.state.position, target, ctx.map, reach_adjacent=True)

    def _find_best_target(self, ctx: CogasContext) -> tuple[int, int] | None:
        """Find nearest neutral junction, including contested ones."""
        pos = ctx.state.position

        def recently_failed(p: tuple[int, int]) -> bool:
            failed_step = ctx.blackboard.get(f"align_failed_{p}", -9999)
            return ctx.step - failed_step < self.COOLDOWN_STEPS

        # Find neutral junctions (no AOE filter — aligners go where needed)
        candidates: list[tuple[int, tuple[int, int]]] = []

        for jpos, e in ctx.map.find(type_contains="junction"):
            alignment = e.properties.get("alignment")
            if alignment is not None:
                continue  # Not neutral
            if recently_failed(jpos):
                continue
            candidates.append((_manhattan(pos, jpos), jpos))

        if not candidates:
            return None
        candidates.sort()
        return candidates[0][1]


_move_toward = move_toward
