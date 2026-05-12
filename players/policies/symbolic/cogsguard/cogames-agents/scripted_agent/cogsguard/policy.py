"""
CoGsGuard Scripted Agent - Vibe-based multi-agent policy.

Agents use vibes to determine their behavior:
- default: do nothing (noop)
- gear: pick a role via smart coordinator, change vibe to that role
- miner/scout/aligner/scrambler: get gear if needed, then execute role behavior
- heart: do nothing (noop)
"""

from __future__ import annotations

import random
from collections import deque
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Optional

import numpy as np

from cogames_agents.policy.evolution.cogsguard.evolutionary_coordinator import (
    EvolutionaryRoleCoordinator,
)
from cogames_agents.policy.scripted_agent.common.geometry import is_within_observation_shape
from cogames_agents.policy.scripted_agent.pathfinding import (
    compute_goal_cells,
    shortest_path,
)
from cogames_agents.policy.scripted_agent.pathfinding import (
    is_traversable as path_is_traversable,
)
from cogames_agents.policy.scripted_agent.pathfinding import (
    is_within_bounds as path_is_within_bounds,
)
from cogames_agents.policy.scripted_agent.types import CellType, ObjectState, ParsedObservation
from cogames_agents.policy.scripted_agent.utils import (
    add_inventory_token,
    change_vibe_action,
    has_type_tag,
    is_adjacent,
    is_station,
    is_wall,
)
from cogames_agents.policy.scripted_agent.utils import (
    parse_observation as utils_parse_observation,
)
from mettagrid.config.mettagrid_config import CardinalDirection
from mettagrid.mettagrid_c import dtype_actions
from mettagrid.policy.policy import MultiAgentPolicy, StatefulAgentPolicy, StatefulPolicyImpl
from mettagrid.policy.policy_env_interface import PolicyEnvInterface
from mettagrid.simulator import Action, AgentObservation, ObservationToken

from .types import (
    ROLE_TO_GEAR,
    ROLE_TO_STATION,
    CogsguardAgentState,
    CogsguardPhase,
    Role,
    StructureInfo,
    StructureType,
)

# Vibe names for role selection
ROLE_VIBES = ["scout", "miner", "aligner", "scrambler"]
VIBE_TO_ROLE = {
    "miner": Role.MINER,
    "scout": Role.SCOUT,
    "aligner": Role.ALIGNER,
    "scrambler": Role.SCRAMBLER,
}
SMART_ROLE_SWITCH_COOLDOWN = 120
SCRAMBLER_GEAR_PRIORITY_STEPS = 25
SMART_ROLE_REASSESS_INTERVAL = 25
SMART_ROLE_REASSESS_PROBABILITY = 0.25
SMART_ROLE_STARTUP_ORDER = ("scout", "miner", "aligner", "scrambler")


def _agent_rng_seed(agent_id: int, *, salt: int = 0) -> int:
    return 0xC0A15EED + salt + (agent_id + 1) * 1_000_003


if TYPE_CHECKING:
    from mettagrid.simulator.interface import AgentObservation

# Debug flag - set to True to see detailed agent behavior
DEBUG = False
GEAR_SEARCH_OFFSETS = [
    # Compound places stations ~4-5 rows below the hub, spaced by 2 columns.
    # Search those slots first to capture early gear windows.
    (4, -4),
    (4, -2),
    (4, 0),
    (4, 2),
    (4, 4),
    (5, -4),
    (5, -2),
    (5, 0),
    (5, 2),
    (5, 4),
    # Fallbacks for variations/tighter layouts.
    (6, -4),
    (6, 0),
    (6, 4),
    (0, 5),
    (5, 0),
    (0, -5),
    (-5, 0),
]


@dataclass
class SmartRoleAgentSnapshot:
    """Lightweight snapshot for smart-role coordination."""

    step: int
    role: Role
    has_gear: bool
    structures_known: tuple[str, ...]
    structures_seen: int
    heart_count: int
    influence_count: int
    junction_alignment_counts: dict[str, int]


@dataclass
class SmartRoleCoordinator:
    """Shared coordinator for future smart-role selection."""

    num_agents: int
    agent_snapshots: dict[int, SmartRoleAgentSnapshot] = field(default_factory=dict)
    junction_alignment_overrides: dict[tuple[int, int], Optional[str]] = field(default_factory=dict)
    station_offsets: dict[str, tuple[int, int]] = field(default_factory=dict)
    recent_scrambles: dict[tuple[int, int], int] = field(default_factory=dict)
    agent_rngs: dict[int, random.Random] = field(default_factory=dict)

    def update_agent(self, s: CogsguardAgentState) -> None:
        hub_pos = s.stations.get("hub")
        if hub_pos is not None:
            self._record_known_junctions(s, hub_pos)
            self._record_known_stations(s, hub_pos)
            self._apply_alignment_overrides(s, hub_pos)
            self._apply_station_overrides(s, hub_pos)
        junction_counts = {"c": 0, "clips": 0, "neutral": 0, "unknown": 0}
        for struct in s.get_structures_by_type(StructureType.CHARGER):
            bucket = self._normalize_alignment(struct.alignment)
            junction_counts[bucket] += 1

        known_structures = tuple(sorted({struct.structure_type.value for struct in s.structures.values()}))
        self.agent_snapshots[s.agent_id] = SmartRoleAgentSnapshot(
            step=s.step_count,
            role=s.role,
            has_gear=s.has_gear(),
            structures_known=known_structures,
            structures_seen=len(s.structures),
            heart_count=s.heart,
            influence_count=s.influence,
            junction_alignment_counts=junction_counts,
        )

    def register_junction_alignment(
        self,
        pos: tuple[int, int],
        alignment: Optional[str],
        hub_pos: Optional[tuple[int, int]],
        step: Optional[int] = None,
    ) -> None:
        if hub_pos is None:
            return
        offset = (pos[0] - hub_pos[0], pos[1] - hub_pos[1])
        self.junction_alignment_overrides[offset] = alignment
        if step is None:
            return
        if alignment is None:
            self.recent_scrambles[offset] = step
        elif alignment == "cogs":
            self.recent_scrambles.pop(offset, None)

    def recent_scramble_targets(
        self,
        hub_pos: Optional[tuple[int, int]],
        step: int,
        *,
        max_age: int = 200,
    ) -> list[tuple[int, int]]:
        if hub_pos is None:
            return []
        targets: list[tuple[int, int]] = []
        stale_offsets: list[tuple[int, int]] = []
        for offset, scramble_step in self.recent_scrambles.items():
            if step - scramble_step > max_age:
                stale_offsets.append(offset)
                continue
            targets.append((hub_pos[0] + offset[0], hub_pos[1] + offset[1]))
        for offset in stale_offsets:
            self.recent_scrambles.pop(offset, None)
        return targets

    def _record_known_junctions(self, s: CogsguardAgentState, hub_pos: tuple[int, int]) -> None:
        for junction in s.get_structures_by_type(StructureType.CHARGER):
            offset = (junction.position[0] - hub_pos[0], junction.position[1] - hub_pos[1])
            if offset not in self.junction_alignment_overrides and junction.alignment is not None:
                self.junction_alignment_overrides[offset] = junction.alignment

    def _record_known_stations(self, s: CogsguardAgentState, hub_pos: tuple[int, int]) -> None:
        for name, pos in s.stations.items():
            if pos is None or name in ("hub", "junction"):
                continue
            if name not in self.station_offsets:
                self.station_offsets[name] = (pos[0] - hub_pos[0], pos[1] - hub_pos[1])

    def _apply_station_overrides(self, s: CogsguardAgentState, hub_pos: tuple[int, int]) -> None:
        if not self.station_offsets:
            return
        for name, offset in self.station_offsets.items():
            if s.stations.get(name) is not None:
                continue
            pos = (hub_pos[0] + offset[0], hub_pos[1] + offset[1])
            if not (0 <= pos[0] < s.map_height and 0 <= pos[1] < s.map_width):
                continue
            s.stations[name] = pos
            if pos not in s.structures:
                s.structures[pos] = StructureInfo(
                    position=pos,
                    structure_type=self._station_structure_type(name),
                    name=name,
                    last_seen_step=s.step_count,
                )
            s.occupancy[pos[0]][pos[1]] = CellType.OBSTACLE.value

    def _apply_alignment_overrides(self, s: CogsguardAgentState, hub_pos: tuple[int, int]) -> None:
        if not self.junction_alignment_overrides:
            return
        for offset, alignment in self.junction_alignment_overrides.items():
            pos = (hub_pos[0] + offset[0], hub_pos[1] + offset[1])
            if not (0 <= pos[0] < s.map_height and 0 <= pos[1] < s.map_width):
                continue
            struct = s.structures.get(pos)
            if struct is None:
                s.structures[pos] = StructureInfo(
                    position=pos,
                    structure_type=StructureType.CHARGER,
                    name="junction",
                    last_seen_step=s.step_count,
                    alignment=alignment,
                )
                s.occupancy[pos[0]][pos[1]] = CellType.OBSTACLE.value
            elif struct.structure_type == StructureType.CHARGER:
                if struct.last_seen_step == s.step_count:
                    continue
                if struct.alignment != alignment:
                    struct.alignment = alignment

        if s.supply_depots:
            for idx, (pos, _alignment) in enumerate(s.supply_depots):
                offset = (pos[0] - hub_pos[0], pos[1] - hub_pos[1])
                if offset in self.junction_alignment_overrides:
                    s.supply_depots[idx] = (pos, self.junction_alignment_overrides[offset])

    @staticmethod
    def _station_structure_type(name: str) -> StructureType:
        return {
            "miner": StructureType.MINER_STATION,
            "scout": StructureType.SCOUT_STATION,
            "aligner": StructureType.ALIGNER_STATION,
            "scrambler": StructureType.SCRAMBLER_STATION,
            "chest": StructureType.CHEST,
        }.get(name, StructureType.UNKNOWN)

    @staticmethod
    def _normalize_alignment(alignment: Optional[str]) -> str:
        if alignment is None or alignment == "neutral":
            return "neutral"
        if alignment in ("c", "clips"):
            return alignment
        return "unknown"

    def choose_role(self, agent_id: int) -> str:
        """Pick a role vibe based on aggregated snapshots."""
        snapshot = self.agent_snapshots.get(agent_id)
        if snapshot is None:
            return SMART_ROLE_STARTUP_ORDER[agent_id % len(SMART_ROLE_STARTUP_ORDER)]

        structures_known = self._aggregate_structures()
        if "hub" not in structures_known:
            return SMART_ROLE_STARTUP_ORDER[agent_id % len(SMART_ROLE_STARTUP_ORDER)]

        role_counts = self._aggregate_role_counts()
        if role_counts.get("scout", 0) == 0:
            return "scout"
        if role_counts.get("miner", 0) == 0:
            return "miner"

        junction_counts = self._aggregate_junction_counts()
        known_junctions = sum(junction_counts.values()) - junction_counts["unknown"]
        if known_junctions == 0:
            return "scout"

        if role_counts.get("scrambler", 0) == 0:
            return "scrambler"
        if role_counts.get("aligner", 0) == 0:
            return "aligner"

        if junction_counts["clips"] > 0 and role_counts.get("scrambler", 0) <= role_counts.get("aligner", 0):
            return "scrambler"
        if junction_counts["neutral"] > 0:
            return "aligner"

        if self._aggregate_structures_seen() < 10:
            return "scout"

        stochastic_role = self._maybe_stochastic_reassess(
            agent_id=agent_id,
            step=snapshot.step,
            role_counts=role_counts,
            junction_counts=junction_counts,
        )
        if stochastic_role is not None:
            return stochastic_role
        return "miner"

    def _maybe_stochastic_reassess(
        self,
        *,
        agent_id: int,
        step: int,
        role_counts: dict[str, int],
        junction_counts: dict[str, int],
    ) -> Optional[str]:
        # Periodic, bounded stochastic reassessment keeps gear-role behavior adaptive
        # without introducing high-frequency switching noise.
        if step <= 0 or step % SMART_ROLE_REASSESS_INTERVAL != 0:
            return None
        rng = self._rng_for_agent(agent_id)
        if rng.random() >= SMART_ROLE_REASSESS_PROBABILITY:
            return None

        weighted_roles = ["miner", "miner", "scout"]
        if junction_counts.get("clips", 0) > 0:
            weighted_roles.append("scrambler")
        if junction_counts.get("neutral", 0) > 0:
            weighted_roles.append("aligner")

        for role in ROLE_VIBES:
            if role_counts.get(role, 0) == 0:
                weighted_roles.extend((role, role))

        return rng.choice(weighted_roles)

    def _rng_for_agent(self, agent_id: int) -> random.Random:
        rng = self.agent_rngs.get(agent_id)
        if rng is None:
            rng = random.Random(_agent_rng_seed(agent_id, salt=17))
            self.agent_rngs[agent_id] = rng
        return rng

    def _aggregate_junction_counts(self) -> dict[str, int]:
        totals = {"c": 0, "clips": 0, "neutral": 0, "unknown": 0}
        for snapshot in self.agent_snapshots.values():
            for key in totals:
                totals[key] = max(totals[key], snapshot.junction_alignment_counts.get(key, 0))
        return totals

    def aligned_junction_count(self) -> int:
        return self._aggregate_junction_counts().get("c", 0)

    def _aggregate_structures(self) -> set[str]:
        structures: set[str] = set()
        for snapshot in self.agent_snapshots.values():
            structures.update(snapshot.structures_known)
        return structures

    def _aggregate_role_counts(self) -> dict[str, int]:
        counts = {role: 0 for role in ROLE_VIBES}
        for snapshot in self.agent_snapshots.values():
            role_name = snapshot.role.value
            if role_name in counts:
                counts[role_name] += 1
        return counts

    def _aggregate_role_gear_counts(self) -> dict[str, int]:
        counts = {role: 0 for role in ROLE_VIBES}
        for snapshot in self.agent_snapshots.values():
            role_name = snapshot.role.value
            if role_name in counts and snapshot.has_gear:
                counts[role_name] += 1
        return counts

    def get_role_gear_counts(self) -> dict[str, int]:
        return self._aggregate_role_gear_counts()

    def get_role_counts(self) -> dict[str, int]:
        return self._aggregate_role_counts()

    def _aggregate_heart_count(self) -> int:
        return sum(snapshot.heart_count for snapshot in self.agent_snapshots.values())

    def _aggregate_influence_count(self) -> int:
        return sum(snapshot.influence_count for snapshot in self.agent_snapshots.values())

    def _aggregate_structures_seen(self) -> int:
        return max((snap.structures_seen for snap in self.agent_snapshots.values()), default=0)


