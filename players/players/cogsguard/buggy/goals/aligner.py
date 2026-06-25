"""Aligner goals — align neutral junctions."""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from players.cogsguard.buggy.goal import Goal
from players.cogsguard.buggy.navigator import _manhattan
from players.cogsguard._shared.utils import move_toward
from mettagrid.simulator import Action

from .gear import GetGearGoal

if TYPE_CHECKING:
    from players.cogsguard.buggy.context import PlankyContext

JUNCTION_AOE_RANGE = 10
CLIPS_CONTROL_RADIUS = 25


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
    MAX_ATTEMPTS_PER_TARGET = 5
    MAX_NAV_STEPS_PER_TARGET = 80
    COOLDOWN_STEPS = 50
    CLAIM_TTL_STEPS = 60

    def is_satisfied(self, ctx: PlankyContext) -> bool:
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

    def execute(self, ctx: PlankyContext) -> Optional[Action]:
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
        ctx.map.claims[target] = (ctx.agent_id, ctx.step)

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
            claim = ctx.map.claims.get(target)
            if claim and claim[0] == ctx.agent_id:
                ctx.map.claims.pop(target, None)
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
                claim = ctx.map.claims.get(target)
                if claim and claim[0] == ctx.agent_id:
                    ctx.map.claims.pop(target, None)
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

    def _find_best_target(self, ctx: PlankyContext) -> tuple[int, int] | None:
        """Find a good neutral junction to align.

        The map can contain many junctions. To scale, we:
        - Prefer targets near existing cogs territory (influence doesn't last forever).
        - Bias each aligner toward a different compass direction to reduce clustering.
        """
        pos = ctx.state.position

        def recently_failed(p: tuple[int, int]) -> bool:
            failed_step = ctx.blackboard.get(f"align_failed_{p}", -9999)
            return ctx.step - failed_step < self.COOLDOWN_STEPS

        def claimed_by_other(p: tuple[int, int]) -> bool:
            claim = ctx.map.claims.get(p)
            if not claim:
                return False
            claim_agent, claim_step = claim
            if claim_agent == ctx.agent_id:
                return False
            return ctx.step - claim_step <= self.CLAIM_TTL_STEPS

        from players.cogsguard.buggy.policy import SPAWN_POS  # noqa: PLC0415

        def primary_dir(p: tuple[int, int]) -> str:
            dr = p[0] - SPAWN_POS[0]
            dc = p[1] - SPAWN_POS[1]
            if abs(dr) >= abs(dc):
                return "south" if dr > 0 else "north"
            return "east" if dc > 0 else "west"

        preferred = ["north", "east", "south", "west"][ctx.agent_id % 4]

        # Prefer targets outside the Clips expansion/scramble radius.
        # Clips only affect junctions within 25 tiles of their current territory.
        clips_sources = [
            p for p, _ in ctx.map.find(type_contains="junction", property_filter={"alignment": "clips"})
        ] + [p for p, _ in ctx.map.find(type_contains="charger", property_filter={"alignment": "clips"})]
        cogs_sources: list[tuple[int, int]] = [SPAWN_POS]
        cogs_sources.extend([p for p, _ in ctx.map.find(type="hub")])
        cogs_alignment_filter = {"alignment": "cogs"}
        cogs_sources.extend(
            [p for p, _ in ctx.map.find(type_contains="junction", property_filter=cogs_alignment_filter)]
        )
        cogs_sources.extend(
            [p for p, _ in ctx.map.find(type_contains="charger", property_filter=cogs_alignment_filter)]
        )

        def dist_to_cogs(p: tuple[int, int]) -> int:
            return min(_manhattan(p, s) for s in cogs_sources) if cogs_sources else 9999

        scored: list[tuple[tuple[int, int, int], tuple[int, int]]] = []

        def consider(p: tuple[int, int], alignment: object | None) -> None:
            if alignment is not None:
                return
            if recently_failed(p):
                return
            if claimed_by_other(p):
                return
            if any(_manhattan(p, s) <= CLIPS_CONTROL_RADIUS for s in clips_sources):
                return
            d_cogs = dist_to_cogs(p)
            d_agent = _manhattan(pos, p)
            penalty = 0 if primary_dir(p) == preferred else 1
            scored.append(((penalty, d_cogs, d_agent), p))

        for jpos, e in ctx.map.find(type_contains="junction"):
            consider(jpos, e.properties.get("alignment"))
        for cpos, e in ctx.map.find(type_contains="charger"):
            consider(cpos, e.properties.get("alignment"))

        if scored:
            scored.sort()
            return scored[0][1]
        return None


_move_toward = move_toward
