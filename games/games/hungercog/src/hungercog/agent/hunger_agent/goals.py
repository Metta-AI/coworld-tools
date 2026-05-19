"""Goals for the Hunger agent."""

from __future__ import annotations

import random as _rng
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from mettagrid.simulator import Action

from .navigator import MOVE_DELTAS, manhattan, move_toward

if TYPE_CHECKING:
    from .entity_map import EntityMap
    from .navigator import Navigator
    from .obs_parser import HungerState


@dataclass
class HungerContext:
    state: HungerState
    map: EntityMap
    blackboard: dict[str, Any]
    navigator: Navigator
    agent_id: int
    step: int


class Goal:
    name: str = "Goal"

    def is_satisfied(self, ctx: HungerContext) -> bool:
        return False

    def execute(self, ctx: HungerContext) -> Action | None:
        return Action(name="noop")


def evaluate_goals(goals: list[Goal], ctx: HungerContext) -> Action:
    for goal in goals:
        if goal.is_satisfied(ctx):
            continue
        action = goal.execute(ctx)
        if action is not None:
            return action
    return Action(name="noop")


# ---------------------------------------------------------------------------
# Shared
# ---------------------------------------------------------------------------


class GetGearGoal(Goal):
    """Navigate to a station and bump it to acquire gear."""

    MAX_BUMPS = 5
    MAX_ATTEMPTS = 80

    def __init__(self, station_type: str, gear_name: str) -> None:
        self.name = f"Get{gear_name.title()}Gear"
        self._station_type = station_type
        self._gear_name = gear_name

    def is_satisfied(self, ctx: HungerContext) -> bool:
        return getattr(ctx.state, self._gear_name, 0) > 0

    def execute(self, ctx: HungerContext) -> Action | None:
        bb = ctx.blackboard
        att_key = f"{self.name}_att"
        bump_key = f"{self.name}_bumps"

        attempts = bb.get(att_key, 0) + 1
        bb[att_key] = attempts
        if attempts > self.MAX_ATTEMPTS:
            bb[att_key] = 0
            return None

        result = ctx.map.find_nearest(ctx.state.position, type=self._station_type)
        if result is None:
            return ctx.navigator.explore(
                ctx.state.position,
                ctx.map,
                bias=["north", "east", "south", "west"][ctx.agent_id % 4],
            )

        station_pos, _ = result
        dist = manhattan(ctx.state.position, station_pos)

        if dist <= 1:
            bumps = bb.get(bump_key, 0) + 1
            bb[bump_key] = bumps
            if bumps > self.MAX_BUMPS:
                bb[bump_key] = 0
                ctx.navigator._cached_path = None
                return ctx.navigator.explore(ctx.state.position, ctx.map)
            return move_toward(ctx.state.position, station_pos)

        bb[bump_key] = 0
        return ctx.navigator.get_action(ctx.state.position, station_pos, ctx.map, reach_adjacent=True)


class ExploreGoal(Goal):
    """Fallback: explore unknown territory."""

    name = "Explore"

    def execute(self, ctx: HungerContext) -> Action | None:
        return ctx.navigator.explore(
            ctx.state.position,
            ctx.map,
            bias=["north", "east", "south", "west"][ctx.agent_id % 4],
        )


# ---------------------------------------------------------------------------
# Prey goals
# ---------------------------------------------------------------------------


class FleeGoal(Goal):
    """Flee from nearby predators (carnivores)."""

    name = "Flee"
    FLEE_RADIUS = 10

    def is_satisfied(self, ctx: HungerContext) -> bool:
        return self._nearest_predator(ctx) is None

    def execute(self, ctx: HungerContext) -> Action | None:
        pred_pos = self._nearest_predator(ctx)
        if pred_pos is None:
            return None
        return _flee_from(ctx.state.position, pred_pos, ctx.map)

    def _nearest_predator(self, ctx: HungerContext) -> tuple[int, int] | None:
        pos = ctx.state.position
        best_pos, best_d = None, self.FLEE_RADIUS + 1
        for epos, e in ctx.map.entities.items():
            if e.type != "agent" or e.properties.get("carnivore", 0) <= 0:
                continue
            d = manhattan(pos, epos)
            if d < best_d:
                best_pos, best_d = epos, d
        return best_pos


