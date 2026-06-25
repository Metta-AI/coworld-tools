"""Miner goals — pick resource, mine, deposit."""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from players.cogsguard.cranky.goal import Goal
from players.cogsguard.cranky.navigator import _manhattan
from players.cogsguard._shared.utils import move_toward
from mettagrid.simulator import Action

from .gear import GetGearGoal

if TYPE_CHECKING:
    from players.cogsguard.cranky.context import CogasContext


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

    def _team_can_afford(self, ctx: "CogasContext") -> bool:
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
        return all(team_resources.get(res, 0) >= amt for res, amt in self._gear_cost.items())


RESOURCE_TYPES = ["carbon", "oxygen", "germanium", "silicon"]

_TEAM_SUFFICIENT_THRESHOLD = 100


def _team_resources_sufficient(ctx: "CogasContext") -> bool:
    s = ctx.state
    return (
        s.team_carbon > _TEAM_SUFFICIENT_THRESHOLD
        and s.team_oxygen > _TEAM_SUFFICIENT_THRESHOLD
        and s.team_germanium > _TEAM_SUFFICIENT_THRESHOLD
        and s.team_silicon > _TEAM_SUFFICIENT_THRESHOLD
    )


class ExploreHubGoal(Goal):
    """Explore the hub to discover all 4 extractors before mining.

    Finds the actual hub from observations (not hardcoded position) and
    explores nearby corners to discover extractors.
    """

    name = "ExploreHub"
    # Hub corner offsets from hub center — extractors at these positions
    HUB_OFFSETS = [(-5, -5), (-5, 5), (5, 5), (5, -5)]

    def is_satisfied(self, ctx: CogasContext) -> bool:
        found = sum(1 for r in RESOURCE_TYPES if ctx.map.find(type=f"{r}_extractor"))
        if found >= 4:
            return True
        # Time limit: don't explore forever, but give more time (30 steps)
        return ctx.step > 30

    def execute(self, ctx: CogasContext) -> Optional[Action]:
        # Find actual hub position from observations
        hub_center = self._get_hub_center(ctx)

        corner_idx = ctx.blackboard.get("_hub_corner_idx", ctx.agent_id % 4)
        offsets = self.HUB_OFFSETS
        target = (hub_center[0] + offsets[corner_idx][0], hub_center[1] + offsets[corner_idx][1])

        dist = _manhattan(ctx.state.position, target)
        if dist <= 2:
            corner_idx = (corner_idx + 1) % 4
            ctx.blackboard["_hub_corner_idx"] = corner_idx
            target = (hub_center[0] + offsets[corner_idx][0], hub_center[1] + offsets[corner_idx][1])

        if ctx.trace:
            ctx.trace.nav_target = target
            found = sum(1 for r in RESOURCE_TYPES if ctx.map.find(type=f"{r}_extractor"))
            ctx.trace.activate(self.name, f"corner={corner_idx} found={found}/4 hub={hub_center}")

        # Check dist to avoid navigator returning noop
        new_dist = _manhattan(ctx.state.position, target)
        if new_dist <= 1:
            return _move_toward(ctx.state.position, target)
        return ctx.navigator.get_action(ctx.state.position, target, ctx.map, reach_adjacent=True)

    def _get_hub_center(self, ctx: CogasContext) -> tuple[int, int]:
        """Find hub center from observations, falling back to current position."""
        # Check if we already cached the hub position
        cached_hub = ctx.blackboard.get("_hub_center")
        if cached_hub is not None:
            return cached_hub

        hub = ctx.map.find_nearest(ctx.state.position, type_contains="hub", property_filter={"alignment": ctx.my_team})
        if hub is not None:
            hub_pos, _ = hub
            ctx.blackboard["_hub_center"] = hub_pos
            return hub_pos

        # Fall back to current position if hub not visible yet
        # (agent will explore from where it spawned)
        return ctx.state.position


