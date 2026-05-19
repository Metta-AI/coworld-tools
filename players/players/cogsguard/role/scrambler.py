"""
Scrambler role for CoGsGuard.

Scramblers find enemy-aligned supply depots and scramble them to take control.
With scrambler gear, they get +200 HP.

Strategy:
- Find ALL junctions on the map
- Prioritize scrambling enemy (clips) aligned junctions
- Systematically work through all junctions to take them over
- Check energy before moving to targets
- Retry failed scramble actions up to MAX_RETRIES times
"""

from __future__ import annotations

from typing import Optional

from players.cogsguard._shared.pathfinding import is_traversable
from players.cogsguard._shared.types import CellType
from players.cogsguard._shared.utils import is_adjacent
from mettagrid.simulator import Action

from .policy import DEBUG, CogsguardAgentPolicyImpl
from .types import CogsguardAgentState, Role, StructureType

# Maximum number of times to retry a failed scramble action
MAX_RETRIES = 3
# HP buffer to start returning to the hub before gear is lost.
HP_RETURN_BUFFER = 12


class ScramblerAgentPolicyImpl(CogsguardAgentPolicyImpl):
    """Scrambler agent: scramble enemy supply depots to take control."""

    ROLE = Role.SCRAMBLER

    def execute_role(self, s: CogsguardAgentState) -> Action:
        """Execute scrambler behavior: find and scramble ALL enemy depots.

        Energy-aware behavior:
        - Check if we have enough energy before attempting to move to targets
        - If energy is low, go recharge at the nexus
        - Retry failed scramble actions up to MAX_RETRIES times
        - If gear is lost, go back to base to re-equip
        - If gear acquisition fails repeatedly, get hearts first (gear may require hearts)
        """
        if DEBUG and s.step_count % 100 == 0:
            num_junctions = len(s.get_structures_by_type(StructureType.CHARGER))
            clips_junctions = len(
                [c for c in s.get_structures_by_type(StructureType.CHARGER) if c.alignment == "clips"]
            )
            num_worked = len(s.worked_junctions)
            print(
                f"[A{s.agent_id}] SCRAMBLER: step={s.step_count} heart={s.heart} energy={s.energy} gear={s.scrambler} "
                f"junctions={num_junctions} clips={clips_junctions} scrambled={num_worked}"
            )

        hub_pos = s.get_structure_position(StructureType.HUB)
        if hub_pos is not None:
            dist_to_hub = abs(hub_pos[0] - s.row) + abs(hub_pos[1] - s.col)
            if s.hp <= dist_to_hub + HP_RETURN_BUFFER:
                if DEBUG and s.step_count % 10 == 0:
                    print(f"[A{s.agent_id}] SCRAMBLER: Low HP ({s.hp}), returning to hub")
                return self._do_recharge(s)

        # === Resource check: need both gear AND heart to scramble ===
        has_gear = s.scrambler >= 1
        has_heart = s.heart >= 1

        # Check if last action succeeded (for retry logic)
        # Actions can fail due to insufficient energy - agents auto-regen so just retry
        if s._pending_action_type == "scramble":
            target = s._pending_action_target
            if s.check_action_success():
                if DEBUG:
                    print(f"[A{s.agent_id}] SCRAMBLER: Previous scramble succeeded!")
                if target is not None and self._smart_role_coordinator is not None:
                    hub_pos = s.stations.get("hub")
                    self._smart_role_coordinator.register_junction_alignment(
                        target,
                        None,
                        hub_pos,
                        s.step_count,
                    )
            elif s.should_retry_action(MAX_RETRIES):
                retry_count = s.increment_retry()
                if DEBUG:
                    print(
                        f"[A{s.agent_id}] SCRAMBLER: Scramble failed, retrying ({retry_count}/{MAX_RETRIES}) "
                        f"at {s._pending_action_target}"
                    )
                # Retry the same action - agent will have auto-regenerated some energy
                if has_heart and s._pending_action_target and is_adjacent((s.row, s.col), s._pending_action_target):
                    return self._use_object_at(s, s._pending_action_target)
            else:
                if DEBUG:
                    print(f"[A{s.agent_id}] SCRAMBLER: Scramble failed after {MAX_RETRIES} retries, moving on")
                s.clear_pending_action()

        # If we don't have gear, try to get it
        if not has_gear:
            return self._handle_no_gear(s)

        # If we have gear but no heart, go get hearts
        if not has_heart:
            if DEBUG and s.step_count % 10 == 0:
                print(f"[A{s.agent_id}] SCRAMBLER: Have gear but no heart, getting hearts first")
            return self._get_hearts(s)

        # Find the best enemy depot to scramble (prioritize closest enemy junction)
        target_depot = self._find_best_target(s)

        if target_depot is None:
            # No known enemy depots, explore to find more junctions
            if DEBUG:
                junctions = s.get_structures_by_type(StructureType.CHARGER)
                print(f"[A{s.agent_id}] SCRAMBLER: No targets (total junctions={len(junctions)}), exploring")
            return self._explore_for_junctions(s)

        # Navigate to depot
        # Note: moves require energy. If move fails due to low energy,
        # action failure detection will catch it and we'll retry next step
        # (agents auto-regen energy every step, and regen full near aligned buildings)
        dist = abs(target_depot[0] - s.row) + abs(target_depot[1] - s.col)
        if not is_adjacent((s.row, s.col), target_depot):
            if DEBUG and s.step_count % 10 == 0:
                print(f"[A{s.agent_id}] SCRAMBLER: Moving to junction at {target_depot} (dist={dist})")
            return self._move_towards(s, target_depot, reach_adjacent=True)

        # Scramble the depot by bumping it
        # Mark this junction as worked
        s.worked_junctions[target_depot] = s.step_count

        # Start tracking this scramble attempt
        s.start_action_attempt("scramble", target_depot)

        if DEBUG:
            junction = s.get_structure_at(target_depot)
            alignment = junction.alignment if junction else "unknown"
            print(
                f"[A{s.agent_id}] SCRAMBLER: SCRAMBLING junction at {target_depot} "
                f"(alignment={alignment}, heart={s.heart}, energy={s.energy})!"
            )
        return self._use_object_at(s, target_depot)

    def _handle_no_gear(self, s: CogsguardAgentState) -> Action:
        """Handle behavior when scrambler doesn't have gear.

        Strategy: Go to gear station and wait there until gear is available.
        Can't do much without gear, so just wait.
        """
        station_pos = s.get_structure_position(StructureType.SCRAMBLER_STATION)

        # If we don't know where the station is, explore to find it
        if station_pos is None:
            if DEBUG:
                print(f"[A{s.agent_id}] SCRAMBLER_NO_GEAR: Station unknown, exploring")
            return self._explore(s)

        # Go to gear station
        if not is_adjacent((s.row, s.col), station_pos):
            if DEBUG and s.step_count % 10 == 0:
                print(f"[A{s.agent_id}] SCRAMBLER_NO_GEAR: Moving to station at {station_pos}")
            return self._move_towards(s, station_pos, reach_adjacent=True)

        # At station - keep trying to get gear
        if DEBUG and s.step_count % 10 == 0:
            print(f"[A{s.agent_id}] SCRAMBLER_NO_GEAR: At station, waiting for gear")
        return self._use_object_at(s, station_pos)

    def _get_hearts(self, s: CogsguardAgentState) -> Action:
        """Get hearts from hub (primary source for hearts).

        The hub can produce hearts from resources:
        1. If agent has cargo (minerals), first deposit them by bumping hub
        2. Then bump hub again to get or make a heart
        3. Hub converts 1 of each element into 1 heart (make_heart handler)

        So as long as miners deposit resources, scramblers can get hearts.
        If we've been trying to get hearts for too long, go explore instead.
        """
        # If we've waited more than 40 steps for hearts, go explore instead
        # This prevents getting stuck when commons is out of resources
        if s._heart_wait_start == 0:
            s._heart_wait_start = s.step_count
        if s.step_count - s._heart_wait_start > 40:
            if DEBUG:
                print(f"[A{s.agent_id}] SCRAMBLER: Waited 40+ steps for hearts, exploring instead")
            s._heart_wait_start = 0
            return self._explore_for_junctions(s)

        # Try hub first - it's the primary heart source
        hub_pos = s.get_structure_position(StructureType.HUB)
        if hub_pos is not None:
            if DEBUG and s.step_count % 10 == 0:
                adj = is_adjacent((s.row, s.col), hub_pos)
                cargo = s.total_cargo
                print(f"[A{s.agent_id}] SCRAMBLER: Getting hearts from hub at {hub_pos}, adjacent={adj}, cargo={cargo}")

            # Navigate to hub if not adjacent
            if not is_adjacent((s.row, s.col), hub_pos):
                return self._move_towards(s, hub_pos, reach_adjacent=True)

            # If we have cargo, deposit it first by bumping hub
            if s.total_cargo > 0:
                if DEBUG:
                    print(f"[A{s.agent_id}] SCRAMBLER: Depositing {s.total_cargo} cargo at hub before getting hearts")
                return self._use_object_at(s, hub_pos)

            # Otherwise, bump hub to get hearts
            return self._use_object_at(s, hub_pos)

        # Hub not found - explore to find it
        if DEBUG:
            print(f"[A{s.agent_id}] SCRAMBLER: No hub found, exploring")
        s._heart_wait_start = 0
        return self._explore(s)

    def _find_best_target(self, s: CogsguardAgentState) -> Optional[tuple[int, int]]:
        """Find the best junction to scramble - prioritize enemy (clips) aligned ones.

        Skips junctions that were recently worked on to ensure we visit multiple junctions.
        """
        # Get all known junctions from structures map
        junctions = s.get_structures_by_type(StructureType.CHARGER)

        # How long to ignore a junction after working on it (steps)
        cooldown = 50

        # Collect junctions and sort by distance, skipping recently worked ones
        enemy_junctions: list[tuple[int, tuple[int, int]]] = []
        any_junctions: list[tuple[int, tuple[int, int]]] = []

        if DEBUG and s.step_count % 20 == 1:
            print(f"[A{s.agent_id}] FIND_TARGET: {len(junctions)} junctions in structures map")
            for ch in junctions:
                print(f"  - {ch.position}: alignment={ch.alignment}")

        for junction in junctions:
            pos = junction.position
            dist = abs(pos[0] - s.row) + abs(pos[1] - s.col)

            if DEBUG and s.step_count % 20 == 1:
                print(f"  LOOP junction@{pos}: alignment='{junction.alignment}' dist={dist}")

            # Skip recently worked junctions (only if actually worked before)
            last_worked = s.worked_junctions.get(pos, 0)
            if last_worked > 0 and s.step_count - last_worked < cooldown:
                if DEBUG and s.step_count % 20 == 1:
                    print(f"    SKIP: on cooldown (worked {s.step_count - last_worked} steps ago)")
                continue

            # Skip cogs-aligned junctions (already ours)
            if junction.alignment == "cogs":
                if DEBUG and s.step_count % 20 == 1:
                    print("    SKIP: cogs-aligned (ours)")
                continue

            # Check alignment - prioritize clips (enemy) junctions
            if junction.alignment == "clips":
                if DEBUG and s.step_count % 20 == 1:
                    print("    ADD to enemy_junctions")
                enemy_junctions.append((dist, pos))
            else:
                any_junctions.append((dist, pos))

        if DEBUG and s.step_count % 20 == 1:
            print(f"  enemy_junctions={enemy_junctions} any={any_junctions}")

        # First try enemy junctions (sorted by distance)
        if enemy_junctions:
            enemy_junctions.sort()
            if DEBUG:
                print(f"[A{s.agent_id}] FIND_TARGET: Returning enemy junction at {enemy_junctions[0][1]}")
            target_idx = 0
            if self._smart_role_coordinator is not None:
                scrambler_ids = sorted(
                    agent_id
                    for agent_id, snapshot in self._smart_role_coordinator.agent_snapshots.items()
                    if snapshot.role == Role.SCRAMBLER
                )
                if scrambler_ids:
                    target_idx = scrambler_ids.index(s.agent_id) if s.agent_id in scrambler_ids else 0
            return enemy_junctions[target_idx % len(enemy_junctions)][1]

        # Then try any non-cogs junction (unknown alignment)
        if any_junctions:
            any_junctions.sort()
            if DEBUG:
                print(f"[A{s.agent_id}] FIND_TARGET: Returning any junction at {any_junctions[0][1]}")
            target_idx = 0
            if self._smart_role_coordinator is not None:
                scrambler_ids = sorted(
                    agent_id
                    for agent_id, snapshot in self._smart_role_coordinator.agent_snapshots.items()
                    if snapshot.role == Role.SCRAMBLER
                )
                if scrambler_ids:
                    target_idx = scrambler_ids.index(s.agent_id) if s.agent_id in scrambler_ids else 0
            return any_junctions[target_idx % len(any_junctions)][1]

        return None

    def _explore_for_junctions(self, s: CogsguardAgentState) -> Action:
        """Explore aggressively to find more junctions spread around the map."""
        frontier_action = self._explore_frontier(s)
        if frontier_action is not None:
            return frontier_action

        # Move in a direction based on agent ID and step count to spread out
        # Chargers are spread around the map, so cover different areas
        directions = ["north", "south", "east", "west"]
        # Cycle through directions, spending 20 steps in each direction
        dir_idx = (s.agent_id + s.step_count // 20) % 4
        direction = directions[dir_idx]

        dr, dc = self._move_deltas[direction]
        next_r, next_c = s.row + dr, s.col + dc

        if is_traversable(s, next_r, next_c, CellType):  # type: ignore[arg-type]
            return self._move(direction)

        # Fall back to regular exploration if blocked
        return self._explore(s)
