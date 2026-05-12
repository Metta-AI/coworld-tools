"""CoGsGuard scripted policy with a phased leader coordinator."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from agent_policies.policies.scripted.cogsguard.scripted_agent.utils import change_vibe_action
from mettagrid.policy.policy import StatefulAgentPolicy
from mettagrid.policy.policy_env_interface import PolicyEnvInterface
from mettagrid.simulator import Action

from .aligner import AlignerAgentPolicyImpl
from .miner import MinerAgentPolicyImpl
from .policy import DEBUG, CogsguardAgentPolicyImpl, CogsguardMultiRoleImpl, CogsguardPolicy
from .role_mix import build_role_plan as _build_role_plan
from .role_mix import default_role_counts as _default_role_counts
from .role_mix import normalize_counts as _normalize_counts
from .scout import ScoutAgentPolicyImpl
from .scrambler import ScramblerAgentPolicyImpl
from .types import CogsguardAgentState, Role, StructureType

PLAN_INTERVAL_STEPS = 40
PHASE_EXPLORE_END = 60
PHASE_CONTROL_END = 220
CHEST_LOW_THRESHOLD = 60
CONTROL_VIBES = {"scrambler", "aligner"}


@dataclass
class CommanderPlannerState:
    num_agents: int
    desired_vibes: list[str] = field(default_factory=list)
    last_plan_step: int = 0
    known_junctions: int = 0
    aligned_junctions: int = 0
    chest_resources: int = 0
    junction_map: dict[tuple[int, int], Optional[str]] = field(default_factory=dict)
    assigned_targets: dict[int, tuple[int, int]] = field(default_factory=dict)

    def update_from_agent(self, s: CogsguardAgentState) -> None:
        junctions = s.get_structures_by_type(StructureType.CHARGER)
        aligned = [c for c in junctions if c.alignment == "cogs"]
        self.known_junctions = max(self.known_junctions, len(junctions))
        self.aligned_junctions = max(self.aligned_junctions, len(aligned))
        for junction in junctions:
            self.junction_map[junction.position] = junction.alignment

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
                f"[COMMANDER] plan@{step_count}: junctions={self.known_junctions} "
                f"aligned={self.aligned_junctions} chest={self.chest_resources} "
                f"roles={counts}"
            )

    def _choose_counts(self, step_count: int) -> dict[str, int]:
        if step_count < PHASE_EXPLORE_END or self.known_junctions == 0:
            scouts = 2 if self.num_agents >= 5 else 1
            return {
                "scrambler": 1,
                "aligner": 0,
                "scout": scouts,
                "miner": max(1, self.num_agents - (1 + scouts)),
            }

        if step_count < PHASE_CONTROL_END and self.aligned_junctions < max(1, self.known_junctions // 3):
            scramblers = 2 if self.num_agents >= 6 else 1
            aligners = 2 if self.num_agents >= 6 else 1
            return {
                "scrambler": scramblers,
                "aligner": aligners,
                "scout": 1,
                "miner": max(1, self.num_agents - (scramblers + aligners + 1)),
            }

        if 0 < self.chest_resources < CHEST_LOW_THRESHOLD:
            return {
                "scrambler": 1,
                "aligner": 1,
                "scout": 1,
                "miner": max(1, self.num_agents - 3),
            }

        return {
            "scrambler": 1,
            "aligner": 1,
            "scout": 1,
            "miner": max(1, self.num_agents - 3),
        }

    def _assign_targets(self) -> None:
        targets = [pos for pos, alignment in self.junction_map.items() if alignment != "cogs"]
        targets.sort()

        self.assigned_targets.clear()
        if not targets or not self.desired_vibes:
            return

        target_index = 0
        for agent_id, vibe in enumerate(self.desired_vibes):
            if vibe not in CONTROL_VIBES:
                continue
            self.assigned_targets[agent_id] = targets[target_index]
            target_index = (target_index + 1) % len(targets)


class CogsguardCommanderMultiRoleImpl(CogsguardMultiRoleImpl):
    def __init__(
        self,
        policy_env_info: PolicyEnvInterface,
        agent_id: int,
        initial_target_vibe: Optional[str],
        shared_state: CommanderPlannerState,
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
        target = self._shared_state.assigned_targets.get(s.agent_id)
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
                Role.MINER: MinerAgentPolicyImpl,
                Role.SCOUT: ScoutAgentPolicyImpl,
                Role.ALIGNER: CommanderAlignerAgentPolicyImpl,
                Role.SCRAMBLER: CommanderScramblerAgentPolicyImpl,
            }[role]
            self._role_impls[role] = impl_class(self._policy_env_info, self._agent_id, role)
        return self._role_impls[role]


class CommanderScramblerAgentPolicyImpl(ScramblerAgentPolicyImpl):
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


class CommanderAlignerAgentPolicyImpl(AlignerAgentPolicyImpl):
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


class CogsguardControlAgent(CogsguardPolicy):
    """CoGsGuard policy with a phased coordinator that overrides roles."""

    short_names = ["cogsguard_control"]

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
        self._shared_state = CommanderPlannerState(policy_env_info.num_agents)
        self._shared_state.desired_vibes = _build_role_plan(policy_env_info.num_agents, counts)

    def agent_policy(self, agent_id: int) -> StatefulAgentPolicy[CogsguardAgentState]:
        if agent_id not in self._agent_policies:
            target_vibe = None
            if agent_id < len(self._initial_vibes):
                target_vibe = self._initial_vibes[agent_id]

            impl = CogsguardCommanderMultiRoleImpl(
                self._policy_env_info,
                agent_id,
                initial_target_vibe=target_vibe,
                shared_state=self._shared_state,
            )
            self._agent_policies[agent_id] = StatefulAgentPolicy(impl, self._policy_env_info, agent_id=agent_id)

        return self._agent_policies[agent_id]