class HarvestGoal(Goal):
    """Find and harvest plant objects with food."""

    name = "Harvest"

    def execute(self, ctx: HungerContext) -> Action | None:
        bb = ctx.blackboard
        pos = ctx.state.position
        blacklist = bb.setdefault("Harvest_blacklist_until", {})
        plant_entities = ctx.map.find(type="plant")
        usable = [
            (p, e) for p, e in plant_entities if e.properties.get("food", 0) > 0 and blacklist.get(p, -1) < ctx.step
        ]

        if not usable:
            return ctx.navigator.explore(
                pos,
                ctx.map,
                bias=["north", "east", "south", "west"][ctx.agent_id % 4],
            )

        usable.sort(key=lambda x: manhattan(pos, x[0]))
        target_pos = usable[0][0]
        dist = manhattan(pos, target_pos)

        if dist <= 1:
            last_target = bb.get("Harvest_last_target")
            last_food = bb.get("Harvest_last_food")
            if last_target == target_pos and last_food == ctx.state.food:
                stall_steps = bb.get("Harvest_stall_steps", 0) + 1
            else:
                stall_steps = 0
            bb["Harvest_last_target"] = target_pos
            bb["Harvest_last_food"] = ctx.state.food
            bb["Harvest_stall_steps"] = stall_steps

            # Bumping an empty/depleted plant can loop forever with stale map state.
            # Blacklist the target briefly and force exploration to re-acquire a fresh plant.
            if stall_steps >= 8:
                blacklist[target_pos] = ctx.step + 80
                bb["Harvest_stall_steps"] = 0
                ctx.navigator._cached_path = None
                ctx.navigator._cached_target = None
                return ctx.navigator.explore(
                    pos,
                    ctx.map,
                    bias=["north", "east", "south", "west"][ctx.agent_id % 4],
                )
            return move_toward(pos, target_pos)

        return ctx.navigator.get_action(pos, target_pos, ctx.map, reach_adjacent=True)


# ---------------------------------------------------------------------------
# Predator goals
# ---------------------------------------------------------------------------


class AvoidPredatorGoal(Goal):
    """Avoid other predators when carrying an egg (both lose egg on contact)."""

    name = "AvoidPredator"
    AVOID_RADIUS = 3

    def is_satisfied(self, ctx: HungerContext) -> bool:
        if ctx.state.egg <= 0:
            return True
        return self._nearest_other_predator(ctx) is None

    def execute(self, ctx: HungerContext) -> Action | None:
        pred_pos = self._nearest_other_predator(ctx)
        if pred_pos is None:
            return None
        return _flee_from(ctx.state.position, pred_pos, ctx.map)

    def _nearest_other_predator(self, ctx: HungerContext) -> tuple[int, int] | None:
        pos = ctx.state.position
        best_pos, best_d = None, self.AVOID_RADIUS + 1
        for epos, e in ctx.map.entities.items():
            if e.type != "agent" or e.properties.get("carnivore", 0) <= 0:
                continue
            d = manhattan(pos, epos)
            if 0 < d < best_d:
                best_pos, best_d = epos, d
        return best_pos


class HuntGoal(Goal):
    """Find herbivores and chase them down."""

    name = "Hunt"

    def execute(self, ctx: HungerContext) -> Action | None:
        pos = ctx.state.position
        prey: list[tuple[tuple[int, int], int]] = []
        for epos, e in ctx.map.entities.items():
            if e.type != "agent" or e.properties.get("herbivore", 0) <= 0:
                continue
            prey.append((epos, e.properties.get("food", 0)))

        if not prey:
            return ctx.navigator.explore(
                pos,
                ctx.map,
                bias=["north", "east", "south", "west"][ctx.agent_id % 4],
            )

        # Prefer closer prey, break ties by more food (juicier target)
        prey.sort(key=lambda x: (manhattan(pos, x[0]), -x[1]))
        target_pos = prey[0][0]
        dist = manhattan(pos, target_pos)

        if dist <= 1:
            return move_toward(pos, target_pos)

        return ctx.navigator.get_action(pos, target_pos, ctx.map, reach_adjacent=True)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _flee_from(pos: tuple[int, int], threat: tuple[int, int], map: EntityMap) -> Action:
    """Move away from threat position."""
    dr, dc = pos[0] - threat[0], pos[1] - threat[1]
    candidates: list[tuple[int, str]] = []
    for d, (ddr, ddc) in MOVE_DELTAS.items():
        p = (pos[0] + ddr, pos[1] + ddc)
        if map.is_wall(p) or map.is_structure(p):
            continue
        # Dot product: positive means moving away from threat
        score = ddr * dr + ddc * dc
        candidates.append((score, d))
    if not candidates:
        return Action(name="noop")
    candidates.sort(reverse=True)
    best_score = candidates[0][0]
    best = [d for s, d in candidates if s == best_score]
    return Action(name=f"move_{_rng.choice(best)}")
