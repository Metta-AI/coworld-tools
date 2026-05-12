"""Miner goals — pick resource, mine, deposit."""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from cogames_agents.policy.scripted_agent.buggy.goal import Goal
from cogames_agents.policy.scripted_agent.buggy.navigator import _manhattan
from cogames_agents.policy.scripted_agent.utils import move_toward
from mettagrid.simulator import Action

from .gear import GetGearGoal

if TYPE_CHECKING:
    from cogames_agents.policy.scripted_agent.buggy.context import PlankyContext


class GetMinerGearGoal(GetGearGoal):
    """Get miner gear (costs C1 O1 G3 S1 from team hub).

    Miners always get gear regardless of reserves — they produce resources.
    """

    def __init__(self) -> None:
        super().__init__(
            gear_attr="miner_gear",
            station_type="miner",
            goal_name="GetMinerGear",
            gear_cost={"carbon": 1, "oxygen": 1, "germanium": 3, "silicon": 1},
        )

    def _team_can_afford(self, ctx: "PlankyContext") -> bool:
        """Miners always get gear — they're the resource producers.

        But skip if team hub is already well-stocked (no need to mine).
        """
        if _team_resources_sufficient(ctx):
            return False
        if not self._gear_cost:
            return True
        s = ctx.state
        team_resources = {
            "carbon": s.team_carbon,
            "oxygen": s.team_oxygen,
            "germanium": s.team_germanium,
            "silicon": s.team_silicon,
        }
        # No reserve requirement for miners — just need the cost
        return all(team_resources.get(res, 0) >= amt for res, amt in self._gear_cost.items())


# Resource types that can be mined
RESOURCE_TYPES = ["carbon", "oxygen", "germanium", "silicon"]

# When the team hub has more than this amount of every resource, stop mining.
_TEAM_SUFFICIENT_THRESHOLD = 100


def _team_resources_sufficient(ctx: "PlankyContext") -> bool:
    """Return True when the team hub has >_TEAM_SUFFICIENT_THRESHOLD of every resource."""
    s = ctx.state
    return (
        s.team_carbon > _TEAM_SUFFICIENT_THRESHOLD
        and s.team_oxygen > _TEAM_SUFFICIENT_THRESHOLD
        and s.team_germanium > _TEAM_SUFFICIENT_THRESHOLD
        and s.team_silicon > _TEAM_SUFFICIENT_THRESHOLD
    )


class ExploreHubGoal(Goal):
    """Explore the hub to discover all 4 extractors before mining.

    Extractors are at hub corners: (±5, ±5) from center.
    Each miner visits corners in a rotated order based on agent_id.
    """

    name = "ExploreHub"
    # Hub corner offsets from SPAWN_POS — extractors at these positions
    HUB_OFFSETS = [(-5, -5), (-5, 5), (5, 5), (5, -5)]

    def is_satisfied(self, ctx: PlankyContext) -> bool:
        found = sum(1 for r in RESOURCE_TYPES if ctx.map.find(type=f"{r}_extractor"))
        if found >= 4:
            return True
        # Time limit: don't explore forever
        return ctx.step > 15

    def execute(self, ctx: PlankyContext) -> Optional[Action]:
        from cogames_agents.policy.scripted_agent.buggy.policy import SPAWN_POS  # noqa: PLC0415

        corner_idx = ctx.blackboard.get("_hub_corner_idx", ctx.agent_id % 4)
        offsets = self.HUB_OFFSETS
        target = (SPAWN_POS[0] + offsets[corner_idx][0], SPAWN_POS[1] + offsets[corner_idx][1])

        dist = _manhattan(ctx.state.position, target)
        if dist <= 2:
            corner_idx = (corner_idx + 1) % 4
            ctx.blackboard["_hub_corner_idx"] = corner_idx
            target = (SPAWN_POS[0] + offsets[corner_idx][0], SPAWN_POS[1] + offsets[corner_idx][1])

        if ctx.trace:
            ctx.trace.nav_target = target
            found = sum(1 for r in RESOURCE_TYPES if ctx.map.find(type=f"{r}_extractor"))
            ctx.trace.activate(self.name, f"corner={corner_idx} found={found}/4")

        return ctx.navigator.get_action(ctx.state.position, target, ctx.map, reach_adjacent=True)