class PickResourceGoal(Goal):
    """Select a target resource based on team hub needs.

    Prioritizes the resource that the team hub has the least of,
    ensuring balanced gathering for heart production.
    Re-evaluates every 50 steps to adapt to changing needs.
    """

    name = "PickResource"
    REEVALUATE_INTERVAL = 50

    def is_satisfied(self, ctx: CogasContext) -> bool:
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

    def execute(self, ctx: CogasContext) -> Optional[Action]:
        team_resources = {
            "carbon": ctx.state.team_carbon,
            "oxygen": ctx.state.team_oxygen,
            "germanium": ctx.state.team_germanium,
            "silicon": ctx.state.team_silicon,
        }

        available_resources: list[tuple[int, str]] = []
        for resource in RESOURCE_TYPES:
            extractors = ctx.map.find(type=f"{resource}_extractor")
            usable = [
                (pos, e)
                for pos, e in extractors
                if e.properties.get("inventory_amount", -1) != 0 and not _extractor_recently_failed(ctx, pos)
            ]
            if usable:
                available_resources.append((team_resources.get(resource, 0), resource))

        if not available_resources:
            ctx.blackboard["target_resource"] = "carbon"
            ctx.blackboard["_target_resource_step"] = ctx.step
            if ctx.trace:
                ctx.trace.activate(self.name, "no extractors known, defaulting to carbon")
            return None

        available_resources.sort()
        best_resource = available_resources[0][1]

        if ctx.trace:
            ctx.trace.activate(self.name, f"need={best_resource} team={team_resources}")

        ctx.blackboard["target_resource"] = best_resource
        ctx.blackboard["_target_resource_step"] = ctx.step
        return None


def _extractor_recently_failed(ctx: CogasContext, pos: tuple[int, int]) -> bool:
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

    def is_satisfied(self, ctx: CogasContext) -> bool:
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

    def execute(self, ctx: CogasContext) -> Optional[Action]:
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
            if ctx.trace:
                hubs = ctx.map.find(type_contains="hub", property_filter={"alignment": ctx.my_team})
                depot_entity = ctx.map.entities.get(depot_pos)
                print(
                    f"[deposit-debug] agent={ctx.agent_id} t={ctx.step} pos={ctx.state.position}"
                    f" depot={depot_pos} depot_type={depot_entity.type if depot_entity else 'NONE'}"
                    f" depot_align={depot_entity.properties.get('alignment') if depot_entity else 'N/A'}"
                    f" cargo={current_cargo} prev={prev_cargo}"
                    f" hubs={[(p, e.properties.get('alignment')) for p, e in hubs]}"
                )
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

    NEVER satisfied - miners should always mine or explore, never noop.
    """

    name = "MineResource"
    MAX_ATTEMPTS_PER_EXTRACTOR = 3  # Reduced from 5 - fail faster

    def is_satisfied(self, ctx: CogasContext) -> bool:
        # Never satisfied - always mine or explore to avoid noops
        # Even when team hub is well-stocked, keep contributing
        return False

    def execute(self, ctx: CogasContext) -> Optional[Action]:
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

    def _find_extractor(self, ctx: CogasContext, resource: str) -> Optional[tuple[int, int]]:
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


def _find_cogs_depot(ctx: CogasContext) -> tuple[int, int] | None:
    """Find nearest cogs-aligned depot, prioritizing hub."""
    from players.cogsguard.cranky.policy import SPAWN_POS  # noqa: PLC0415

    pos = ctx.state.position

    def recently_failed(p: tuple[int, int]) -> bool:
        failed_step = ctx.blackboard.get(f"deposit_failed_{p}", -9999)
        return ctx.step - failed_step < 100

    for apos, _ in ctx.map.find(type_contains="hub", property_filter={"alignment": ctx.my_team}):
        if not recently_failed(apos):
            return apos

    # Fallback: nearest cogs junction near hub
    candidates: list[tuple[int, tuple[int, int]]] = []
    for jpos, _ in ctx.map.find(type_contains="junction", property_filter={"alignment": "cogs"}):
        if not recently_failed(jpos) and _manhattan(jpos, SPAWN_POS) <= 15:
            candidates.append((_manhattan(pos, jpos), jpos))

    if not candidates:
        # Last resort: navigate to hub area
        return SPAWN_POS
    candidates.sort()
    return candidates[0][1]


_move_toward = move_toward
