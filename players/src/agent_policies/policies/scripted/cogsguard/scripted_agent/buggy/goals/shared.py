"""Shared goals used by multiple roles."""

from __future__ import annotations

from typing import TYPE_CHECKING

from agent_policies.policies.scripted.cogsguard.scripted_agent.buggy.goal import Goal
from agent_policies.policies.scripted.cogsguard.scripted_agent.buggy.navigator import _manhattan
from agent_policies.policies.scripted.cogsguard.scripted_agent.utils import move_toward
from mettagrid.simulator import Action

if TYPE_CHECKING:
    from agent_policies.policies.scripted.cogsguard.scripted_agent.buggy.context import PlankyContext


class GetHeartsGoal(Goal):
    """Navigate to hub to acquire hearts.

    In CogsGuard, hearts are obtained from the hub (withdraw if available,
    otherwise craft if the team hub has enough elements). Since Planky cannot
    always observe the team hub heart inventory directly, we primarily rely on
    "try and back off" behavior rather than hard-gating on affordability.
    """

    name = "GetHearts"
    MAX_BUMPS_AT_CHEST = 16
    MAX_TOTAL_ATTEMPTS = 120
    RETRY_INTERVAL = 200

    def __init__(self, min_hearts: int = 1) -> None:
        self._min_hearts = min_hearts
        self._bb_attempts_key = f"{self.name}_total_attempts"
        self._bb_giveup_step_key = f"{self.name}_giveup_step"
        self._bb_bump_count_key = f"{self.name}_bump_count"
        self._bb_prev_heart_key = f"{self.name}_prev_heart"

    def is_satisfied(self, ctx: PlankyContext) -> bool:
        if ctx.state.heart >= self._min_hearts:
            ctx.blackboard[self._bb_attempts_key] = 0
            ctx.blackboard[self._bb_bump_count_key] = 0
            return True
        giveup_step = ctx.blackboard.get(self._bb_giveup_step_key, -9999)
        if ctx.step - giveup_step < self.RETRY_INTERVAL:
            return True
        return False

    def execute(self, ctx: PlankyContext) -> Action | None:
        attempts = ctx.blackboard.get(self._bb_attempts_key, 0) + 1
        ctx.blackboard[self._bb_attempts_key] = attempts
        if attempts > self.MAX_TOTAL_ATTEMPTS:
            ctx.blackboard[self._bb_giveup_step_key] = ctx.step
            ctx.blackboard[self._bb_attempts_key] = 0
            ctx.blackboard[self._bb_bump_count_key] = 0
            if ctx.trace:
                ctx.trace.activate(self.name, "giving up after max attempts")
            return None

        prev_heart = ctx.blackboard.get(self._bb_prev_heart_key, ctx.state.heart)
        if ctx.state.heart > prev_heart:
            # Success — reset counters
            ctx.blackboard[self._bb_attempts_key] = 0
            ctx.blackboard[self._bb_bump_count_key] = 0
        ctx.blackboard[self._bb_prev_heart_key] = ctx.state.heart

        # If carrying cargo, deposit it first before getting hearts
        if ctx.state.cargo_total > 0:
            depot_pos = _find_deposit(ctx)
            if depot_pos is not None:
                if ctx.trace:
                    ctx.trace.nav_target = depot_pos
                dist = _manhattan(ctx.state.position, depot_pos)
                if dist <= 1:
                    return _move_toward(ctx.state.position, depot_pos)
                return ctx.navigator.get_action(ctx.state.position, depot_pos, ctx.map, reach_adjacent=True)

        # Find hub (primary source for hearts)
        result = ctx.map.find_nearest(ctx.state.position, type="hub")
        if result is None:
            return ctx.navigator.explore(ctx.state.position, ctx.map)

        hub_pos, _ = result
        if ctx.trace:
            ctx.trace.nav_target = hub_pos

        dist = _manhattan(ctx.state.position, hub_pos)
        if dist <= 1:
            bump_count = ctx.blackboard.get(self._bb_bump_count_key, 0) + 1
            ctx.blackboard[self._bb_bump_count_key] = bump_count
            if bump_count > self.MAX_BUMPS_AT_CHEST:
                ctx.blackboard[self._bb_giveup_step_key] = ctx.step
                ctx.blackboard[self._bb_attempts_key] = 0
                ctx.blackboard[self._bb_bump_count_key] = 0
                if ctx.trace:
                    ctx.trace.activate(self.name, "no hearts, backing off")
                return None
            return _move_toward(ctx.state.position, hub_pos)
        return ctx.navigator.get_action(ctx.state.position, hub_pos, ctx.map, reach_adjacent=True)


class FallbackMineGoal(Goal):
    """Fallback: mine resources when combat roles can't act.

    Used at the bottom of aligner/scrambler goal lists so they contribute
    to the economy instead of idling when they lack gear or hearts.
    """

    name = "FallbackMine"

    def is_satisfied(self, ctx: PlankyContext) -> bool:
        from .miner import _team_resources_sufficient  # noqa: PLC0415

        # Stop fallback mining when team hub is well-stocked
        if _team_resources_sufficient(ctx) and ctx.state.cargo_total == 0:
            return True
        return False

    def execute(self, ctx: PlankyContext) -> Action:
        from .miner import RESOURCE_TYPES, _extractor_recently_failed  # noqa: PLC0415

        # If carrying resources, deposit first
        if ctx.state.cargo_total > 0:
            depot_pos = _find_deposit(ctx)
            if depot_pos is not None:
                if ctx.trace:
                    ctx.trace.nav_target = depot_pos
                dist = _manhattan(ctx.state.position, depot_pos)
                if dist <= 1:
                    return _move_toward(ctx.state.position, depot_pos)
                return ctx.navigator.get_action(ctx.state.position, depot_pos, ctx.map, reach_adjacent=True)

        # Find nearest usable extractor (any resource type)
        best: tuple[int, tuple[int, int]] | None = None
        for resource in RESOURCE_TYPES:
            for pos, e in ctx.map.find(type=f"{resource}_extractor"):
                if e.properties.get("inventory_amount", -1) == 0:
                    continue
                if _extractor_recently_failed(ctx, pos):
                    continue
                d = _manhattan(ctx.state.position, pos)
                if best is None or d < best[0]:
                    best = (d, pos)

        if best is not None:
            if ctx.trace:
                ctx.trace.nav_target = best[1]
            dist = best[0]
            if dist <= 1:
                return _move_toward(ctx.state.position, best[1])
            return ctx.navigator.get_action(ctx.state.position, best[1], ctx.map, reach_adjacent=True)

        # No extractors known — explore
        return ctx.navigator.explore(
            ctx.state.position,
            ctx.map,
            direction_bias=["north", "east", "south", "west"][ctx.agent_id % 4],
        )


def _find_deposit(ctx: "PlankyContext") -> tuple[int, int] | None:
    """Find nearest cogs-aligned depot for depositing resources."""
    pos = ctx.state.position
    candidates: list[tuple[int, tuple[int, int]]] = []
    for apos, _ in ctx.map.find(type="hub"):
        candidates.append((_manhattan(pos, apos), apos))
    for jpos, _ in ctx.map.find(type_contains="junction", property_filter={"alignment": "cogs"}):
        candidates.append((_manhattan(pos, jpos), jpos))
    for cpos, _ in ctx.map.find(type_contains="charger", property_filter={"alignment": "cogs"}):
        candidates.append((_manhattan(pos, cpos), cpos))
    if not candidates:
        return None
    candidates.sort()
    return candidates[0][1]


_move_toward = move_toward