class PickResourceGoal(Goal):
    """Select a target resource based on team hub needs.

    Prioritizes the resource that the team hub has the least of,
    ensuring balanced gathering for heart production.
    Re-evaluates every 50 steps to adapt to changing needs.
    """

    name = "PickResource"
    REEVALUATE_INTERVAL = 50

    def is_satisfied(self, ctx: PlankyContext) -> bool:
        # Don't bother picking a resource if team hub is well-stocked
        if _team_resources_sufficient(ctx):
            return True

        if "target_resource" not in ctx.blackboard:
            return False

        # Re-evaluate periodically to ensure we're mining what's needed
        last_pick = ctx.blackboard.get("_target_resource_step", 0)
        if ctx.step - last_pick >= self.REEVALUATE_INTERVAL:
            # Clear to force re-evaluation
            ctx.blackboard.pop("target_resource", None)
            return False

        return True

    def execute(self, ctx: PlankyContext) -> Optional[Action]:
        # Get team resource levels
        team_resources = {
            "carbon": ctx.state.team_carbon,
            "oxygen": ctx.state.team_oxygen,
            "germanium": ctx.state.team_germanium,
            "silicon": ctx.state.team_silicon,
        }

        # Find resources with available extractors
        available_resources: list[tuple[int, str]] = []
        for resource in RESOURCE_TYPES:
            extractors = ctx.map.find(type=f"{resource}_extractor")
            usable = [
                (pos, e)
                for pos, e in extractors
                if e.properties.get("inventory_amount", -1) != 0 and not _extractor_recently_failed(ctx, pos)
            ]
            if usable:
                # Score by team amount (lower = higher priority)
                available_resources.append((team_resources.get(resource, 0), resource))

        if not available_resources:
            # No extractors known — pick carbon as default, MineResource will explore
            ctx.blackboard["target_resource"] = "carbon"
            ctx.blackboard["_target_resource_step"] = ctx.step
            if ctx.trace:
                ctx.trace.activate(self.name, "no extractors known, defaulting to carbon")
            return Action(name="noop")

        # Pick the resource the team hub has least of (that we can mine)
        available_resources.sort()
        best_resource = available_resources[0][1]

        if ctx.trace:
            ctx.trace.activate(self.name, f"need={best_resource} team={team_resources}")

        ctx.blackboard["target_resource"] = best_resource
        ctx.blackboard["_target_resource_step"] = ctx.step
        return Action(name="noop")


def _extractor_recently_failed(ctx: PlankyContext, pos: tuple[int, int]) -> bool:
    """Check if we recently failed to mine from this extractor."""
    failed_step = ctx.blackboard.get(f"mine_failed_{pos}", -9999)
    return ctx.step - failed_step < 100  # 100 step cooldown - extractors may refill


