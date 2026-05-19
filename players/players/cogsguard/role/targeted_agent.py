"""CoGsGuard scripted policy with targeted role assignments."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from players.cogsguard._shared.utils import change_vibe_action
from mettagrid.policy.policy import StatefulAgentPolicy
from mettagrid.policy.policy_env_interface import PolicyEnvInterface
from mettagrid.simulator import Action

from .aligner import AlignerAgentPolicyImpl
from .miner import HEALING_AOE_RANGE, MinerAgentPolicyImpl
from .policy import DEBUG, CogsguardAgentPolicyImpl, CogsguardMultiRoleImpl, CogsguardPolicy
from .role_mix import build_role_plan as _build_role_plan
from .role_mix import default_role_counts as _default_role_counts
from .role_mix import normalize_counts as _normalize_counts
from .scout import ScoutAgentPolicyImpl
from .scrambler import ScramblerAgentPolicyImpl
from .types import CogsguardAgentState, Role, StructureInfo, StructureType

PLAN_INTERVAL_STEPS = 25
PHASE_EXPLORE_END = 80
PHASE_CONTROL_END = 260
CHEST_LOW_THRESHOLD = 60
CONTROL_VIBES = {"scrambler", "aligner"}
RESOURCE_CYCLE = ["carbon", "oxygen", "germanium", "silicon"]


@dataclass
class TargetedPlannerState:
    num_agents: int
    desired_vibes: list[str] = field(default_factory=list)
    last_plan_step: int = 0
    known_junctions: int = 0
    aligned_junctions: int = 0
    chest_resources: int = 0
    junction_map: dict[tuple[int, int], Optional[str]] = field(default_factory=dict)
    extractor_map: dict[tuple[int, int], Optional[str]] = field(default_factory=dict)
    assigned_junctions: dict[int, tuple[int, int]] = field(default_factory=dict)
    assigned_extractors: dict[int, tuple[int, int]] = field(default_factory=dict)

    def update_from_agent(self, s: CogsguardAgentState) -> None:
        junctions = s.get_structures_by_type(StructureType.CHARGER)
        aligned = [c for c in junctions if c.alignment == "cogs"]
        self.known_junctions = max(self.known_junctions, len(junctions))
        self.aligned_junctions = max(self.aligned_junctions, len(aligned))
        for junction in junctions:
            self.junction_map[junction.position] = junction.alignment

        for extractor in s.get_usable_extractors():
            self.extractor_map[extractor.position] = extractor.resource_type

        chest_resources = 0
        for struct in s.get_structures_by_type(StructureType.CHEST):
            chest_resources = max(chest_resources, struct.inventory_amount)
        if chest_resources > 0:
            self.chest_resources = max(self.chest_resources, chest_resources)

    def maybe_plan(self, step_count: int) -> None:
        if step_count - self.last_plan_step < PLAN_INTERVAL_STEPS:
            return
        self.last_plan_step = step_count

        counts = self._choose_counts(step_count)
        self.desired_vibes = _build_role_plan(self.num_agents, counts)
        self._assign_targets()

        if DEBUG:
            print(
                f"[TARGETED] plan@{step_count}: junctions={self.known_junctions} "
                f"aligned={self.aligned_junctions} chest={self.chest_resources} "
                f"roles={counts}"
            )

    def _choose_counts(self, step_count: int) -> dict[str, int]:
        if step_count < PHASE_EXPLORE_END or self.known_junctions == 0:
            scouts = 3 if self.num_agents >= 8 else 2 if self.num_agents >= 5 else 1
            return {
                "scrambler": 0,
                "aligner": 0,
                "scout": scouts,
                "miner": max(1, self.num_agents - scouts),
            }

        if 0 < self.chest_resources < CHEST_LOW_THRESHOLD:
            scramblers = 1
            aligners = 1
            scouts = 1
            return {
                "scrambler": scramblers,
                "aligner": aligners,
                "scout": scouts,
                "miner": max(1, self.num_agents - (scramblers + aligners + scouts)),
            }

        if step_count < PHASE_CONTROL_END and self.aligned_junctions < max(1, self.known_junctions // 2):
            if self.num_agents >= 8:
                scramblers = 2
                aligners = 3
            elif self.num_agents >= 6:
                scramblers = 1
                aligners = 2
            else:
                scramblers = 1
                aligners = 1
            return {
                "scrambler": scramblers,
                "aligner": aligners,
                "scout": 1,
                "miner": max(1, self.num_agents - (scramblers + aligners + 1)),
            }

        return {
            "scrambler": 1,
            "aligner": 2 if self.num_agents >= 6 else 1,
            "scout": 1,
            "miner": max(1, self.num_agents - (2 if self.num_agents >= 6 else 1) - 2),
        }

    def _assign_targets(self) -> None:
        junctions = [pos for pos, alignment in self.junction_map.items() if alignment != "cogs"]
        junctions.sort()
        extractors_by_resource: dict[str, list[tuple[int, int]]] = {res: [] for res in RESOURCE_CYCLE}
        for pos, resource in self.extractor_map.items():
            if resource in extractors_by_resource:
                extractors_by_resource[resource].append(pos)
        for positions in extractors_by_resource.values():
            positions.sort()
        all_extractors = sorted(self.extractor_map.keys())

        self.assigned_junctions.clear()
        self.assigned_extractors.clear()
        if not self.desired_vibes:
            return

        junction_index = 0
        extractor_index = 0
        for agent_id, vibe in enumerate(self.desired_vibes):
            if vibe in CONTROL_VIBES and junctions:
                self.assigned_junctions[agent_id] = junctions[junction_index]
                junction_index = (junction_index + 1) % len(junctions)
            elif vibe == "miner" and self.extractor_map:
                preferred = RESOURCE_CYCLE[agent_id % len(RESOURCE_CYCLE)]
                preferred_list = extractors_by_resource.get(preferred, [])
                if preferred_list:
                    self.assigned_extractors[agent_id] = preferred_list[extractor_index % len(preferred_list)]
                elif all_extractors:
                    self.assigned_extractors[agent_id] = all_extractors[extractor_index % len(all_extractors)]
                extractor_index += 1


class TargetedMultiRoleImpl(CogsguardMultiRoleImpl):
    def __init__(
        self,
        policy_env_info: PolicyEnvInterface,
        agent_id: int,
        initial_target_vibe: Optional[str],
        shared_state: TargetedPlannerState,
    ):
        super().__init__(policy_env_info, agent_id, initial_target_vibe=initial_target_vibe)
        self._shared_state = shared_state

    def _execute_phase(self, s: CogsguardAgentState) -> Action:
        self._shared_state.update_from_agent(s)
        if s.agent_id == 0:
            self._shared_state.maybe_plan(s.step_count)

        if self._shared_state.desired_vibes:
            desired = self._shared_state.desired_vibes[s.agent_id]
            if desired != s.current_vibe:
                return change_vibe_action(desired, action_names=self._action_names)

        return super()._execute_phase(s)

    def execute_role(self, s: CogsguardAgentState) -> Action:
        target = self._shared_state.assigned_junctions.get(s.agent_id)
        if target and s.current_vibe in CONTROL_VIBES and s.has_gear() and s.heart >= 1:
            struct = s.get_structure_at(target)
            if struct and struct.alignment != "cogs":
                if abs(target[0] - s.row) + abs(target[1] - s.col) > 1:
                    return self._move_towards(s, target, reach_adjacent=True)
                return self._use_object_at(s, target)
        return super().execute_role(s)

    def _get_role_impl(self, role: Role) -> CogsguardAgentPolicyImpl:
        if role not in self._role_impls:
            impl_class = {
                Role.MINER: TargetedMinerAgentPolicyImpl,
                Role.SCOUT: ScoutAgentPolicyImpl,
                Role.ALIGNER: TargetedAlignerAgentPolicyImpl,
                Role.SCRAMBLER: TargetedScramblerAgentPolicyImpl,
            }[role]
            if role == Role.MINER:
                self._role_impls[role] = impl_class(self._policy_env_info, self._agent_id, role, self._shared_state)
            else:
                self._role_impls[role] = impl_class(self._policy_env_info, self._agent_id, role)
        return self._role_impls[role]


class TargetedScramblerAgentPolicyImpl(ScramblerAgentPolicyImpl):
    def _find_best_target(self, s: CogsguardAgentState) -> Optional[tuple[int, int]]:
        junctions = s.get_structures_by_type(StructureType.CHARGER)
        cooldown = 20 if len(junctions) <= 4 else 50

        enemy_junctions: list[tuple[int, tuple[int, int]]] = []
        neutral_junctions: list[tuple[int, tuple[int, int]]] = []
        any_junctions: list[tuple[int, tuple[int, int]]] = []

        for junction in junctions:
            pos = junction.position
            dist = abs(pos[0] - s.row) + abs(pos[1] - s.col)

            last_worked = s.worked_junctions.get(pos, 0)
            if last_worked > 0 and s.step_count - last_worked < cooldown:
                continue

            if junction.alignment == "cogs":
                continue

            if junction.alignment == "clips":
                enemy_junctions.append((dist, pos))
            elif junction.alignment is None or junction.alignment == "neutral":
                neutral_junctions.append((dist, pos))
            else:
                any_junctions.append((dist, pos))

        if enemy_junctions:
            enemy_junctions.sort()
            return enemy_junctions[0][1]
        if neutral_junctions:
            neutral_junctions.sort()
            return neutral_junctions[0][1]
        if any_junctions:
            any_junctions.sort()
            return any_junctions[0][1]

        return super()._find_best_target(s)


class TargetedAlignerAgentPolicyImpl(AlignerAgentPolicyImpl):
    def _find_best_target(self, s: CogsguardAgentState) -> Optional[tuple[int, int]]:
        junctions = s.get_structures_by_type(StructureType.CHARGER)
        cooldown = 20 if len(junctions) <= 4 else 50

        neutral_junctions: list[tuple[int, tuple[int, int]]] = []
        clips_junctions: list[tuple[int, tuple[int, int]]] = []
        other_junctions: list[tuple[int, tuple[int, int]]] = []

        for junction in junctions:
            pos = junction.position
            dist = abs(pos[0] - s.row) + abs(pos[1] - s.col)

            last_worked = s.worked_junctions.get(pos, 0)
            if last_worked > 0 and s.step_count - last_worked < cooldown:
                continue

            if junction.alignment == "cogs":
                continue

            if junction.alignment is None or junction.alignment == "neutral":
                neutral_junctions.append((dist, pos))
            elif junction.alignment == "clips":
                clips_junctions.append((dist, pos))
            else:
                other_junctions.append((dist, pos))

        if neutral_junctions:
            neutral_junctions.sort()
            return neutral_junctions[0][1]
        if clips_junctions:
            clips_junctions.sort()
            return clips_junctions[0][1]
        if other_junctions:
            other_junctions.sort()
            return other_junctions[0][1]

        return super()._find_best_target(s)


class TargetedMinerAgentPolicyImpl(MinerAgentPolicyImpl):
    def __init__(
        self,
        policy_env_info: PolicyEnvInterface,
        agent_id: int,
        role: Role,
        shared_state: TargetedPlannerState,
    ):
        super().__init__(policy_env_info, agent_id, role)
        self._shared_state = shared_state
        self._preferred_resource = RESOURCE_CYCLE[agent_id % len(RESOURCE_CYCLE)]

    def _get_safe_extractor(
        self,
        s: CogsguardAgentState,
        preferred_resource: str | None = None,
    ) -> Optional[StructureInfo]:
        target = self._shared_state.assigned_extractors.get(s.agent_id)
        if target:
            current = s.get_structure_at(target)
            if current and current.is_usable_extractor():
                max_safe_dist = self._get_max_safe_distance(s)
                dist_to_ext = abs(target[0] - s.row) + abs(target[1] - s.col)
                nearest_depot = self._get_nearest_aligned_depot(s)
                if nearest_depot:
                    dist_ext_to_depot = abs(target[0] - nearest_depot[0]) + abs(target[1] - nearest_depot[1])
                    round_trip = dist_to_ext + max(0, dist_ext_to_depot - HEALING_AOE_RANGE)
                else:
                    round_trip = dist_to_ext * 2
                if round_trip <= max_safe_dist:
                    return current
        resource = preferred_resource or self._preferred_resource
        preferred = [ext for ext in s.get_usable_extractors() if ext.resource_type == resource]
        if preferred:
            nearest_depot = self._get_nearest_aligned_depot(s)
            max_safe_dist = self._get_max_safe_distance(s)
            candidates: list[tuple[int, int, int, StructureInfo]] = []
            for ext in preferred:
                dist_to_ext = abs(ext.position[0] - s.row) + abs(ext.position[1] - s.col)
                if nearest_depot:
                    dist_ext_to_depot = abs(ext.position[0] - nearest_depot[0]) + abs(
                        ext.position[1] - nearest_depot[1]
                    )
                    round_trip = dist_to_ext + max(0, dist_ext_to_depot - HEALING_AOE_RANGE)
                else:
                    round_trip = dist_to_ext * 2
                if round_trip <= max_safe_dist:
                    dist_ext_to_depot = (
                        abs(ext.position[0] - nearest_depot[0]) + abs(ext.position[1] - nearest_depot[1])
                        if nearest_depot
                        else 100
                    )
                    candidates.append((ext.inventory_amount, dist_ext_to_depot, dist_to_ext, ext))
            if candidates:
                candidates.sort(key=lambda x: (-x[0], x[1], x[2]))
                return candidates[0][3]

        return super()._get_safe_extractor(s, preferred_resource=preferred_resource)


class CogsguardTargetedAgent(CogsguardPolicy):
    """CoGsGuard policy with coordinated role and target assignment."""

    short_names = ["cogsguard_targeted"]

    def __init__(
        self,
        policy_env_info: PolicyEnvInterface,
        device: str = "cpu",
        **vibe_counts: Any,
    ):
        has_explicit_counts = any(isinstance(v, int) for v in vibe_counts.values())
        if has_explicit_counts:
            counts = _normalize_counts(policy_env_info.num_agents, vibe_counts)
        else:
            counts = _default_role_counts(policy_env_info.num_agents)
        super().__init__(policy_env_info, device=device, **counts)
        self._shared_state = TargetedPlannerState(policy_env_info.num_agents)
        self._shared_state.desired_vibes = _build_role_plan(policy_env_info.num_agents, counts)

    def agent_policy(self, agent_id: int) -> StatefulAgentPolicy[CogsguardAgentState]:
        if agent_id not in self._agent_policies:
            target_vibe = None
            if agent_id < len(self._initial_vibes):
                target_vibe = self._initial_vibes[agent_id]

            impl = TargetedMultiRoleImpl(
                self._policy_env_info,
                agent_id,
                initial_target_vibe=target_vibe,
                shared_state=self._shared_state,
            )
            self._agent_policies[agent_id] = StatefulAgentPolicy(impl, self._policy_env_info, agent_id=agent_id)

        return self._agent_policies[agent_id]