class CogsguardAgentPolicyImpl(StatefulPolicyImpl[CogsguardAgentState]):
    """Base policy implementation for CoGsGuard agents.

    Handles common behavior like gear acquisition. Role-specific behavior
    is implemented by overriding execute_role().
    """

    # Subclasses set this
    ROLE: Role = Role.MINER

    def __init__(
        self,
        policy_env_info: PolicyEnvInterface,
        agent_id: int,
        role: Role,
        smart_role_coordinator: Optional[SmartRoleCoordinator] = None,
        evolutionary_role_coordinator: Optional[EvolutionaryRoleCoordinator] = None,
        use_evolutionary_roles: bool = False,
    ):
        self._agent_id = agent_id
        self._role = role
        self._policy_env_info = policy_env_info
        self._smart_role_coordinator = smart_role_coordinator
        self._evolutionary_role_coordinator = evolutionary_role_coordinator
        self._use_evolutionary_roles = use_evolutionary_roles
        # Some env configs omit move_energy_cost; default to 1 to match simulator fallback.
        self._move_energy_cost = getattr(policy_env_info, "move_energy_cost", 1)

        # Observation grid half-ranges
        self._obs_hr = policy_env_info.obs_height // 2
        self._obs_wr = policy_env_info.obs_width // 2

        # Action lookup
        self._action_names = policy_env_info.all_action_names
        self._action_set = set(self._action_names)
        self._vibe_names = [
            name[len("change_vibe_") :] for name in self._action_names if name.startswith("change_vibe_")
        ]
        self._move_deltas = {
            "north": (-1, 0),
            "south": (1, 0),
            "east": (0, 1),
            "west": (0, -1),
        }

        # Feature name sets for observation parsing
        self._spatial_feature_names = {"tag"}
        self._agent_feature_key_by_name = {"agent:group": "agent_group", "agent:frozen": "agent_frozen"}
        self._protocol_input_prefix = "protocol_input:"
        self._protocol_output_prefix = "protocol_output:"

        # Cache tag names on first use
        self._tag_names: dict[int, str] = {}
        self._rng = random.Random(_agent_rng_seed(agent_id, salt=31))

    def _noop(self) -> Action:
        return Action(name="noop")

    def _has_vibe(self, vibe_name: str) -> bool:
        return vibe_name in self._vibe_names

    def _choose_role_vibe(self, s: CogsguardAgentState) -> str:
        if self._use_evolutionary_roles and self._evolutionary_role_coordinator is not None:
            return self._evolutionary_role_coordinator.choose_vibe(s.agent_id, s.step_count)
        if self._smart_role_coordinator is None:
            return self._rng.choice(ROLE_VIBES)
        return self._smart_role_coordinator.choose_role(s.agent_id)

    def _move(self, direction: str) -> Action:
        action_name = f"move_{direction}"
        if action_name in self._action_set:
            return Action(name=action_name)
        return self._noop()

    def initial_agent_state(self) -> CogsguardAgentState:
        """Initialize state for this agent.

        IMPORTANT: Positions are tracked RELATIVE to the agent's starting position.
        - Agent starts at (0, 0) in internal coordinates
        - All discovered object positions are relative to this origin
        - The actual map size doesn't matter - we only use relative offsets
        - Occupancy grid is centered at (grid_size/2, grid_size/2) to allow negative relative positions
        """
        self._tag_names = self._policy_env_info.tag_id_to_name

        # Use a grid large enough for typical exploration range
        # Grid center is the agent's starting position (0, 0) in relative coords
        # But stored at grid_center to allow negative relative positions
        grid_size = 200
        grid_center = grid_size // 2

        state = CogsguardAgentState(
            agent_id=self._agent_id,
            role=self._role,
            map_height=grid_size,
            map_width=grid_size,
            occupancy=[[CellType.FREE.value] * grid_size for _ in range(grid_size)],
            explored=[[False] * grid_size for _ in range(grid_size)],
            # Start at (0, 0) relative - stored at grid center for negative offset support
            row=grid_center,
            col=grid_center,
        )

        if self._move_energy_cost is not None:
            state.MOVE_ENERGY_COST = self._move_energy_cost
        return state

    def step_with_state(self, obs: AgentObservation, s: CogsguardAgentState) -> tuple[Action, CogsguardAgentState]:
        """Main step function."""
        s.step_count += 1
        s.current_obs = obs
        s.agent_occupancy.clear()

        # Read inventory
        self._read_inventory(s, obs)

        # Update position from last action
        self._update_agent_position(s)

        # Parse observation
        parsed = self._parse_observation(s, obs)

        # Update map knowledge
        self._update_occupancy_and_discover(s, parsed)

        if self._smart_role_coordinator is not None:
            self._smart_role_coordinator.update_agent(s)

        # Update phase
        self._update_phase(s)

        # Execute current phase
        action = self._execute_phase(s)

        # Debug logging
        if DEBUG and s.step_count <= 50:  # Only first 50 steps per agent
            gear_status = "HAS_GEAR" if s.has_gear() else "NO_GEAR"
            nexus_pos = s.get_structure_position(StructureType.HUB) or "NOT_FOUND"
            print(
                f"[A{s.agent_id}] Step {s.step_count}: vibe={s.current_vibe} role={s.role.value} | "
                f"Phase={s.phase.value} | {gear_status} | "
                f"Energy={s.energy} | "
                f"Pos=({s.row},{s.col}) | "
                f"Nexus@{nexus_pos} | "
                f"Action={action.name}"
            )

        s.last_action = action
        return action, s

    def _read_inventory(self, s: CogsguardAgentState, obs: AgentObservation) -> None:
        """Read inventory, vibe, and last executed action from observation."""
        inv = {}
        vibe_id = 0  # Default vibe ID
        last_action_id: Optional[int] = None
        center_r, center_c = self._obs_hr, self._obs_wr
        token_value_base = None
        for tok in obs.tokens:
            feature_name = tok.feature.name
            if feature_name == "last_action":
                last_action_id = tok.value
                continue

            if tok.location == (center_r, center_c):
                if feature_name.startswith("inv:"):
                    if token_value_base is None:
                        token_value_base = int(tok.feature.normalization)
                    add_inventory_token(inv, feature_name, tok.value, token_value_base=token_value_base)
                elif feature_name == "vibe":
                    vibe_id = tok.value

        s.energy = inv.get("energy", 0)
        s.carbon = inv.get("carbon", 0)
        s.oxygen = inv.get("oxygen", 0)
        s.germanium = inv.get("germanium", 0)
        s.silicon = inv.get("silicon", 0)
        s.heart = inv.get("heart", 0)
        s.influence = inv.get("influence", 0)
        s.hp = inv.get("hp", 100)

        # Gear items
        s.miner = inv.get("miner", 0)
        s.scout = inv.get("scout", 0)
        s.aligner = inv.get("aligner", 0)
        s.scrambler = inv.get("scrambler", 0)

        if s.heart != s._last_heart_count:
            s._heart_wait_start = 0
        s._last_heart_count = s.heart

        # Read vibe name from vibe ID using policy_env_info
        s.current_vibe = self._get_vibe_name(vibe_id)

        # Read last executed action from observation
        # This tells us what the simulator actually did, not what we intended
        if last_action_id is not None:
            action_names = self._action_names
            if 0 <= last_action_id < len(action_names):
                s.last_action_executed = action_names[last_action_id]
            else:
                s.last_action_executed = None
        else:
            s.last_action_executed = None

    def _get_vibe_name(self, vibe_id: int) -> str:
        """Convert vibe ID to vibe name."""
        if 0 <= vibe_id < len(self._vibe_names):
            return self._vibe_names[vibe_id]
        return "default"

    def _update_agent_position(self, s: CogsguardAgentState) -> None:
        """Update position based on last action that was ACTUALLY EXECUTED.

        IMPORTANT: Position is updated from the executed action in observations.
        This keeps internal position consistent with the simulator, even when
        movement is delayed or overridden by another controller.
        """
        # Use last_action_executed from observation, NOT last_action (our intent)
        executed_action = s.last_action_executed
        intended_action = s.last_action.name if s.last_action else None
        action_for_position = executed_action or intended_action

        # Debug: Log when intended != executed (action failed, delayed, or human control)
        if DEBUG and s.step_count <= 100:
            if intended_action and executed_action and intended_action != executed_action:
                print(
                    f"[A{s.agent_id}] ACTION_MISMATCH: intended={intended_action}, "
                    f"executed={executed_action} (action failed/delayed or human control)"
                )

        # ONLY update position when:
        # 1. The executed action is a move
        # 2. We're not interacting with an object this step
        if action_for_position and action_for_position.startswith("move_") and not s.using_object_this_step:
            direction = action_for_position[5:]  # Remove "move_" prefix
            if direction in self._move_deltas:
                dr, dc = self._move_deltas[direction]
                s.row += dr
                s.col += dc

        s.using_object_this_step = False

        # Track position history
        current_pos = (s.row, s.col)
        s.position_history.append(current_pos)
        if len(s.position_history) > 30:
            s.position_history.pop(0)

    def _parse_observation(self, s: CogsguardAgentState, obs: AgentObservation) -> ParsedObservation:
        """Parse observation into structured format."""
        return utils_parse_observation(
            s,  # type: ignore[arg-type]  # CogsguardAgentState is compatible with SimpleAgentState
            obs,
            obs_hr=self._obs_hr,
            obs_wr=self._obs_wr,
            spatial_feature_names=self._spatial_feature_names,
            agent_feature_key_by_name=self._agent_feature_key_by_name,
            protocol_input_prefix=self._protocol_input_prefix,
            protocol_output_prefix=self._protocol_output_prefix,
            tag_names=self._tag_names,
        )

    def _update_occupancy_and_discover(self, s: CogsguardAgentState, parsed: ParsedObservation) -> None:
        """Update occupancy map and discover objects."""
        if s.row < 0:
            return

        # Mark only cells within the simulator's observation mask as FREE/explored.
        for dr in range(-self._obs_hr, self._obs_hr + 1):
            for dc in range(-self._obs_wr, self._obs_wr + 1):
                if not is_within_observation_shape(
                    row_offset=dr,
                    col_offset=dc,
                    row_radius=self._obs_hr,
                    col_radius=self._obs_wr,
                ):
                    continue
                r, c = s.row + dr, s.col + dc
                if 0 <= r < s.map_height and 0 <= c < s.map_width:
                    s.occupancy[r][c] = CellType.FREE.value
                    s.explored[r][c] = True

        # Process discovered objects
        if DEBUG and s.step_count == 1:
            print(f"[A{s.agent_id}] Nearby objects: {[obj.name for obj in parsed.nearby_objects.values()]}")

        for pos, obj_state in parsed.nearby_objects.items():
            r, c = pos
            obj_name = obj_state.name.lower()
            obj_tags = [tag.lower() for tag in obj_state.tags]

            # Walls are obstacles
            if is_wall(obj_name):
                s.occupancy[r][c] = CellType.OBSTACLE.value
                self._update_structure(s, pos, obj_name, StructureType.WALL, obj_state)
                continue

            # Track other agents
            if obj_name == "agent" and obj_state.agent_id != s.agent_id:
                s.agent_occupancy.add((r, c))
                continue

            # Discover gear stations
            for _role, station_name in ROLE_TO_STATION.items():
                if (
                    is_station(obj_name, station_name)
                    or station_name in obj_name
                    or any(station_name in tag for tag in obj_tags)
                ):
                    s.occupancy[r][c] = CellType.OBSTACLE.value
                    struct_type = self._get_station_type(station_name)
                    self._update_structure(s, pos, obj_name, struct_type, obj_state)
                    break

            # Discover supply depots (junction in cogsguard)
            is_junction = has_type_tag(obj_tags, ("supply_depot", "junction", "junction"))
            if is_junction:
                s.occupancy[r][c] = CellType.OBSTACLE.value
                self._update_structure(s, pos, obj_name, StructureType.CHARGER, obj_state)

            # Discover hub (the main base / resource deposit point)
            is_hub = (
                "hub" in obj_name
                or obj_name in {"main_nexus"}
                or any("hub" in tag or "main_nexus" in tag or "nexus" in tag for tag in obj_tags)
            )
            if is_hub:
                s.occupancy[r][c] = CellType.OBSTACLE.value
                self._update_structure(s, pos, obj_name, StructureType.HUB, obj_state)

            # Discover chest (for hearts) - exclude extractors which are ChestConfig-backed.
            resources = ["carbon", "oxygen", "germanium", "silicon"]
            has_extractor_tag = "extractor" in obj_name or any("extractor" in tag for tag in obj_tags)
            is_resource_chest = any(f"{res}_" in obj_name or f"{res}chest" in obj_name for res in resources)
            if (
                not has_extractor_tag
                and (obj_name == "chest" or ("chest" in obj_name and not is_resource_chest))
                or any(tag == "chest" for tag in obj_tags)
            ):
                s.occupancy[r][c] = CellType.OBSTACLE.value
                self._update_structure(s, pos, obj_name, StructureType.CHEST, obj_state)

            # Discover extractors (in cogsguard they're named {resource}_extractor).
            for resource in ["carbon", "oxygen", "germanium", "silicon"]:
                if f"{resource}_extractor" in obj_name or any(f"{resource}_extractor" in tag for tag in obj_tags):
                    s.occupancy[r][c] = CellType.OBSTACLE.value
                    self._update_structure(s, pos, obj_name, StructureType.EXTRACTOR, obj_state, resource_type=resource)
                    break

    def _get_station_type(self, station_name: str) -> StructureType:
        """Convert station name to StructureType."""
        mapping = {
            "miner": StructureType.MINER_STATION,
            "scout": StructureType.SCOUT_STATION,
            "aligner": StructureType.ALIGNER_STATION,
            "scrambler": StructureType.SCRAMBLER_STATION,
        }
        return mapping.get(station_name, StructureType.UNKNOWN)

    def _update_structure(
        self,
        s: CogsguardAgentState,
        pos: tuple[int, int],
        obj_name: str,
        structure_type: StructureType,
        obj_state: ObjectState,
        resource_type: Optional[str] = None,
    ) -> None:
        """Update or create a structure in the structures map."""
        # Derive alignment from object name, tags, and structure type
        alignment = self._derive_alignment(obj_name, structure_type, obj_state.tags)
        if pos in s.alignment_overrides:
            override = s.alignment_overrides[pos]
            if alignment is None:
                alignment = override
            elif alignment != override:
                s.alignment_overrides[pos] = alignment

        # Calculate inventory amount for extractors
        # Key insight: empty dict {} on FIRST observation = no info yet (assume full)
        # Empty dict {} on SUBSEQUENT observation = depleted (0 resources)
        is_new_structure = pos not in s.structures

        if structure_type == StructureType.EXTRACTOR:
            # For extractors, track resource counts carefully
            if resource_type and resource_type in obj_state.inventory:
                # We have actual inventory info for this resource type
                inventory_amount = obj_state.inventory[resource_type]
            elif obj_state.inventory:
                # Sum all inventory if resource type not specified
                inventory_amount = sum(obj_state.inventory.values())
            elif is_new_structure:
                # First time seeing this extractor with no inventory info
                # Assume it has resources (we don't know yet)
                inventory_amount = 999
            else:
                # Known extractor with empty inventory dict = depleted (0 resources)
                inventory_amount = 0
            if DEBUG and inventory_amount == 0:
                print(f"[A{s.agent_id}] EXTRACTOR_EMPTY: {pos} resource={resource_type} inv={obj_state.inventory}")
        elif obj_state.inventory:
            # Non-extractors: use inventory sum if present
            inventory_amount = sum(obj_state.inventory.values())
        else:
            inventory_amount = 999  # Default: unknown/full

        if pos in s.structures:
            # Update existing structure
            struct = s.structures[pos]
            struct.last_seen_step = s.step_count
            struct.alignment = alignment
            struct.inventory_amount = inventory_amount
        else:
            # Create new structure
            s.structures[pos] = StructureInfo(
                position=pos,
                structure_type=structure_type,
                name=obj_name,
                last_seen_step=s.step_count,
                resource_type=resource_type,
                alignment=alignment,
                inventory_amount=inventory_amount,
            )

        if structure_type in {
            StructureType.HUB,
            StructureType.CHEST,
            StructureType.MINER_STATION,
            StructureType.SCOUT_STATION,
            StructureType.ALIGNER_STATION,
            StructureType.SCRAMBLER_STATION,
        }:
            s.stations[structure_type.value] = pos

        if structure_type == StructureType.CHARGER:
            for idx, (depot_pos, _alignment) in enumerate(s.supply_depots):
                if depot_pos == pos:
                    s.supply_depots[idx] = (pos, alignment)
                    break
            else:
                s.supply_depots.append((pos, alignment))
            if DEBUG:
                print(
                    f"[A{s.agent_id}] STRUCTURE: Added {structure_type.value} at {pos} "
                    f"(alignment={alignment}, inv={inventory_amount})"
                )

    def _derive_alignment(
        self,
        obj_name: str,
        structure_type: Optional[StructureType] = None,
        tags: Optional[list[str]] = None,
    ) -> Optional[str]:
        """Derive alignment from object name, tags, and structure type.

        In CoGsGuard:
        - Hub/nexus = cogs-aligned
        - Charger/supply_depot alignment comes from team: tags
        """
        obj_lower = obj_name.lower()
        tag_lowers = [tag.lower() for tag in tags or []]
        # Check if name contains alignment info
        # Check for team prefix format "X:" (e.g., "c:hub", "cg:miner")
        if ":" in obj_lower:
            prefix = obj_lower.split(":")[0]
            if prefix in ("c", "cg", "cb"):
                return "cogs"
        if "cogs" in obj_lower or "cogs_" in obj_lower or any("cogs" in tag for tag in tag_lowers):
            return "cogs"
        if "clips" in obj_lower or "clips_" in obj_lower or any("clips" in tag for tag in tag_lowers):
            return "clips"
        # Structure type defaults:
        # - Hub/nexus defaults to cogs (main cogs building)
        if structure_type == StructureType.HUB:
            if (
                "nexus" in obj_lower
                or "hub" in obj_lower
                or any("nexus" in tag for tag in tag_lowers)
                or any("hub" in tag for tag in tag_lowers)
            ):
                return "cogs"
        return None  # Unknown/neutral

    def _update_phase(self, s: CogsguardAgentState) -> None:
        """Update agent phase based on current vibe.

        Vibe-based state machine:
        - default/heart: do nothing
        - gear: pick role via smart coordinator, change vibe to that role
        - role vibe (scout/miner/aligner/scrambler): get gear first, then execute role
        """
        vibe = s.current_vibe

        # Role vibes: scout, miner, aligner, scrambler
        if vibe in VIBE_TO_ROLE:
            # Update role based on vibe
            s.role = VIBE_TO_ROLE[vibe]
            # Always try to get gear first, then execute role
            if s.has_gear():
                s.phase = CogsguardPhase.EXECUTE_ROLE
            elif s.step_count > 30 and s.role in (Role.MINER, Role.SCOUT):
                # After 30 steps, miners/scouts can proceed without gear to bootstrap economy/exploration.
                s.phase = CogsguardPhase.EXECUTE_ROLE
            else:
                s.phase = CogsguardPhase.GET_GEAR
        else:
            # For default, heart, gear vibes - handled in _execute_phase
            s.phase = CogsguardPhase.GET_GEAR  # Will be overridden

    def _execute_phase(self, s: CogsguardAgentState) -> Action:
        """Execute action for current phase based on vibe.

        Vibe-based behavior:
        - default: do nothing (noop)
        - gear: pick role via smart coordinator, change vibe to that role
        - role vibe: get gear then execute role
        - heart: do nothing (noop)
        """
        vibe = s.current_vibe

        # Default vibe: do nothing (wait for external vibe change)
        if vibe == "default":
            return self._noop()

        # Heart vibe: do nothing
        if vibe == "heart":
            return self._noop()

        # Gear vibe: pick a role and change vibe to it
        if vibe == "gear":
            selected_role = self._choose_role_vibe(s)
            if DEBUG:
                print(f"[A{s.agent_id}] GEAR_VIBE: Picking role vibe: {selected_role}")
            s.last_role_switch_step = s.step_count
            s.role_lock_until_step = s.step_count + SMART_ROLE_SWITCH_COOLDOWN
            return change_vibe_action(selected_role, action_names=self._action_names)

        # Role vibes: execute the role behavior
        if vibe in VIBE_TO_ROLE:
            if s.phase == CogsguardPhase.GET_GEAR:
                return self._do_get_gear(s)
            elif s.phase == CogsguardPhase.EXECUTE_ROLE:
                return self.execute_role(s)

        return self._noop()

    def _do_recharge(self, s: CogsguardAgentState) -> Action:
        """Recharge by standing near the main nexus (cogs-aligned, has energy AOE).

        IMPORTANT: If energy is very low, we can't even move to the nexus!
        In that case, just wait (noop) and hope AOE regeneration eventually helps,
        or try a single step towards the nexus if we can afford it.
        """
        # The main_nexus is cogs-aligned and has AOE that gives energy to cogs agents
        # The supply_depot is clips-aligned and won't give energy to cogs agents
        nexus_pos = s.get_structure_position(StructureType.HUB)
        if nexus_pos is None:
            if DEBUG:
                print(f"[A{s.agent_id}] RECHARGE: No nexus found, exploring")
            return self._explore(s)

        # Just need to be near the nexus (within AOE range), not adjacent
        dist = abs(s.row - nexus_pos[0]) + abs(s.col - nexus_pos[1])
        aoe_range = 10  # AOE range from recipe

        if dist <= aoe_range:
            if DEBUG and s.step_count % 20 == 0:
                print(f"[A{s.agent_id}] RECHARGE: Near nexus (dist={dist}), waiting for AOE (energy={s.energy})")
            return self._noop()

        # Check if we have enough energy to move at all
        # If energy is too low, just wait and hope for passive regen or AOE
        if s.energy < s.MOVE_ENERGY_COST:
            if DEBUG and s.step_count % 20 == 0:
                print(
                    f"[A{s.agent_id}] RECHARGE: Energy critically low ({s.energy}), "
                    f"can't move to nexus at dist={dist}, waiting for regen"
                )
            return self._noop()

        # If we have some energy but not much, try to move one step at a time towards nexus
        # This is more conservative - don't commit to a long path if we might not make it
        if s.energy < s.MOVE_ENERGY_COST * 3:
            if DEBUG and s.step_count % 10 == 0:
                print(
                    f"[A{s.agent_id}] RECHARGE: Low energy ({s.energy}), "
                    f"taking single step towards nexus at {nexus_pos}"
                )
            # Simple single-step movement towards nexus
            dr = nexus_pos[0] - s.row
            dc = nexus_pos[1] - s.col
            if abs(dr) >= abs(dc):
                # Move vertically
                if dr > 0:
                    return self._move("south")
                else:
                    return self._move("north")
            else:
                # Move horizontally
                if dc > 0:
                    return self._move("east")
                else:
                    return self._move("west")

        if DEBUG and s.step_count % 20 == 0:
            print(f"[A{s.agent_id}] RECHARGE: Moving to nexus at {nexus_pos} from ({s.row},{s.col}), dist={dist}")
        return self._move_towards(s, nexus_pos, reach_adjacent=True)

    def _do_get_gear(self, s: CogsguardAgentState) -> Action:
        """Find gear station and equip gear."""
        if (
            self._smart_role_coordinator is not None
            and s.role != Role.SCRAMBLER
            and s.step_count <= SCRAMBLER_GEAR_PRIORITY_STEPS
        ):
            has_scrambler_teammate = any(
                snapshot.role == Role.SCRAMBLER for snapshot in self._smart_role_coordinator.agent_snapshots.values()
            )
            if has_scrambler_teammate:
                gear_counts = self._smart_role_coordinator.get_role_gear_counts()
                if gear_counts.get("scrambler", 0) == 0:
                    if DEBUG and s.step_count % 5 == 0:
                        print(f"[A{s.agent_id}] GET_GEAR: yielding to scrambler gear priority")
                    return self._explore(s)
        station_name = s.get_gear_station_name()
        station_pos = s.get_structure_position(s.get_gear_station_type())
        hub_pos = s.get_structure_position(StructureType.HUB)

        if DEBUG and s.step_count <= 10:
            known_structures = sorted({struct.structure_type.value for struct in s.structures.values()})
            print(f"[A{s.agent_id}] GET_GEAR: station={station_name} pos={station_pos} all={known_structures}")

        # Bootstrap with scout gear for mobility when station is unknown.
        if station_pos is None:
            scout_station = s.get_structure_position(StructureType.SCOUT_STATION)
            if scout_station is not None and s.scout == 0 and station_name != "scout":
                if not is_adjacent((s.row, s.col), scout_station):
                    return self._move_towards(s, scout_station, reach_adjacent=True)
                return self._use_object_at(s, scout_station)

            if hub_pos is not None:
                offset = GEAR_SEARCH_OFFSETS[(s.agent_id + s.step_count // 10) % len(GEAR_SEARCH_OFFSETS)]
                target = (hub_pos[0] + offset[0], hub_pos[1] + offset[1])
                goal_cells = compute_goal_cells(s, target, True, CellType)  # type: ignore[arg-type]
                if goal_cells:
                    return self._move_towards(s, target, reach_adjacent=True)

            if DEBUG:
                print(f"[A{s.agent_id}] GET_GEAR: No {station_name} found, exploring")
            return self._explore(s)

        # Navigate to station
        adj = is_adjacent((s.row, s.col), station_pos)
        if DEBUG and s.step_count <= 60:
            print(f"[A{s.agent_id}] GET_GEAR: pos=({s.row},{s.col}), station={station_pos}, adjacent={adj}")
        if not adj:
            return self._move_towards(s, station_pos, reach_adjacent=True)

        # Bump station to get gear
        if DEBUG:
            print(f"[A{s.agent_id}] GET_GEAR: Adjacent to {station_name}, bumping it!")
        return self._use_object_at(s, station_pos)

    def execute_role(self, s: CogsguardAgentState) -> Action:
        """Execute role-specific behavior. Override in subclasses."""
        if s.step_count <= 100:
            print(f"[A{s.agent_id}] BASE_EXECUTE_ROLE: impl={type(self).__name__}, role={s.role}")
        return self._explore(s)

    # =========================================================================
    # Navigation utilities
    # =========================================================================

    def _use_object_at(self, s: CogsguardAgentState, target_pos: tuple[int, int]) -> Action:
        """Use an object by moving into its cell."""
        tr, tc = target_pos
        if s.row == tr and s.col == tc:
            return self._noop()

        dr = tr - s.row
        dc = tc - s.col

        # Check agent collision
        if (tr, tc) in s.agent_occupancy:
            return self._noop()

        # Mark that we're using an object
        s.using_object_this_step = True

        if dr == -1:
            return self._move("north")
        if dr == 1:
            return self._move("south")
        if dc == 1:
            return self._move("east")
        if dc == -1:
            return self._move("west")

        return self._noop()

    def _explore_frontier(self, s: CogsguardAgentState) -> Optional[Action]:
        """Find and move toward the nearest unexplored frontier."""
        if not s.explored or len(s.explored) == 0:
            return None

        start = (s.row, s.col)
        visited: set[tuple[int, int]] = {start}
        queue: deque[tuple[tuple[int, int], Optional[str]]] = deque()
        queue.append((start, None))

        directions = [("north", -1, 0), ("south", 1, 0), ("east", 0, 1), ("west", 0, -1)]
        direction_deltas = {direction: (dr, dc) for direction, dr, dc in directions}

        while queue:
            pos, first_step = queue.popleft()
            r, c = pos

            for direction, dr, dc in directions:
                nr, nc = r + dr, c + dc
                if not (0 <= nr < s.map_height and 0 <= nc < s.map_width):
                    continue
                if (nr, nc) in visited:
                    continue

                visited.add((nr, nc))

                if not s.explored[nr][nc]:
                    if first_step is None:
                        if s.occupancy[nr][nc] == CellType.FREE.value and (nr, nc) not in s.agent_occupancy:
                            if DEBUG and s.step_count <= 100:
                                print(f"[A{s.agent_id}] FRONTIER: Moving {direction} to unexplored ({nr},{nc})")
                            return self._move(direction)
                    else:
                        step_dr, step_dc = direction_deltas[first_step]
                        step_r, step_c = s.row + step_dr, s.col + step_dc
                        if not (0 <= step_r < s.map_height and 0 <= step_c < s.map_width):
                            continue
                        if s.occupancy[step_r][step_c] != CellType.FREE.value or (step_r, step_c) in s.agent_occupancy:
                            continue
                        if DEBUG and s.step_count <= 100:
                            explored_count = sum(sum(row) for row in s.explored)
                            total_cells = s.map_height * s.map_width
                            print(
                                f"[A{s.agent_id}] FRONTIER: Heading {first_step} towards "
                                f"frontier at ({nr},{nc}), explored={explored_count}/{total_cells}"
                            )
                        return self._move(first_step)

                if s.explored[nr][nc] and s.occupancy[nr][nc] == CellType.FREE.value:
                    next_first_step = first_step
                    if first_step is None and (r, c) == start:
                        next_first_step = direction
                    queue.append(((nr, nc), next_first_step))

        if DEBUG and s.step_count % 50 == 0:
            explored_count = sum(sum(row) for row in s.explored)
            total_cells = s.map_height * s.map_width
            print(f"[A{s.agent_id}] FRONTIER: None found, explored={explored_count}/{total_cells}")
        return None

    def _explore(self, s: CogsguardAgentState) -> Action:
        """Explore systematically - cycle through cardinal directions."""
        # Check for location loop (agents blocking each other back and forth)
        if self._is_in_location_loop(s):
            action = self._break_location_loop(s)
            if action:
                return action
            # If can't break loop, fall through to normal exploration

        # Start with east since gear stations are typically east of hub
        direction_cycle: list[CardinalDirection] = ["east", "south", "west", "north"]

        if DEBUG and s.step_count <= 30:
            print(f"[A{s.agent_id}] EXPLORE: target={s.exploration_target}, step={s.step_count}")

        if s.exploration_target is not None and isinstance(s.exploration_target, str):
            steps_in_direction = s.step_count - s.exploration_target_step
            if steps_in_direction < 8:  # Explore 8 steps before turning (faster cycles)
                dr, dc = self._move_deltas.get(s.exploration_target, (0, 0))
                next_r, next_c = s.row + dr, s.col + dc
                if path_is_traversable(s, next_r, next_c, CellType):  # type: ignore[arg-type]
                    return self._move(s.exploration_target)  # type: ignore[arg-type]

        # Pick next direction in the cycle (don't randomize)
        current_dir = s.exploration_target
        if current_dir in direction_cycle:
            idx = direction_cycle.index(current_dir)
            next_idx = (idx + 1) % 4
        else:
            # Always start with east (index 0) since gear stations are east of hub
            next_idx = 0

        # Try directions starting from next_idx
        for i in range(4):
            direction = direction_cycle[(next_idx + i) % 4]
            dr, dc = self._move_deltas[direction]
            next_r, next_c = s.row + dr, s.col + dc
            traversable = path_is_traversable(s, next_r, next_c, CellType)  # type: ignore[arg-type]
            if DEBUG and s.step_count <= 10:
                in_bounds = 0 <= next_r < s.map_height and 0 <= next_c < s.map_width
                cell_val = s.occupancy[next_r][next_c] if in_bounds else -1
                agent_occ = (next_r, next_c) in s.agent_occupancy
                print(
                    f"[A{s.agent_id}] EXPLORE_DIR: {direction} -> ({next_r},{next_c}) "
                    f"trav={traversable} cell={cell_val} agent={agent_occ}"
                )
            if traversable:
                s.exploration_target = direction
                s.exploration_target_step = s.step_count
                return self._move(direction)

        if DEBUG and s.step_count <= 10:
            print(f"[A{s.agent_id}] EXPLORE: All directions blocked, returning noop")
        return self._noop()

    def _move_towards(
        self,
        s: CogsguardAgentState,
        target: tuple[int, int],
        *,
        reach_adjacent: bool = False,
    ) -> Action:
        """Pathfind toward a target."""
        # Check for location loop (agents blocking each other back and forth)
        if self._is_in_location_loop(s):
            action = self._break_location_loop(s)
            if action:
                return action
            # If can't break loop, fall through to normal pathfinding

        start = (s.row, s.col)
        if start == target and not reach_adjacent:
            return self._noop()

        goal_cells = compute_goal_cells(s, target, reach_adjacent, CellType)  # type: ignore[arg-type]
        if not goal_cells:
            if DEBUG:
                print(f"[A{s.agent_id}] PATHFIND: No goal cells for {target}")
            return self._noop()

        # Check cached path
        path = None
        if s.cached_path and s.cached_path_target == target and s.cached_path_reach_adjacent == reach_adjacent:
            next_pos = s.cached_path[0]
            if path_is_traversable(s, next_pos[0], next_pos[1], CellType):  # type: ignore[arg-type]
                path = s.cached_path

        # Compute new path if needed
        if path is None:
            path = shortest_path(s, start, goal_cells, False, CellType)  # type: ignore[arg-type]
            s.cached_path = path.copy() if path else None
            s.cached_path_target = target
            s.cached_path_reach_adjacent = reach_adjacent

        if not path:
            if DEBUG:
                print(f"[A{s.agent_id}] PATHFIND: No path to {target}, exploring instead")
            return self._explore(s)

        next_pos = path[0]

        # Convert to action
        dr = next_pos[0] - s.row
        dc = next_pos[1] - s.col

        # Check agent collision
        if (next_pos[0], next_pos[1]) in s.agent_occupancy:
            action = self._try_random_direction(s)
            if action:
                s.cached_path = None
                s.cached_path_target = None
                return action
            return self._noop()

        # Advance cached path only after taking a step
        if s.cached_path:
            s.cached_path = s.cached_path[1:]
            if not s.cached_path:
                s.cached_path = None
                s.cached_path_target = None

        if dr == -1 and dc == 0:
            return self._move("north")
        elif dr == 1 and dc == 0:
            return self._move("south")
        elif dr == 0 and dc == 1:
            return self._move("east")
        elif dr == 0 and dc == -1:
            return self._move("west")

        return self._noop()

    def _try_random_direction(self, s: CogsguardAgentState) -> Optional[Action]:
        """Try to move in a random free direction."""
        directions: list[CardinalDirection] = ["north", "south", "east", "west"]
        self._rng.shuffle(directions)
        for direction in directions:
            dr, dc = self._move_deltas[direction]
            nr, nc = s.row + dr, s.col + dc
            if path_is_within_bounds(s, nr, nc) and s.occupancy[nr][nc] == CellType.FREE.value:  # type: ignore[arg-type]
                if (nr, nc) not in s.agent_occupancy:
                    return self._move(direction)
        return None

    def _is_in_location_loop(self, s: CogsguardAgentState) -> bool:
        """Detect if agent is stuck in a back-and-forth location loop.

        Detects patterns like A→B→A→B→A (oscillating between 2 positions 3+ times).
        Returns True if such a loop is detected.
        """
        history = s.position_history
        # Need at least 5 positions to detect A→B→A→B→A pattern
        if len(history) < 5:
            return False

        # Check last 6 positions for oscillation pattern
        recent = history[-6:] if len(history) >= 6 else history

        # Count unique positions in recent history
        unique_positions = set(recent)

        # If only 2 unique positions in last 6 moves, we're oscillating
        if len(unique_positions) <= 2 and len(recent) >= 5:
            if DEBUG:
                print(f"[A{s.agent_id}] LOOP_DETECTED: Oscillating between {unique_positions}")
            return True

        return False

    def _break_location_loop(self, s: CogsguardAgentState) -> Optional[Action]:
        """Try to break out of a location loop by moving in a random direction.

        Clears cached path to force re-pathing after breaking the loop.
        """
        if DEBUG:
            print(f"[A{s.agent_id}] BREAKING_LOOP: Attempting random move to escape")

        # Clear cached path to force fresh pathfinding
        s.cached_path = None
        s.cached_path_target = None

        # Clear position history to reset loop detection
        s.position_history.clear()

        return self._try_random_direction(s)


# =============================================================================
# Policy wrapper
# =============================================================================


def _parse_vibe_list(raw: Optional[str]) -> list[str]:
    if not raw:
        return []
    return [entry.strip().lower() for entry in raw.split(",") if entry.strip()]


class CogsguardPolicy(MultiAgentPolicy):
    """Multi-agent policy for CoGsGuard with vibe-based role selection.

    Agents use vibes to determine their behavior:
    - default: do nothing
    - gear: pick a role via smart or evolutionary coordinator, change vibe to that role
    - miner/scout/aligner/scrambler: get gear then execute role
    - heart: do nothing

    Initial vibe counts can be specified via URI query parameters:
        metta://policy/role?miner=4&scrambler=2&gear=1
    You can also set a fixed role pattern with:
        metta://policy/role?role_cycle=aligner,miner,scrambler,scout
        metta://policy/role?role_order=aligner,miner,aligner,miner,scout

    Vibes are assigned to agents in order. If counts don't sum to num_agents,
    remaining agents get "gear" vibe (which picks a role via the smart coordinator).
    """

    short_names = ["role"]

    def __init__(
        self,
        policy_env_info: PolicyEnvInterface,
        device: str = "cpu",
        role_cycle: Optional[str] = None,
        role_order: Optional[str] = None,
        **vibe_counts: int,
    ):
        super().__init__(policy_env_info, device=device)
        self._agent_policies: dict[int, StatefulAgentPolicy[CogsguardAgentState]] = {}
        self._smart_role_coordinator = SmartRoleCoordinator(policy_env_info.num_agents)
        self._feature_by_id = {feature.id: feature for feature in policy_env_info.obs_features}
        self._action_name_to_index = policy_env_info.action_name_to_flat_index
        self._noop_action_value = dtype_actions.type(self._action_name_to_index["noop"])

        def _parse_flag(value: object) -> bool:
            if isinstance(value, bool):
                return value
            if isinstance(value, int):
                return value != 0
            if isinstance(value, str):
                return value.strip().lower() in {"1", "true", "yes", "on"}
            return False

        self._use_evolutionary_roles = (
            _parse_flag(vibe_counts.pop("evolution", None))
            or _parse_flag(vibe_counts.pop("evolutionary", None))
            or _parse_flag(vibe_counts.pop("evolve", None))
        )
        self._evolutionary_role_coordinator = (
            EvolutionaryRoleCoordinator(policy_env_info.num_agents) if self._use_evolutionary_roles else None
        )
        self._evolutionary_hooks_configured = False

        action_names = policy_env_info.all_action_names
        available_vibes = {name[len("change_vibe_") :] for name in action_names if name.startswith("change_vibe_")}
        role_vibes = [vibe for vibe in ["scrambler", "aligner", "miner", "scout"] if vibe in available_vibes]

        self._initial_vibes: list[str] = []
        role_cycle_list = _parse_vibe_list(role_cycle)
        role_order_list = _parse_vibe_list(role_order)

        if role_order_list:
            self._initial_vibes = []
            fallback_vibe = "default"
            for vibe in role_order_list:
                if vibe in available_vibes or vibe == "default":
                    self._initial_vibes.append(vibe)
                else:
                    if DEBUG:
                        print(f"[CogsguardPolicy] Unknown role_order vibe '{vibe}', using '{fallback_vibe}'")
                    self._initial_vibes.append(fallback_vibe)
            remaining = policy_env_info.num_agents - len(self._initial_vibes)
            if remaining > 0 and "gear" in available_vibes:
                self._initial_vibes.extend(["gear"] * remaining)
        elif role_cycle_list:
            cycle = [vibe for vibe in role_cycle_list if vibe in available_vibes]
            if cycle:
                while len(self._initial_vibes) < policy_env_info.num_agents:
                    self._initial_vibes.extend(cycle)
                self._initial_vibes = self._initial_vibes[: policy_env_info.num_agents]

        if not self._initial_vibes:
            # Build initial vibe assignment from URI params (e.g., ?scrambler=1&miner=4)
            counts = {k: v for k, v in vibe_counts.items() if isinstance(v, int)}
            if not counts and role_vibes:
                counts = {"scrambler": 1, "miner": 4}

            if role_vibes:
                for vibe_name in role_vibes:  # Role vibes first
                    self._initial_vibes.extend([vibe_name] * counts.get(vibe_name, 0))
            # Add gear vibes (agents will pick a role)
            if "gear" in available_vibes:
                self._initial_vibes.extend(["gear"] * counts.get("gear", 0))
            remaining = policy_env_info.num_agents - len(self._initial_vibes)
            if remaining > 0 and "gear" in available_vibes:
                self._initial_vibes.extend(["gear"] * remaining)

        if DEBUG:
            print(f"[CogsguardPolicy] Initial vibe assignment: {self._initial_vibes}")

    def agent_policy(self, agent_id: int) -> StatefulAgentPolicy[CogsguardAgentState]:
        if agent_id not in self._agent_policies:
            # Create a multi-role implementation that can handle any role
            # The actual role is determined by vibe at runtime
            # Assign initial target vibe based on agent_id and configured counts
            target_vibe: Optional[str] = None
            if agent_id < len(self._initial_vibes):
                target_vibe = self._initial_vibes[agent_id]
            # Agents without assigned vibes stay on "default" (noop)

            impl = CogsguardMultiRoleImpl(
                self._policy_env_info,
                agent_id,
                initial_target_vibe=target_vibe,
                smart_role_coordinator=self._smart_role_coordinator,
                evolutionary_role_coordinator=self._evolutionary_role_coordinator,
                use_evolutionary_roles=self._use_evolutionary_roles,
            )
            if self._evolutionary_role_coordinator is not None and not self._evolutionary_hooks_configured:
                from .behavior_hooks import build_cogsguard_behavior_hooks  # noqa: PLC0415

                self._evolutionary_role_coordinator.behavior_hooks.update(build_cogsguard_behavior_hooks(impl))
                self._evolutionary_hooks_configured = True
            self._agent_policies[agent_id] = StatefulAgentPolicy(impl, self._policy_env_info, agent_id=agent_id)

        return self._agent_policies[agent_id]

    def step_batch(self, raw_observations: np.ndarray, raw_actions: np.ndarray) -> None:
        num_agents = min(raw_observations.shape[0], self._policy_env_info.num_agents)
        for agent_id in range(num_agents):
            obs = self._raw_obs_to_agent_obs(agent_id, raw_observations[agent_id])
            action = self.agent_policy(agent_id).step(obs)
            action_index = self._action_name_to_index[action.name]
            raw_actions[agent_id] = dtype_actions.type(action_index)

    def _raw_obs_to_agent_obs(self, agent_id: int, raw_obs: np.ndarray) -> AgentObservation:
        tokens: list[ObservationToken] = []
        for token in raw_obs:
            feature_id = int(token[1])
            if feature_id == 0xFF:
                break
            feature = self._feature_by_id.get(feature_id)
            if feature is None:
                continue
            location_packed = int(token[0])
            value = int(token[2])
            tokens.append(
                ObservationToken(
                    feature=feature,
                    value=value,
                    raw_token=(location_packed, feature_id, value),
                )
            )
        return AgentObservation(agent_id=agent_id, tokens=tokens)


class CogsguardMultiRoleImpl(CogsguardAgentPolicyImpl):
    """Multi-role implementation that delegates to role-specific behavior based on vibe."""

    def __init__(
        self,
        policy_env_info: PolicyEnvInterface,
        agent_id: int,
        initial_target_vibe: Optional[str] = None,
        smart_role_coordinator: Optional[SmartRoleCoordinator] = None,
        evolutionary_role_coordinator: Optional[EvolutionaryRoleCoordinator] = None,
        use_evolutionary_roles: bool = False,
    ):
        # Initialize with MINER as default, but role will be updated based on vibe
        super().__init__(
            policy_env_info,
            agent_id,
            Role.MINER,
            smart_role_coordinator=smart_role_coordinator,
            evolutionary_role_coordinator=evolutionary_role_coordinator,
            use_evolutionary_roles=use_evolutionary_roles,
        )

        # Target vibe to switch to at start (if specified)
        self._initial_target_vibe = initial_target_vibe
        self._initial_vibe_set = False
        self._smart_role_enabled = initial_target_vibe == "gear"

        # Lazy-load role implementations
        self._role_impls: dict[Role, CogsguardAgentPolicyImpl] = {}

    def _execute_phase(self, s: CogsguardAgentState) -> Action:
        """Execute action for current phase, handling initial vibe assignment.

        Overrides base class to:
        1. Handle initial vibe assignment from URI params
        2. Skip the hardcoded "agent 0 = scrambler" logic when initial vibe is configured
        """
        # If we have a target vibe and haven't switched yet, do it first
        if self._initial_target_vibe and not self._initial_vibe_set:
            if not self._has_vibe(self._initial_target_vibe):
                self._initial_vibe_set = True
                self._smart_role_enabled = False
                return self._noop()
            if s.current_vibe != self._initial_target_vibe:
                if DEBUG:
                    print(
                        f"[A{s.agent_id}] INITIAL_VIBE: Switching from {s.current_vibe} to {self._initial_target_vibe}"
                    )
                return change_vibe_action(self._initial_target_vibe, action_names=self._action_names)
            self._initial_vibe_set = True

        # If initial target vibe was configured, skip the hardcoded agent 0 scrambler logic
        # by directly handling the vibe-based behavior here
        if self._initial_target_vibe:
            return self._execute_vibe_behavior(s)

        # Continue with normal phase execution (includes agent 0 scrambler logic)
        return super()._execute_phase(s)

    def _execute_vibe_behavior(self, s: CogsguardAgentState) -> Action:
        """Execute vibe-based behavior without the hardcoded agent 0 scrambler override."""
        vibe = s.current_vibe

        # Default vibe: do nothing (wait for external vibe change)
        if vibe == "default":
            return self._noop()

        # Heart vibe: do nothing
        if vibe == "heart":
            return self._noop()

        # Gear vibe: pick a role and change vibe to it
        if vibe == "gear":
            if self._smart_role_enabled and s.step_count <= 20:
                selected_role = SMART_ROLE_STARTUP_ORDER[s.agent_id % len(SMART_ROLE_STARTUP_ORDER)]
            else:
                selected_role = self._choose_role_vibe(s)
            if DEBUG:
                print(f"[A{s.agent_id}] GEAR_VIBE: Picking role vibe: {selected_role}")
            if not self._has_vibe(selected_role):
                return self._noop()
            s.last_role_switch_step = s.step_count
            s.role_lock_until_step = s.step_count + SMART_ROLE_SWITCH_COOLDOWN
            return change_vibe_action(selected_role, action_names=self._action_names)

        # Role vibes: execute the role behavior
        if vibe in VIBE_TO_ROLE:
            action = self._maybe_switch_smart_role(s)
            if action is not None:
                return action
            if s.phase == CogsguardPhase.GET_GEAR:
                return self._do_get_gear(s)
            elif s.phase == CogsguardPhase.EXECUTE_ROLE:
                return self.execute_role(s)

        return self._noop()

    def _maybe_switch_smart_role(self, s: CogsguardAgentState) -> Optional[Action]:
        if not self._smart_role_enabled or self._smart_role_coordinator is None:
            return None
        if s._pending_action_type is not None:
            return None
        if s.phase == CogsguardPhase.GET_GEAR:
            return None
        if s.step_count < s.role_lock_until_step:
            return None

        gear_role = None
        if s.aligner > 0:
            gear_role = "aligner"
        elif s.scrambler > 0:
            gear_role = "scrambler"
        elif s.miner > 0:
            gear_role = "miner"
        elif s.scout > 0:
            gear_role = "scout"
        if gear_role and gear_role != s.current_vibe:
            if not self._has_vibe(gear_role):
                return None
            return change_vibe_action(gear_role, action_names=self._action_names)

        selected_role = self._smart_role_coordinator.choose_role(s.agent_id)
        if selected_role == s.current_vibe:
            return None

        role_counts = self._smart_role_coordinator.get_role_counts()
        selected_role_count = role_counts.get(selected_role, 0)
        if selected_role_count > 0:
            if s.step_count % SMART_ROLE_REASSESS_INTERVAL != 0:
                return None
            if self._rng.random() >= SMART_ROLE_REASSESS_PROBABILITY:
                return None

        s.last_role_switch_step = s.step_count
        s.role_lock_until_step = s.step_count + SMART_ROLE_SWITCH_COOLDOWN
        if DEBUG:
            print(f"[A{s.agent_id}] SMART_ROLE: Switching to {selected_role}")
        if not self._has_vibe(selected_role):
            return None
        return change_vibe_action(selected_role, action_names=self._action_names)

    def _get_role_impl(self, role: Role) -> CogsguardAgentPolicyImpl:
        """Get or create role-specific implementation."""
        if role not in self._role_impls:
            from .aligner import AlignerAgentPolicyImpl  # noqa: PLC0415
            from .miner import MinerAgentPolicyImpl  # noqa: PLC0415
            from .scout import ScoutAgentPolicyImpl  # noqa: PLC0415
            from .scrambler import ScramblerAgentPolicyImpl  # noqa: PLC0415

            impl_class = {
                Role.MINER: MinerAgentPolicyImpl,
                Role.SCOUT: ScoutAgentPolicyImpl,
                Role.ALIGNER: AlignerAgentPolicyImpl,
                Role.SCRAMBLER: ScramblerAgentPolicyImpl,
            }[role]

            self._role_impls[role] = impl_class(
                self._policy_env_info,
                self._agent_id,
                role,
                smart_role_coordinator=self._smart_role_coordinator,
            )

        return self._role_impls[role]

    def execute_role(self, s: CogsguardAgentState) -> Action:
        """Delegate to role-specific implementation based on current role (set from vibe)."""
        role_impl = self._get_role_impl(s.role)
        return role_impl.execute_role(s)


class CogsguardGeneralistImpl(CogsguardAgentPolicyImpl):
    """Generalist agent that picks roles based on situational priorities."""

    ROLE = Role.MINER
    ROLE_SWITCH_COOLDOWN = 120
    EARLY_SCOUT_STEPS = 80
    MIN_STRUCTURES_FOR_MIDGAME = 6
    MIN_ENERGY_BUFFER = 2

    def __init__(
        self,
        policy_env_info: PolicyEnvInterface,
        agent_id: int,
        smart_role_coordinator: Optional[SmartRoleCoordinator] = None,
    ):
        super().__init__(policy_env_info, agent_id, Role.MINER, smart_role_coordinator=smart_role_coordinator)
        self._role_impls: dict[Role, CogsguardAgentPolicyImpl] = {}

    def _update_phase(self, s: CogsguardAgentState) -> None:
        desired_role = self._select_role(s)
        if self._should_switch_role(s, desired_role):
            if DEBUG:
                print(f"[A{s.agent_id}] GENERALIST: Switching role {s.role.value} -> {desired_role.value}")
            s.role = desired_role
            s.last_role_switch_step = s.step_count
            s.role_lock_until_step = s.step_count + self.ROLE_SWITCH_COOLDOWN

        if s.has_gear() or s.step_count > 30:
            s.phase = CogsguardPhase.EXECUTE_ROLE
        else:
            s.phase = CogsguardPhase.GET_GEAR

    def _execute_phase(self, s: CogsguardAgentState) -> Action:
        if self._should_recharge(s):
            return self._do_recharge(s)
        if s.phase == CogsguardPhase.GET_GEAR:
            return self._do_get_gear(s)
        if s.phase == CogsguardPhase.EXECUTE_ROLE:
            return self.execute_role(s)
        return self._noop()

    def execute_role(self, s: CogsguardAgentState) -> Action:
        role_impl = self._get_role_impl(s.role)
        return role_impl.execute_role(s)

    def _select_role(self, s: CogsguardAgentState) -> Role:
        if s._pending_action_type is not None:
            return s.role

        hub_known = s.stations.get("hub") is not None

        if not hub_known:
            return Role.SCOUT

        if s._pending_alignment_target is not None:
            return Role.ALIGNER

        if s.step_count < self.EARLY_SCOUT_STEPS and len(s.structures) < self.MIN_STRUCTURES_FOR_MIDGAME:
            return Role.SCOUT

        junctions = s.get_structures_by_type(StructureType.CHARGER)
        has_enemy_junctions = any(junction.alignment == "clips" for junction in junctions)
        has_neutral_junctions = any(junction.alignment in (None, "neutral") for junction in junctions)
        role_counts = self._role_counts()

        if s.role == Role.SCRAMBLER:
            if has_neutral_junctions and self._role_is_ready(s, Role.ALIGNER):
                return Role.ALIGNER
            if has_enemy_junctions:
                return Role.SCRAMBLER
        if s.role == Role.ALIGNER:
            if (
                s._pending_alignment_target is None
                and not has_neutral_junctions
                and has_enemy_junctions
                and self._role_is_ready(s, Role.SCRAMBLER)
            ):
                return Role.SCRAMBLER
            if has_enemy_junctions or has_neutral_junctions:
                return Role.ALIGNER

        target_counts = self._target_role_counts(
            num_agents=self._policy_env_info.num_agents,
            has_enemy_junctions=has_enemy_junctions,
            has_neutral_junctions=has_neutral_junctions,
            hub_known=hub_known,
            step_count=s.step_count,
        )
        deficit_role = self._pick_deficit_role(s, role_counts, target_counts)
        if deficit_role is not None:
            return deficit_role

        if has_enemy_junctions and self._role_is_ready(s, Role.SCRAMBLER):
            return Role.SCRAMBLER
        if has_neutral_junctions and self._role_is_ready(s, Role.ALIGNER):
            return Role.ALIGNER

        if not s.get_usable_extractors():
            return Role.SCOUT

        if s.total_cargo < s.cargo_capacity - 2:
            return Role.MINER

        return self._pick_balanced_role(s, has_enemy_junctions, has_neutral_junctions)

    def _should_switch_role(self, s: CogsguardAgentState, desired_role: Role) -> bool:
        if desired_role == s.role:
            return False
        if s._pending_action_type is not None:
            return False
        if desired_role == Role.ALIGNER and s._pending_alignment_target is not None:
            return True
        if desired_role == Role.ALIGNER and s.role == Role.SCRAMBLER:
            has_neutral = any(
                junction.alignment in (None, "neutral") for junction in s.get_structures_by_type(StructureType.CHARGER)
            )
            if has_neutral:
                return True
        return not (s.step_count < s.role_lock_until_step)

    def _role_is_ready(self, s: CogsguardAgentState, role: Role) -> bool:
        if role in (Role.ALIGNER, Role.SCRAMBLER) and s.stations.get("hub") is None:
            return False
        if role in (Role.MINER, Role.SCOUT):
            return True
        return True

    def _target_role_counts(
        self,
        num_agents: int,
        has_enemy_junctions: bool,
        has_neutral_junctions: bool,
        hub_known: bool,
        step_count: int,
    ) -> dict[Role, int]:
        targets: dict[Role, int] = {}
        if step_count < self.EARLY_SCOUT_STEPS:
            targets[Role.SCOUT] = 2 if num_agents >= 8 else 1
        else:
            targets[Role.SCOUT] = 1
        targets[Role.MINER] = max(4, num_agents // 2)
        if hub_known:
            targets[Role.SCRAMBLER] = 2 if has_enemy_junctions else 1
            targets[Role.ALIGNER] = 2 if has_neutral_junctions else 1
        return targets

    def _pick_deficit_role(
        self,
        s: CogsguardAgentState,
        role_counts: dict[Role, int],
        target_counts: dict[Role, int],
    ) -> Role | None:
        if not target_counts:
            return None
        deficits: list[Role] = []
        ordered_roles = [Role.SCRAMBLER, Role.ALIGNER, Role.SCOUT, Role.MINER]
        for role in ordered_roles:
            target = target_counts.get(role, 0)
            if target <= 0:
                continue
            deficit = max(target - role_counts.get(role, 0), 0)
            deficits.extend([role] * deficit)
        if not deficits:
            return None
        role = deficits[s.agent_id % len(deficits)]
        if self._role_is_ready(s, role):
            return role
        return None

    def _should_recharge(self, s: CogsguardAgentState) -> bool:
        if s.total_cargo > 0:
            return False
        if s.energy >= s.MOVE_ENERGY_COST * self.MIN_ENERGY_BUFFER:
            return False
        return s.stations.get("hub") is not None

    def _role_has_gear(self, s: CogsguardAgentState, role: Role) -> bool:
        return getattr(s, ROLE_TO_GEAR[role], 0) > 0

    def _role_station_known(self, s: CogsguardAgentState, role: Role) -> bool:
        return s.stations.get(ROLE_TO_STATION[role]) is not None

    def _pick_balanced_role(
        self,
        s: CogsguardAgentState,
        has_enemy_junctions: bool,
        has_neutral_junctions: bool,
    ) -> Role:
        candidates = [Role.MINER, Role.SCOUT]
        if has_enemy_junctions and self._role_is_ready(s, Role.SCRAMBLER):
            candidates.append(Role.SCRAMBLER)
        if has_neutral_junctions and self._role_is_ready(s, Role.ALIGNER):
            candidates.append(Role.ALIGNER)

        role_counts = self._role_counts()
        best_role = s.role
        best_score = float("-inf")
        for role in candidates:
            score = 0
            if role == s.role:
                score += 2
            if self._role_has_gear(s, role):
                score += 3
            elif self._role_station_known(s, role):
                score += 1
            if role_counts:
                score += 2 - role_counts.get(role, 0)
            if score > best_score:
                best_score = score
                best_role = role
        return best_role

    def _role_counts(self) -> dict[Role, int]:
        if self._smart_role_coordinator is None:
            return {}
        counts = {role: 0 for role in Role}
        for snapshot in self._smart_role_coordinator.agent_snapshots.values():
            counts[snapshot.role] += 1
        return counts

    def _get_role_impl(self, role: Role) -> CogsguardAgentPolicyImpl:
        if role not in self._role_impls:
            from .aligner import AlignerAgentPolicyImpl  # noqa: PLC0415
            from .miner import MinerAgentPolicyImpl  # noqa: PLC0415
            from .scout import ScoutAgentPolicyImpl  # noqa: PLC0415
            from .scrambler import ScramblerAgentPolicyImpl  # noqa: PLC0415

            impl_class = {
                Role.MINER: MinerAgentPolicyImpl,
                Role.SCOUT: ScoutAgentPolicyImpl,
                Role.ALIGNER: AlignerAgentPolicyImpl,
                Role.SCRAMBLER: ScramblerAgentPolicyImpl,
            }[role]

            self._role_impls[role] = impl_class(
                self._policy_env_info,
                self._agent_id,
                role,
                smart_role_coordinator=self._smart_role_coordinator,
            )
        return self._role_impls[role]


class CogsguardWomboImpl(CogsguardGeneralistImpl):
    """Generalist agent that prioritizes aligning multiple junctions."""

    TARGET_ALIGNED_JUNCTIONS = 2
    JUNCTION_PUSH_SCOUTS = 2
    JUNCTION_PUSH_ALIGNERS = 2
    JUNCTION_PUSH_SCRAMBLERS = 2
    MIN_MINERS = 4

    def _select_role(self, s: CogsguardAgentState) -> Role:
        aligned_count = 0
        if self._smart_role_coordinator is not None:
            aligned_count = self._smart_role_coordinator.aligned_junction_count()
        if aligned_count < self.TARGET_ALIGNED_JUNCTIONS:
            if s._pending_action_type is not None:
                return s.role
            if s.stations.get("hub") is None:
                return Role.SCOUT
            if s.role in (Role.SCRAMBLER, Role.ALIGNER) and s.has_gear():
                return s.role
            if s.role == Role.SCRAMBLER and s._pending_alignment_target is not None:
                return Role.SCRAMBLER
        return super()._select_role(s)

    def _should_recharge(self, s: CogsguardAgentState) -> bool:
        aligned_count = 0
        if self._smart_role_coordinator is not None:
            aligned_count = self._smart_role_coordinator.aligned_junction_count()
        if aligned_count < self.TARGET_ALIGNED_JUNCTIONS and s.role in (Role.SCRAMBLER, Role.ALIGNER):
            if s.total_cargo > 0:
                return False
            if s.energy >= s.MOVE_ENERGY_COST * self.MIN_ENERGY_BUFFER:
                return False
            return s.stations.get("hub") is not None
        return super()._should_recharge(s)

    def _target_role_counts(
        self,
        num_agents: int,
        has_enemy_junctions: bool,
        has_neutral_junctions: bool,
        hub_known: bool,
        step_count: int,
    ) -> dict[Role, int]:
        targets = super()._target_role_counts(
            num_agents=num_agents,
            has_enemy_junctions=has_enemy_junctions,
            has_neutral_junctions=has_neutral_junctions,
            hub_known=hub_known,
            step_count=step_count,
        )

        aligned_count = 0
        if self._smart_role_coordinator is not None:
            aligned_count = self._smart_role_coordinator.aligned_junction_count()

        if aligned_count < self.TARGET_ALIGNED_JUNCTIONS:
            targets[Role.SCOUT] = max(targets.get(Role.SCOUT, 0), self.JUNCTION_PUSH_SCOUTS)
            if hub_known:
                targets[Role.SCRAMBLER] = max(targets.get(Role.SCRAMBLER, 0), self.JUNCTION_PUSH_SCRAMBLERS)
                targets[Role.ALIGNER] = max(targets.get(Role.ALIGNER, 0), self.JUNCTION_PUSH_ALIGNERS)
            targets[Role.MINER] = max(self.MIN_MINERS, num_agents // 2)

        return targets


class CogsguardGeneralistPolicy(CogsguardPolicy):
    """Generalist policy that adapts roles based on map and resource priorities."""

    def __init__(self, policy_env_info: PolicyEnvInterface, device: str = "cpu", **_ignored: int):
        super().__init__(policy_env_info, device=device, **_ignored)

    def agent_policy(self, agent_id: int) -> StatefulAgentPolicy[CogsguardAgentState]:
        if agent_id not in self._agent_policies:
            impl = CogsguardGeneralistImpl(
                self._policy_env_info,
                agent_id,
                smart_role_coordinator=self._smart_role_coordinator,
            )
            self._agent_policies[agent_id] = StatefulAgentPolicy(impl, self._policy_env_info, agent_id=agent_id)
        return self._agent_policies[agent_id]


class CogsguardWomboPolicy(CogsguardPolicy):
    """Generalist policy that prioritizes role rigs based on map conditions."""

    short_names = ["wombo"]

    def __init__(self, policy_env_info: PolicyEnvInterface, device: str = "cpu", **_ignored: int):
        super().__init__(policy_env_info, device=device, **_ignored)

    def agent_policy(self, agent_id: int) -> StatefulAgentPolicy[CogsguardAgentState]:
        if agent_id not in self._agent_policies:
            impl = CogsguardWomboImpl(
                self._policy_env_info,
                agent_id,
                smart_role_coordinator=self._smart_role_coordinator,
            )
            self._agent_policies[agent_id] = StatefulAgentPolicy(impl, self._policy_env_info, agent_id=agent_id)
        return self._agent_policies[agent_id]