class DepositCargoGoal(Goal):
    """Deposit resources at nearest cogs-aligned building when cargo is reasonably full.

    Triggers when cargo is >= 50% full (or >= 10 resources for small capacity).
    Once triggered, keeps depositing until cargo is EMPTY.
    Tracks attempts and marks depots as failed if cargo doesn't decrease.
    """

    name = "DepositCargo"
    MAX_ATTEMPTS_PER_DEPOT = 5

    def is_satisfied(self, ctx: PlankyContext) -> bool:
        cargo = ctx.state.cargo_total

        # If we're currently depositing (flag set), keep going until empty
        if ctx.blackboard.get("_depositing", False):
            if cargo == 0:
                ctx.blackboard["_depositing"] = False
                return True
            return False  # Keep depositing until empty

        # Not currently depositing - check if we should start
        # Deposit when at least 50% full (but always deposit if cargo == capacity)
        capacity = ctx.state.cargo_capacity
        threshold = max(2, capacity // 2)

        if cargo >= threshold:
            ctx.blackboard["_depositing"] = True
            return False  # Start depositing

        return True  # Don't need to deposit yet

    def execute(self, ctx: PlankyContext) -> Optional[Action]:
        # Track cargo to detect successful deposit
        prev_cargo = ctx.blackboard.get("prev_deposit_cargo", ctx.state.cargo_total)
        current_cargo = ctx.state.cargo_total
        ctx.blackboard["prev_deposit_cargo"] = current_cargo

        # Find nearest cogs depot
        depot_pos = _find_cogs_depot(ctx)
        if depot_pos is None:
            return ctx.navigator.explore(ctx.state.position, ctx.map)

        if ctx.trace:
            ctx.trace.nav_target = depot_pos

        dist = _manhattan(ctx.state.position, depot_pos)
        if dist <= 1:
            # Adjacent to depot - track attempts
            attempts_key = f"deposit_attempts_{depot_pos}"
            attempts = ctx.blackboard.get(attempts_key, 0) + 1

            # Reset if cargo decreased (deposit succeeded)
            if current_cargo < prev_cargo:
                ctx.blackboard[attempts_key] = 0
            else:
                ctx.blackboard[attempts_key] = attempts

                if attempts > self.MAX_ATTEMPTS_PER_DEPOT:
                    # Mark as failed temporarily
                    ctx.blackboard[f"deposit_failed_{depot_pos}"] = ctx.step
                    ctx.blackboard[attempts_key] = 0
                    if ctx.trace:
                        ctx.trace.activate(self.name, f"giving up on {depot_pos}")
                    return ctx.navigator.explore(ctx.state.position, ctx.map)

            return _move_toward(ctx.state.position, depot_pos)

        # Not adjacent - reset attempts
        ctx.blackboard[f"deposit_attempts_{depot_pos}"] = 0
        return ctx.navigator.get_action(ctx.state.position, depot_pos, ctx.map, reach_adjacent=True)


class MineResourceGoal(Goal):
    """Navigate to extractor for target_resource and bump it.

    Tracks attempts at each extractor and marks them as failed if
    cargo doesn't increase after several bumps (extractor empty/broken).
    """

    name = "MineResource"
    MAX_ATTEMPTS_PER_EXTRACTOR = 3  # Reduced from 5 - fail faster

    def is_satisfied(self, ctx: PlankyContext) -> bool:
        # Stop mining when the team hub is well-stocked
        if _team_resources_sufficient(ctx) and ctx.state.cargo_total == 0:
            if ctx.trace:
                ctx.trace.skip(self.name, "team resources sufficient, idling")
            return True
        return False

    def execute(self, ctx: PlankyContext) -> Optional[Action]:
        target_resource = ctx.blackboard.get("target_resource", "carbon")

        # Track cargo to detect successful mining
        prev_cargo = ctx.blackboard.get("prev_cargo", 0)
        current_cargo = ctx.state.cargo_total
        ctx.blackboard["prev_cargo"] = current_cargo

        # Find nearest usable extractor for this resource
        target_pos = self._find_extractor(ctx, target_resource)

        if target_pos is None:
            # Try any resource type
            for resource in RESOURCE_TYPES:
                if resource == target_resource:
                    continue
                target_pos = self._find_extractor(ctx, resource)
                if target_pos:
                    ctx.blackboard["target_resource"] = resource
                    ctx.blackboard["_target_resource_step"] = ctx.step
                    break

        if target_pos is None:
            # No extractors found — explore in agent-specific direction to discover them
            ctx.blackboard.pop("target_resource", None)
            directions = ["north", "east", "south", "west"]
            return ctx.navigator.explore(
                ctx.state.position,
                ctx.map,
                direction_bias=directions[ctx.agent_id % 4],
            )

        if ctx.trace:
            ctx.trace.nav_target = target_pos

        dist = _manhattan(ctx.state.position, target_pos)
        if dist <= 1:
            # Adjacent to extractor — track attempts
            attempts_key = f"mine_attempts_{target_pos}"
            attempts = ctx.blackboard.get(attempts_key, 0) + 1

            # Reset attempts if cargo increased (mining succeeded)
            if current_cargo > prev_cargo:
                ctx.blackboard[attempts_key] = 0
            else:
                ctx.blackboard[attempts_key] = attempts

                if attempts > self.MAX_ATTEMPTS_PER_EXTRACTOR:
                    # Mark as failed permanently for this episode
                    ctx.blackboard[f"mine_failed_{target_pos}"] = ctx.step
                    ctx.blackboard[attempts_key] = 0
                    # Also clear target resource to force re-evaluation
                    ctx.blackboard.pop("target_resource", None)
                    if ctx.trace:
                        ctx.trace.activate(self.name, f"giving up on {target_pos}")
                    return ctx.navigator.explore(
                        ctx.state.position,
                        ctx.map,
                        direction_bias=["north", "east", "south", "west"][ctx.agent_id % 4],
                    )

            return _move_toward(ctx.state.position, target_pos)

        # Don't reset attempts when moving away - only reset on successful mine
        return ctx.navigator.get_action(ctx.state.position, target_pos, ctx.map, reach_adjacent=True)

    def _find_extractor(self, ctx: PlankyContext, resource: str) -> Optional[tuple[int, int]]:
        """Find nearest usable extractor."""
        extractors = ctx.map.find(type=f"{resource}_extractor")
        usable = [
            (pos, e)
            for pos, e in extractors
            if e.properties.get("inventory_amount", -1) != 0 and not _extractor_recently_failed(ctx, pos)
        ]

        if not usable:
            return None

        # Sort by distance to agent
        usable.sort(key=lambda x: _manhattan(ctx.state.position, x[0]))
        return usable[0][0]


def _find_cogs_depot(ctx: PlankyContext) -> tuple[int, int] | None:
    """Find nearest cogs-aligned depot, prioritizing the hub."""
    from cogames_agents.policy.scripted_agent.buggy.policy import SPAWN_POS  # noqa: PLC0415

    pos = ctx.state.position

    def recently_failed(p: tuple[int, int]) -> bool:
        failed_step = ctx.blackboard.get(f"deposit_failed_{p}", -9999)
        return ctx.step - failed_step < 100

    # Prioritize hubs
    for apos, _ in ctx.map.find(type="hub"):
        if not recently_failed(apos):
            return apos

    # Fallback: nearest cogs junction/charger
    candidates: list[tuple[int, tuple[int, int]]] = []
    for jpos, _ in ctx.map.find(type_contains="junction", property_filter={"alignment": "cogs"}):
        if not recently_failed(jpos):
            candidates.append((_manhattan(pos, jpos), jpos))
    for cpos, _ in ctx.map.find(type_contains="charger", property_filter={"alignment": "cogs"}):
        if not recently_failed(cpos):
            candidates.append((_manhattan(pos, cpos), cpos))

    if not candidates:
        # Last resort: navigate to hub area even if we haven't discovered a depot yet.
        return SPAWN_POS
    candidates.sort()
    return candidates[0][1]


_move_toward = move_toward
