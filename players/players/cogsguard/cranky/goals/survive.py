"""SurviveGoal — retreat to safety when HP is critical."""

from __future__ import annotations

from typing import TYPE_CHECKING

from players.cogsguard.cranky.goal import Goal
from players.cogsguard.cranky.navigator import _manhattan, _move_action
from mettagrid.simulator import Action

if TYPE_CHECKING:
    from players.cogsguard.cranky.context import CogasContext

# Game constants
JUNCTION_AOE_RANGE = 10
HP_SAFETY_MARGIN = 10


class SurviveGoal(Goal):
    """Retreat to nearest safe zone when HP is low."""

    name = "Survive"

    def __init__(self, hp_threshold: int = 30) -> None:
        self._hp_threshold = hp_threshold

    def is_satisfied(self, ctx: CogasContext) -> bool:
        # If we're in a safe zone, we're fine
        if _is_in_safe_zone(ctx):
            return True
        # If HP is above threshold, we're fine
        safe_pos = _nearest_safe_zone(ctx)
        if safe_pos is None:
            return ctx.state.hp > 20  # No known safe zone, be conservative
        steps_to_safety = max(0, _manhattan(ctx.state.position, safe_pos) - JUNCTION_AOE_RANGE)
        hp_needed = steps_to_safety + HP_SAFETY_MARGIN
        return ctx.state.hp > hp_needed

    def execute(self, ctx: CogasContext) -> Action:
        safe_pos = _nearest_safe_zone(ctx)
        if safe_pos is None:
            return ctx.navigator.explore(ctx.state.position, ctx.map)
        if ctx.trace:
            ctx.trace.nav_target = safe_pos
        # Check dist to avoid navigator returning noop
        dist = _manhattan(ctx.state.position, safe_pos)
        if dist <= 1:
            return _move_action(ctx.state.position, safe_pos)
        return ctx.navigator.get_action(ctx.state.position, safe_pos, ctx.map, reach_adjacent=True)


def _is_in_safe_zone(ctx: CogasContext) -> bool:
    """Check if agent is within AOE of any cogs structure."""
    pos = ctx.state.position
    # Check hub
    hubs = ctx.map.find(type="hub")
    for apos, _ in hubs:
        if _manhattan(pos, apos) <= JUNCTION_AOE_RANGE:
            return True
    # Check cogs junctions
    junctions = ctx.map.find(type_contains="junction", property_filter={"alignment": "cogs"})
    for jpos, _ in junctions:
        if _manhattan(pos, jpos) <= JUNCTION_AOE_RANGE:
            return True
    # Check cogs junctions
    junctions = ctx.map.find(type_contains="junction", property_filter={"alignment": "cogs"})
    for cpos, _ in junctions:
        if _manhattan(pos, cpos) <= JUNCTION_AOE_RANGE:
            return True
    return False


def _is_in_enemy_aoe(ctx: CogasContext) -> bool:
    """Check if agent is within AOE of any clips structure."""
    pos = ctx.state.position
    for jpos, _ in ctx.map.find(type_contains="junction", property_filter={"alignment": "clips"}):
        if _manhattan(pos, jpos) <= JUNCTION_AOE_RANGE:
            return True
    for cpos, _ in ctx.map.find(type_contains="junction", property_filter={"alignment": "clips"}):
        if _manhattan(pos, cpos) <= JUNCTION_AOE_RANGE:
            return True
    return False


def _nearest_safe_zone(ctx: CogasContext) -> tuple[int, int] | None:
    """Find nearest cogs-aligned structure."""
    pos = ctx.state.position
    candidates: list[tuple[int, tuple[int, int]]] = []

    for apos, _ in ctx.map.find(type="hub"):
        candidates.append((_manhattan(pos, apos), apos))
    for jpos, _ in ctx.map.find(type_contains="junction", property_filter={"alignment": "cogs"}):
        candidates.append((_manhattan(pos, jpos), jpos))
    for cpos, _ in ctx.map.find(type_contains="junction", property_filter={"alignment": "cogs"}):
        candidates.append((_manhattan(pos, cpos), cpos))

    if not candidates:
        return None
    candidates.sort()
    return candidates[0][1]
