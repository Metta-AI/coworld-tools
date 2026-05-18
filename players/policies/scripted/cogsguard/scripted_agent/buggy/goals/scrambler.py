"""Scrambler goals — neutralize enemy junctions."""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from policies.scripted.cogsguard.scripted_agent.buggy.goal import Goal
from policies.scripted.cogsguard.scripted_agent.buggy.navigator import _manhattan
from policies.scripted.cogsguard.scripted_agent.utils import move_toward
from mettagrid.simulator import Action

from .gear import GetGearGoal

if TYPE_CHECKING:
    from policies.scripted.cogsguard.scripted_agent.buggy.context import PlankyContext

JUNCTION_AOE_RANGE = 10
CLIPS_CONTROL_RADIUS = 25


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
    CLAIM_TTL_STEPS = 60

    def is_satisfied(self, ctx: PlankyContext) -> bool:
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

    def execute(self, ctx: PlankyContext) -> Optional[Action]:
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
        ctx.map.claims[target] = (ctx.agent_id, ctx.step)

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
            attempts_key = f"scramble_attempts_{target}"
            attempts = ctx.blackboard.get(attempts_key, 0) + 1
            ctx.blackboard[attempts_key] = attempts

            if attempts > self.MAX_ATTEMPTS_PER_TARGET:
                # Mark this junction as failed temporarily
                failed_key = f"scramble_failed_{target}"
                ctx.blackboard[failed_key] = ctx.step
                ctx.blackboard[attempts_key] = 0
                claim = ctx.map.claims.get(target)
                if claim and claim[0] == ctx.agent_id:
                    ctx.map.claims.pop(target, None)
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

    def _find_best_target(self, ctx: PlankyContext) -> tuple[int, int] | None:
        """Find enemy junction to scramble.

        Scramblers are most valuable at the frontier: neutralizing nearby Clips
        territory so Aligners can advance without having their influence drained.
        """
        pos = ctx.state.position

        def recently_failed(p: tuple[int, int]) -> bool:
            failed_step = ctx.blackboard.get(f"scramble_failed_{p}", -9999)
            return ctx.step - failed_step < self.COOLDOWN_STEPS

        def claimed_by_other(p: tuple[int, int]) -> bool:
            claim = ctx.map.claims.get(p)
            if not claim:
                return False
            claim_agent, claim_step = claim
            if claim_agent == ctx.agent_id:
                return False
            return ctx.step - claim_step <= self.CLAIM_TTL_STEPS

        enemy_positions = [
            p for p, _ in ctx.map.find(type_contains="junction", property_filter={"alignment": "clips"})
        ] + [p for p, _ in ctx.map.find(type_contains="charger", property_filter={"alignment": "clips"})]
        if not enemy_positions:
            return None

        from policies.scripted.cogsguard.scripted_agent.buggy.policy import SPAWN_POS  # noqa: PLC0415

        def primary_dir(p: tuple[int, int]) -> str:
            dr = p[0] - SPAWN_POS[0]
            dc = p[1] - SPAWN_POS[1]
            if abs(dr) >= abs(dc):
                return "south" if dr > 0 else "north"
            return "east" if dc > 0 else "west"

        preferred = ["north", "east", "south", "west"][ctx.agent_id % 4]

        # Favor targets near friendly territory to create an advancing buffer.
        cogs_sources: list[tuple[int, int]] = [SPAWN_POS]
        cogs_sources.extend([p for p, _ in ctx.map.find(type="hub")])
        cogs_alignment_filter = {"alignment": "cogs"}
        cogs_sources.extend(
            [p for p, _ in ctx.map.find(type_contains="junction", property_filter=cogs_alignment_filter)]
        )
        cogs_sources.extend(
            [p for p, _ in ctx.map.find(type_contains="charger", property_filter=cogs_alignment_filter)]
        )

        neutral_positions = [
            p for p, e in ctx.map.find(type_contains="junction") if e.properties.get("alignment") is None
        ] + [p for p, e in ctx.map.find(type_contains="charger") if e.properties.get("alignment") is None]

        def dist_to_cogs(p: tuple[int, int]) -> int:
            return min(_manhattan(p, s) for s in cogs_sources) if cogs_sources else 9999

        scored: list[tuple[tuple[int, int, int, int], tuple[int, int]]] = []
        for epos in enemy_positions:
            if recently_failed(epos):
                continue
            if claimed_by_other(epos):
                continue
            d_cogs = dist_to_cogs(epos)
            d_agent = _manhattan(pos, epos)
            penalty_dir = 0 if primary_dir(epos) == preferred else 1
            blocked = sum(1 for np in neutral_positions if _manhattan(epos, np) <= CLIPS_CONTROL_RADIUS)
            scored.append(((d_cogs, penalty_dir, -blocked, d_agent), epos))

        if not scored:
            return None

        scored.sort()
        return scored[0][1]


_move_toward = move_toward
