from __future__ import annotations

import heapq
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass

from mettagrid_sdk.games.cogsguard import (
    COGSGUARD_BOOTSTRAP_HUB_OFFSETS,
    CogsguardSemanticSurface,
)
from mettagrid_sdk.sdk import MacroDirective, MettagridState, SemanticEntity

from cvc.cogent.player_cog.memory import MemoryStore
from cvc.cogent.player_cog.policy import helpers as _h
from cvc.cogent.player_cog.policy.helpers import KnownEntity
from mettagrid.policy.policy import AgentPolicy, MultiAgentPolicy
from mettagrid.policy.policy_env_interface import PolicyEnvInterface
from mettagrid.simulator import Action
from mettagrid.simulator.interface import AgentObservation

_STATION_OFFSETS = {
    "aligner": (-3, 4),
    "scrambler": (-1, 4),
    "miner": (1, 4),
    "scout": (3, 4),
}
_TEMP_BLOCK_STEPS = 10
_RETREAT_MARGIN = 20
_DEFAULT_BOUND_MARGIN = 12
_ALIGNER_GEAR_DELAY_STEPS = 0
_TARGET_SWITCH_THRESHOLD = 3.0
_SHARED_JUNCTION_MEMORY_STEPS = 400
_OSCILLATION_HISTORY_STEPS = 6
_OSCILLATION_UNSTICK_STEPS = 4
_MINING_ALIGNER_MIN_RESOURCE = 14
_DEFAULT_NETWORK_WEIGHT = 0.5
_DEFAULT_HOTSPOT_WEIGHT = 8.0
_ECONOMY_BOOTSTRAP_ALIGNER_BUDGET = 2
_ALIGNER_PRIORITY = (0, 1, 2, 3, 4, 5, 6, 7)
_SCRAMBLER_PRIORITY = (3, 7, 6, 2)
_HUB_OFFSETS = COGSGUARD_BOOTSTRAP_HUB_OFFSETS
_COGSGUARD_SURFACE = CogsguardSemanticSurface()


@dataclass(slots=True)
class MoveAttempt:
    direction: str
    stationary_use: bool


@dataclass(slots=True)
class PressureMetrics:
    frontier_neutral_junctions: int
    best_frontier_coverage: int
    best_enemy_scramble_block: int


@dataclass(slots=True)
class NavigationObservation:
    position: tuple[int, int]
    subtask: str
    target_kind: str
    target_position: tuple[int, int] | None


class SharedWorldModel:
    def __init__(self) -> None:
        self._entities: dict[str, KnownEntity] = {}

    def reset(self) -> None:
        self._entities.clear()

    def update(self, state: MettagridState) -> None:
        step = state.step or 0
        for entity in state.visible_entities:
            if entity.entity_type == "agent":
                continue
            global_x = _h.attr_int(entity, "global_x", entity.position.x)
            global_y = _h.attr_int(entity, "global_y", entity.position.y)
            key = f"{entity.entity_type}@{global_x},{global_y}"
            self._entities[key] = KnownEntity(
                entity_type=entity.entity_type,
                global_x=global_x,
                global_y=global_y,
                labels=tuple(entity.labels),
                team=_h.attr_str(entity, "team"),
                owner=_h.attr_str(entity, "owner"),
                last_seen_step=step,
                attributes=dict(entity.attributes),
            )

    def prune_missing_extractors(
        self,
        *,
        current_position: tuple[int, int],
        visible_entities: list[SemanticEntity],
        obs_width: int,
        obs_height: int,
    ) -> None:
        half_width = obs_width // 2
        half_height = obs_height // 2
        min_x = current_position[0] - half_width
        max_x = current_position[0] + half_width
        min_y = current_position[1] - half_height
        max_y = current_position[1] + half_height
        visible_extractors = {
            (
                _h.attr_int(entity, "global_x", entity.position.x),
                _h.attr_int(entity, "global_y", entity.position.y),
            )
            for entity in visible_entities
            if entity.entity_type.endswith("_extractor")
        }
        stale_keys = [
            key
            for key, entity in self._entities.items()
            if entity.entity_type.endswith("_extractor")
            and min_x <= entity.global_x <= max_x
            and min_y <= entity.global_y <= max_y
            and entity.position not in visible_extractors
        ]
        for key in stale_keys:
            self._entities.pop(key, None)

    def entities(
        self,
        *,
        entity_type: str | None = None,
        predicate: Callable[[KnownEntity], bool] | None = None,
    ) -> list[KnownEntity]:
        result = []
        for entity in self._entities.values():
            if entity_type is not None and entity.entity_type != entity_type:
                continue
            if predicate is not None and not predicate(entity):
                continue
            result.append(entity)
        return result

    def nearest(
        self,
        *,
        position: tuple[int, int],
        entity_type: str | None = None,
        predicate: Callable[[KnownEntity], bool] | None = None,
    ) -> KnownEntity | None:
        candidates = self.entities(entity_type=entity_type, predicate=predicate)
        if not candidates:
            return None
        return min(candidates, key=lambda entity: (_h.manhattan(position, entity.position), entity.position))

    def occupied_cells(self, *, exclude: set[tuple[int, int]] | None = None) -> set[tuple[int, int]]:
        excluded = set() if exclude is None else exclude
        return {
            entity.position
            for entity in self._entities.values()
            if entity.position not in excluded and entity.entity_type != "agent"
        }

    def is_occupied(self, position: tuple[int, int]) -> bool:
        return position in self.occupied_cells()

    def entity_at(
        self,
        *,
        position: tuple[int, int],
        entity_type: str | None = None,
        predicate: Callable[[KnownEntity], bool] | None = None,
    ) -> KnownEntity | None:
        for entity in self._entities.values():
            if entity.position != position:
                continue
            if entity_type is not None and entity.entity_type != entity_type:
                continue
            if predicate is not None and not predicate(entity):
                continue
            return entity
        return None

    def forget_nearest(
        self,
        *,
        position: tuple[int, int],
        entity_type: str,
        max_distance: int,
    ) -> bool:
        nearest = self.nearest(position=position, entity_type=entity_type)
        if nearest is None or _h.manhattan(position, nearest.position) > max_distance:
            return False
        key = f"{nearest.entity_type}@{nearest.global_x},{nearest.global_y}"
        self._entities.pop(key, None)
        return True


class SemanticCogAgentPolicy(AgentPolicy):
    def __init__(
        self,
        policy_env_info: PolicyEnvInterface,
        *,
        agent_id: int,
        world_model: SharedWorldModel,
        shared_claims: dict[tuple[int, int], tuple[int, int]],
        shared_junctions: dict[tuple[int, int], tuple[str | None, int]],
        shared_hotspots: dict[tuple[int, int], int] | None = None,
        shared_team_ids: set[int] | None = None,
    ) -> None:
        super().__init__(policy_env_info)
        self._agent_id = agent_id
        self._world_model = world_model
        self._shared_claims = shared_claims
        self._shared_junctions = shared_junctions
        self._shared_hotspots = shared_hotspots if shared_hotspots is not None else {}
        self._shared_team_ids = shared_team_ids if shared_team_ids is not None else set()
        self._memory = MemoryStore()
        self._previous_state: MettagridState | None = None
        self._last_global_pos: tuple[int, int] | None = None
        self._last_attempt: MoveAttempt | None = None
        self._temp_blocks: dict[tuple[int, int], int] = {}
        self._step_index = 0
        self._action_names = set(policy_env_info.action_names)
        self._vibe_actions = set(policy_env_info.vibe_action_names)
        self._fallback_action = "noop" if "noop" in self._action_names else policy_env_info.action_names[0]
        self._explore_index = 0
        self._default_resource_bias = _h._ELEMENTS[agent_id % len(_h._ELEMENTS)]
        self._resource_bias = self._default_resource_bias
        self._last_inventory_signature: tuple[tuple[str, int], ...] | None = None
        self._stalled_steps = 0
        self._oscillation_steps = 0
        self._recent_navigation: deque[NavigationObservation] = deque(maxlen=_OSCILLATION_HISTORY_STEPS)
        self._current_target_position: tuple[int, int] | None = None
        self._current_target_kind: str | None = None
        self._claimed_target: tuple[int, int] | None = None
        self._sticky_target_position: tuple[int, int] | None = None
        self._sticky_target_kind: str | None = None
        self._current_directive = MacroDirective()
        self._network_weight = _DEFAULT_NETWORK_WEIGHT
        self._hotspot_weight = _DEFAULT_HOTSPOT_WEIGHT
        self._expansion_weight = 10.0
        self._expansion_cap = 60.0

    def step(self, obs: AgentObservation) -> Action:
        self._step_index += 1
        state = _COGSGUARD_SURFACE.build_state_with_events(
            obs,
            policy_env_info=self.policy_env_info,
            step=self._step_index,
            previous_state=self._previous_state,
        )
        return self.evaluate_state(state)

    def evaluate_state(self, state: MettagridState) -> Action:
        self._step_index = self._step_index + 1 if state.step is None else state.step
        self._current_target_position = None
        self._current_target_kind = None
        self._memory.append_semantic_events(
            state.recent_events,
            game=state.game,
            role_context=state.self_state.role,
            tags=[state.self_state.role or "unknown"],
        )

        self._world_model.update(state)
        self._update_shared_junctions(state)
        self._world_model.prune_missing_extractors(
            current_position=_h.absolute_position(state),
            visible_entities=state.visible_entities,
            obs_width=self.policy_env_info.obs_width,
            obs_height=self.policy_env_info.obs_height,
        )
        current_pos = _h.absolute_position(state)
        self._update_temp_blocks(current_pos)
        self._update_stall_counter(state, current_pos)

        directive = self._sanitize_macro_directive(self._macro_directive(state))
        self._current_directive = directive
        self._resource_bias = (
            self._default_resource_bias if directive.resource_bias is None else directive.resource_bias
        )
        role = directive.role or self._desired_role(state, objective=directive.objective)
        action, summary = self._choose_action(state, role)
        self._record_navigation_observation(current_pos, summary)
        macro_snapshot = self._macro_snapshot(state, role)
        self._infos = {
            "role": role,
            "subtask": summary,
            "summary": summary,
            "oscillation_steps": self._oscillation_steps,
            "phase": _h.phase_name(state, role),
            "heart": int(state.self_state.inventory.get("heart", 0)),
            "heart_batch_target": _h.heart_batch_target(state, role),
            "target_kind": self._current_target_kind or "",
            "target_position": (
                "" if self._current_target_position is None else _h.format_position(self._current_target_position)
            ),
            "directive_role": directive.role or "",
            "directive_resource_bias": directive.resource_bias or "",
            "directive_objective": directive.objective or "",
            "directive_note": directive.note,
            "directive_target_entity_id": directive.target_entity_id or "",
            "directive_target_region": directive.target_region or "",
            **macro_snapshot,
        }
        self._previous_state = state
        self._last_global_pos = current_pos
        self._last_inventory_signature = _h.inventory_signature(state)
        return action

    def reset(self, simulation=None) -> None:
        self._memory = MemoryStore()
        self._previous_state = None
        self._world_model.reset()
        self._last_global_pos = None
        self._last_attempt = None
        self._temp_blocks.clear()
        self._step_index = 0
        self._explore_index = 0
        self._resource_bias = self._default_resource_bias
        self._last_inventory_signature = None
        self._stalled_steps = 0
        self._oscillation_steps = 0
        self._recent_navigation.clear()
        self._clear_target_claim()
        self._clear_sticky_target()
        self._current_directive = MacroDirective()
        self._infos = {}

    def _macro_directive(self, state: MettagridState) -> MacroDirective:
        del state
        return MacroDirective()

    def render_skill_library(self) -> str:
        return _COGSGUARD_SURFACE.render_skill_library()

    def _sanitize_macro_directive(self, directive: MacroDirective) -> MacroDirective:
        role = directive.role if directive.role in {"miner", "aligner", "scrambler", "scout"} else None
        resource_bias = directive.resource_bias if directive.resource_bias in _h._ELEMENTS else None
        note = directive.note.strip()
        objective = directive.objective.strip() if directive.objective is not None else None
        target_entity_id = directive.target_entity_id.strip() if directive.target_entity_id is not None else None
        target_region = directive.target_region.strip() if directive.target_region is not None else None
        return MacroDirective(
            role=role,
            target_entity_id=target_entity_id or None,
            target_region=target_region or None,
            resource_bias=resource_bias,
            objective=objective or None,
            note=note,
            metadata=dict(directive.metadata),
        )

    def _desired_role(self, state: MettagridState, *, objective: str | None = None) -> str:
        aligner_budget, scrambler_budget = self._pressure_budgets(state, objective=objective)
        team_ids = self._shared_team_ids
        if team_ids:
            # Use team-relative role assignment: filter priorities to agents we control
            team_scrambler_priority = [aid for aid in _SCRAMBLER_PRIORITY if aid in team_ids]
            team_aligner_priority = [aid for aid in _ALIGNER_PRIORITY if aid in team_ids]
            scrambler_ids = set(team_scrambler_priority[:scrambler_budget])
            aligner_ids = []
            for agent_id in team_aligner_priority:
                if agent_id in scrambler_ids:
                    continue
                if len(aligner_ids) == aligner_budget:
                    break
                aligner_ids.append(agent_id)
        else:
            # Fallback: original global priority behavior
            scrambler_ids = set(_SCRAMBLER_PRIORITY[:scrambler_budget])
            aligner_ids = []
            for agent_id in _ALIGNER_PRIORITY:
                if agent_id in scrambler_ids:
                    continue
                if len(aligner_ids) == aligner_budget:
                    break
                aligner_ids.append(agent_id)
        if self._agent_id in scrambler_ids:
            return "scrambler"
        if self._agent_id in aligner_ids:
            return "aligner"
        return "miner"

    def _choose_action(self, state: MettagridState, role: str) -> tuple[Action, str]:
        if role not in {"aligner", "miner"}:
            self._clear_target_claim()
            self._clear_sticky_target()
        elif role == "aligner" and self._sticky_target_kind not in {None, "junction"}:
            self._clear_sticky_target()
        elif role == "miner" and (
            self._sticky_target_kind is not None and not self._sticky_target_kind.endswith("_extractor")
        ):
            self._clear_sticky_target()
        safe_target = self._nearest_hub(state)
        safe_distance = 0 if safe_target is None else _h.manhattan(_h.absolute_position(state), safe_target.position)

        # EARLY-GAME SURVIVAL: HP starts at 50, drains 1/tick, territory heals +100/tick.
        # Territory radius is 10 tiles from hub/network junctions.
        hp = int(state.self_state.inventory.get("hp", 0))
        step = state.step or self._step_index

        # Stay at hub until HP reaches 100. Territory heals +100/tick when in range.
        # Short timeout: if healed to 100+ by step 20, move on. Otherwise extend wait.
        if hp < 100 and hp > 0 and safe_target is not None and safe_distance <= 3 and step <= 20:
            return self._hold(summary="hub_camp_heal", vibe="change_vibe_default")

        # If HP dropping in early game, rush to hub immediately.
        if step < 150 and safe_target is not None and hp > 0 and hp < 40:
            if safe_distance > 2:
                return self._move_to_known(state, safe_target, summary="survival_retreat")
            return self._hold(summary="survival_hold", vibe="change_vibe_default")

        # WIPEOUT RECOVERY: If hp=0, stay near hub to try to trigger healing.
        if hp == 0 and safe_target is not None:
            if safe_distance > 3:
                return self._move_to_known(state, safe_target, summary="wipeout_return_hub")
            return self._hold(summary="wipeout_hub_hold", vibe="change_vibe_default")

        if self._should_retreat(state, role, safe_target):
            self._clear_target_claim()
            self._clear_sticky_target()
            if safe_target is not None and safe_distance > 2:
                return self._move_to_known(state, safe_target, summary="retreat_to_hub")
            if _h.has_role_gear(state, role):
                return self._hold(summary="retreat_hold", vibe="change_vibe_default")

        if self._oscillation_steps >= _OSCILLATION_UNSTICK_STEPS:
            return self._unstick_action(state, role)

        if self._stalled_steps >= 12:
            return self._unstick_action(state, role)

        if role != "miner" and _h.needs_emergency_mining(state):
            return self._miner_action(state, summary_prefix="emergency_")

        if role == "aligner" and not _h.has_role_gear(state, role):
            if (state.step or self._step_index) < _ALIGNER_GEAR_DELAY_STEPS:
                self._clear_target_claim()
                self._clear_sticky_target()
                return self._miner_action(state, summary_prefix="delay_gear_")

        if not _h.has_role_gear(state, role):
            self._clear_target_claim()
            self._clear_sticky_target()
            if not _h.team_can_afford_gear(state, role):
                return self._miner_action(state, summary_prefix=f"fund_{role}_gear_")
            return self._acquire_role_gear(state, role)

        if role == "miner":
            return self._miner_action(state)
        if role == "aligner":
            return self._aligner_action(state)
        if role == "scrambler":
            return self._scrambler_action(state)
        return self._explore_action(state, role=role, summary="explore")

    def _acquire_role_gear(self, state: MettagridState, role: str) -> tuple[Action, str]:
        station_type = f"{role}_station"
        current_pos = _h.absolute_position(state)
        station = self._world_model.nearest(position=current_pos, entity_type=station_type)
        if station is not None:
            return self._move_to_known(state, station, summary=f"get_{role}_gear", vibe="change_vibe_gear")

        hub = self._nearest_hub(state)
        if hub is None:
            return self._explore_action(state, role=role, summary=f"find_{role}_station")
        relative_target = _h.spawn_relative_station_target(self._agent_id, role)
        if relative_target is not None:
            target = (hub.global_x + relative_target[0], hub.global_y + relative_target[1])
        else:
            dx, dy = _STATION_OFFSETS[role]
            target = (hub.global_x + dx, hub.global_y + dy)
        return self._move_to_position(state, target, summary=f"search_{role}_station", vibe="change_vibe_gear")

    def _miner_action(self, state: MettagridState, summary_prefix: str = "") -> tuple[Action, str]:
        if self._should_deposit_resources(state):
            depot = self._nearest_friendly_depot(state)
            if depot is not None:
                return self._move_to_known(
                    state,
                    depot,
                    summary=f"{summary_prefix}deposit_resources",
                    vibe="change_vibe_miner",
                )

        extractor = self._preferred_miner_extractor(state)
        if extractor is not None:
            self._set_sticky_target(extractor.position, extractor.entity_type)
            return self._move_to_known(
                state,
                extractor,
                summary=f"{summary_prefix}mine_{extractor.entity_type.removesuffix('_extractor')}",
                vibe="change_vibe_miner",
            )

        self._clear_sticky_target()
        return self._explore_action(state, role="miner", summary=f"{summary_prefix}find_extractors")

    def _aligner_action(self, state: MettagridState) -> tuple[Action, str]:
        hearts = int(state.self_state.inventory.get("heart", 0))
        hub = self._nearest_hub(state)
        if hearts <= 0:
            self._clear_target_claim()
            self._clear_sticky_target()
            if not _h.team_can_refill_hearts(state):
                return self._miner_action(state, summary_prefix="rebuild_hearts_")
            if hub is not None:
                return self._move_to_known(state, hub, summary="acquire_heart", vibe="change_vibe_heart")
            return self._explore_action(state, role="aligner", summary="find_hub_for_heart")
        if _h.should_batch_hearts(state, role="aligner", hub_position=hub.position if hub else None):
            self._clear_target_claim()
            self._clear_sticky_target()
            assert hub is not None
            return self._move_to_known(state, hub, summary="batch_hearts", vibe="change_vibe_heart")

        target = self._preferred_alignable_neutral_junction(state)
        if target is not None:
            self._claim_target(target.position)
            self._set_sticky_target(target.position, target.entity_type)
            return self._move_to_known(state, target, summary="align_junction", vibe="change_vibe_aligner")

        self._clear_target_claim()
        self._clear_sticky_target()
        if _h.resource_total(state) > 0:
            depot = self._nearest_friendly_depot(state)
            if depot is not None:
                return self._move_to_known(state, depot, summary="deposit_cargo", vibe="change_vibe_aligner")

        return self._explore_action(state, role="aligner", summary="find_neutral_junction")

    def _scrambler_action(self, state: MettagridState) -> tuple[Action, str]:
        hearts = int(state.self_state.inventory.get("heart", 0))
        hub = self._nearest_hub(state)
        if hearts <= 0:
            self._clear_sticky_target()
            if not _h.team_can_refill_hearts(state):
                return self._miner_action(state, summary_prefix="rebuild_hearts_")
            if hub is not None:
                return self._move_to_known(state, hub, summary="acquire_heart", vibe="change_vibe_heart")
            return self._explore_action(state, role="scrambler", summary="find_hub_for_heart")
        if _h.should_batch_hearts(state, role="scrambler", hub_position=hub.position if hub else None):
            self._clear_sticky_target()
            assert hub is not None
            return self._move_to_known(state, hub, summary="batch_hearts", vibe="change_vibe_heart")

        target = self._preferred_scramble_target(state)
        if target is not None:
            self._set_sticky_target(target.position, target.entity_type)
            return self._move_to_known(state, target, summary="scramble_junction", vibe="change_vibe_scrambler")

        self._clear_sticky_target()
        return self._explore_action(state, role="scrambler", summary="find_enemy_junction")

    def _explore_action(self, state: MettagridState, *, role: str, summary: str) -> tuple[Action, str]:
        current_pos = _h.absolute_position(state)
        hub = self._nearest_hub(state)
        center = (hub.global_x, hub.global_y) if hub is not None else current_pos
        offsets = _h.explore_offsets(role)
        offset_index = (self._explore_index + self._agent_id) % len(offsets)
        target = offsets[offset_index]
        absolute_target = (center[0] + target[0], center[1] + target[1])
        if _h.manhattan(current_pos, absolute_target) <= 2:
            self._explore_index += 1
            offset_index = (self._explore_index + self._agent_id) % len(offsets)
            target = offsets[offset_index]
            absolute_target = (center[0] + target[0], center[1] + target[1])
        return self._move_to_position(state, absolute_target, summary=summary, vibe=_h.role_vibe(role))

    def _move_to_known(
        self,
        state: MettagridState,
        entity: KnownEntity,
        *,
        summary: str,
        vibe: str | None = None,
    ) -> tuple[Action, str]:
        self._current_target_position = entity.position
        self._current_target_kind = entity.entity_type
        return self._move_to_position(state, entity.position, summary=summary, vibe=vibe)

    def _move_to_position(
        self,
        state: MettagridState,
        target: tuple[int, int],
        *,
        summary: str,
        vibe: str | None = None,
    ) -> tuple[Action, str]:
        self._current_target_position = target
        self._current_target_kind = self._current_target_kind or "position"
        current = _h.absolute_position(state)
        next_step = self._next_step(current, target)
        if next_step is None:
            self._last_attempt = None
            return self._hold(summary=f"{summary}_hold", vibe=vibe)

        direction = _h.direction_from_step(current, next_step)
        stationary_use = next_step == target and self._world_model.is_occupied(target)
        self._last_attempt = MoveAttempt(direction=direction, stationary_use=stationary_use)
        return self._action(f"move_{direction}", vibe=vibe), summary

    def _hold(self, *, summary: str, vibe: str | None = None) -> tuple[Action, str]:
        self._last_attempt = None
        if "retreat" in summary:
            self._current_target_kind = "retreat"
        return self._action(self._fallback_action, vibe=vibe), summary

    def _claim_target(self, target: tuple[int, int]) -> None:
        self._clear_stale_claims()
        self._clear_target_claim()
        self._shared_claims[target] = (self._agent_id, self._step_index)
        self._claimed_target = target

    def _clear_target_claim(self) -> None:
        if self._claimed_target is None:
            return
        claim = self._shared_claims.get(self._claimed_target)
        if claim is not None and claim[0] == self._agent_id:
            self._shared_claims.pop(self._claimed_target)
        self._claimed_target = None

    def _set_sticky_target(self, position: tuple[int, int], entity_type: str) -> None:
        self._sticky_target_position = position
        self._sticky_target_kind = entity_type

    def _clear_sticky_target(self) -> None:
        self._sticky_target_position = None
        self._sticky_target_kind = None

    def _clear_stale_claims(self) -> None:
        stale_positions = [
            position
            for position, (_, step) in self._shared_claims.items()
            if self._step_index - step > _h._TARGET_CLAIM_STEPS
        ]
        for position in stale_positions:
            self._shared_claims.pop(position)

    def _next_step(self, current: tuple[int, int], target: tuple[int, int]) -> tuple[int, int] | None:
        if current == target:
            return None

        blocked = self._world_model.occupied_cells(exclude={target})
        blocked.update(cell for cell, until_step in self._temp_blocks.items() if until_step >= self._step_index)
        if _h.manhattan(current, target) <= 1:
            return target

        min_x = min(current[0], target[0]) - _DEFAULT_BOUND_MARGIN
        max_x = max(current[0], target[0]) + _DEFAULT_BOUND_MARGIN
        min_y = min(current[1], target[1]) - _DEFAULT_BOUND_MARGIN
        max_y = max(current[1], target[1]) + _DEFAULT_BOUND_MARGIN

        frontier: list[tuple[int, int, tuple[int, int]]] = [(0, 0, current)]
        came_from: dict[tuple[int, int], tuple[int, int]] = {}
        best_cost = {current: 0}

        while frontier:
            _, cost, node = heapq.heappop(frontier)
            if node == target:
                break
            if cost > best_cost.get(node, cost):
                continue
            for dx, dy in _h._MOVE_DELTAS.values():
                nxt = (node[0] + dx, node[1] + dy)
                if nxt in blocked:
                    continue
                if nxt[0] < min_x or nxt[0] > max_x or nxt[1] < min_y or nxt[1] > max_y:
                    continue
                next_cost = cost + 1
                if next_cost >= best_cost.get(nxt, 1 << 30):
                    continue
                best_cost[nxt] = next_cost
                came_from[nxt] = node
                priority = next_cost + _h.manhattan(nxt, target)
                heapq.heappush(frontier, (priority, next_cost, nxt))

        if target not in came_from:
            return _h.greedy_step(current, target, blocked)

        step = target
        while came_from[step] != current:
            step = came_from[step]
        return step

    def _update_temp_blocks(self, current_pos: tuple[int, int]) -> None:
        self._temp_blocks = {
            cell: until_step for cell, until_step in self._temp_blocks.items() if until_step >= self._step_index
        }
        if self._last_attempt is None or self._last_global_pos is None:
            return
        if current_pos != self._last_global_pos:
            return
        if self._last_attempt.stationary_use:
            return
        dx, dy = _h._MOVE_DELTAS[self._last_attempt.direction]
        blocked_cell = (current_pos[0] + dx, current_pos[1] + dy)
        self._temp_blocks[blocked_cell] = self._step_index + _TEMP_BLOCK_STEPS

    def _nearest_hub(self, state: MettagridState) -> KnownEntity | None:
        hub = self._world_model.nearest(
            position=_h.absolute_position(state),
            entity_type="hub",
            predicate=lambda entity: entity.team == _h.team_id(state),
        )
        if hub is not None:
            return hub

        bootstrap_offset = _HUB_OFFSETS.get(self._agent_id)
        if bootstrap_offset is None:
            return None
        return KnownEntity(
            entity_type="hub",
            global_x=bootstrap_offset[0],
            global_y=bootstrap_offset[1],
            labels=(),
            team=_h.team_id(state),
            owner=_h.team_id(state),
            last_seen_step=state.step or self._step_index,
            attributes={},
        )

    def _nearest_friendly_depot(self, state: MettagridState) -> KnownEntity | None:
        team_id = _h.team_id(state)
        depot = self._world_model.nearest(
            position=_h.absolute_position(state),
            predicate=lambda entity: (
                (entity.entity_type == "hub" and entity.team == team_id)
                or (entity.entity_type == "junction" and entity.owner == team_id)
            ),
        )
        shared_friendly = self._shared_junction_entities(state, predicate=lambda entity: entity.owner == team_id)
        if shared_friendly:
            shared_nearest = min(
                shared_friendly,
                key=lambda entity: (_h.manhattan(_h.absolute_position(state), entity.position), entity.position),
            )
            if depot is None or _h.manhattan(_h.absolute_position(state), shared_nearest.position) < _h.manhattan(
                _h.absolute_position(state), depot.position
            ):
                depot = shared_nearest
        if depot is not None:
            return depot
        return self._nearest_hub(state)

    def _update_shared_junctions(self, state: MettagridState) -> None:
        hub = self._nearest_hub(state)
        if hub is None:
            return
        team_id = _h.team_id(state)
        for entity in state.visible_entities:
            if entity.entity_type != "junction":
                continue
            rel_position = (
                int(entity.attributes["global_x"]) - hub.global_x,
                int(entity.attributes["global_y"]) - hub.global_y,
            )
            owner = entity.attributes.get("owner")
            new_owner = None if owner in {None, "neutral"} else str(owner)
            # Detect scramble: junction was ours, now it's not
            old = self._shared_junctions.get(rel_position)
            if old is not None:
                old_owner, _ = old
                if old_owner == team_id and new_owner != team_id:
                    self._shared_hotspots[rel_position] = self._shared_hotspots.get(rel_position, 0) + 1
            self._shared_junctions[rel_position] = (new_owner, state.step or self._step_index)

    def _shared_junction_entities(
        self,
        state: MettagridState,
        *,
        predicate: Callable[[KnownEntity], bool],
    ) -> list[KnownEntity]:
        hub = self._nearest_hub(state)
        if hub is None:
            return []
        step = state.step or self._step_index
        result = []
        for (dx, dy), (owner, last_seen_step) in self._shared_junctions.items():
            if step - last_seen_step > _SHARED_JUNCTION_MEMORY_STEPS:
                continue
            entity = KnownEntity(
                entity_type="junction",
                global_x=hub.global_x + dx,
                global_y=hub.global_y + dy,
                labels=(),
                team=owner,
                owner=owner,
                last_seen_step=last_seen_step,
                attributes={},
            )
            if predicate(entity):
                result.append(entity)
        return result

    def _known_junctions(
        self,
        state: MettagridState,
        *,
        predicate: Callable[[KnownEntity], bool],
    ) -> list[KnownEntity]:
        by_position = {
            entity.position: entity
            for entity in self._world_model.entities(entity_type="junction", predicate=predicate)
        }
        for entity in self._shared_junction_entities(state, predicate=predicate):
            by_position.setdefault(entity.position, entity)
        return list(by_position.values())

    def _nearest_alignable_neutral_junction(self, state: MettagridState) -> KnownEntity | None:
        team_id = _h.team_id(state)
        current_pos = _h.absolute_position(state)
        hub = self._nearest_hub(state)
        hub_pos = hub.position if hub is not None else None
        hubs = self._world_model.entities(entity_type="hub", predicate=lambda entity: entity.team == team_id)
        friendly_junctions = self._known_junctions(state, predicate=lambda entity: entity.owner == team_id)
        network_sources = [*hubs, *friendly_junctions]
        candidates = []
        for entity in self._known_junctions(state, predicate=lambda junction: junction.owner in {None, "neutral"}):
            if not _h.within_alignment_network(entity.position, network_sources):
                continue
            candidates.append(entity)
        if not candidates:
            return None
        directed_candidate = self._directive_target_candidate(candidates)
        if directed_candidate is not None:
            return directed_candidate
        enemy_junctions = self._known_junctions(
            state,
            predicate=lambda junction: junction.owner not in {None, "neutral", team_id},
        )
        unreachable = [
            entity
            for entity in self._known_junctions(state, predicate=lambda junction: junction.owner in {None, "neutral"})
            if entity not in candidates
        ]
        return min(
            candidates,
            key=lambda entity: (
                _h.aligner_target_score(
                    current_position=current_pos,
                    candidate=entity,
                    unreachable=unreachable,
                    enemy_junctions=enemy_junctions,
                    claimed_by_other=_h.is_claimed_by_other(
                        claims=self._shared_claims,
                        candidate=entity.position,
                        agent_id=self._agent_id,
                        step=self._step_index,
                    ),
                    hub_position=hub_pos,
                    friendly_junctions=friendly_junctions,
                    hotspot_count=self._junction_hotspot_count(entity, hub),
                    network_weight=self._network_weight,
                    hotspot_weight=self._hotspot_weight,
                    expansion_weight=self._expansion_weight,
                    expansion_cap=self._expansion_cap,
                ),
                entity.position,
            ),
        )

    def _preferred_alignable_neutral_junction(self, state: MettagridState) -> KnownEntity | None:
        candidate = self._nearest_alignable_neutral_junction(state)
        sticky = self._sticky_align_target(state)
        if sticky is None:
            return candidate
        if candidate is None:
            return sticky

        current_pos = _h.absolute_position(state)
        team_id = _h.team_id(state)
        neutral_junctions = self._world_model.entities(
            entity_type="junction",
            predicate=lambda junction: junction.owner in {None, "neutral"},
        )
        enemy_junctions = self._world_model.entities(
            entity_type="junction",
            predicate=lambda junction: junction.owner not in {None, "neutral", team_id},
        )
        hub = self._nearest_hub(state)
        hub_pos = hub.position if hub is not None else None
        friendly_junctions = self._world_model.entities(
            entity_type="junction",
            predicate=lambda junction: junction.owner == team_id,
        )
        sticky_score = _h.aligner_target_score(
            current_position=current_pos,
            candidate=sticky,
            unreachable=[entity for entity in neutral_junctions if entity.position != sticky.position],
            enemy_junctions=enemy_junctions,
            claimed_by_other=False,
            hub_position=hub_pos,
            friendly_junctions=friendly_junctions,
            hotspot_count=self._junction_hotspot_count(sticky, hub),
            network_weight=self._network_weight,
            hotspot_weight=self._hotspot_weight,
        )[0]
        candidate_score = _h.aligner_target_score(
            current_position=current_pos,
            candidate=candidate,
            unreachable=[entity for entity in neutral_junctions if entity.position != candidate.position],
            enemy_junctions=enemy_junctions,
            claimed_by_other=_h.is_claimed_by_other(
                claims=self._shared_claims,
                candidate=candidate.position,
                agent_id=self._agent_id,
                step=self._step_index,
            ),
            hub_position=hub_pos,
            friendly_junctions=friendly_junctions,
            hotspot_count=self._junction_hotspot_count(candidate, hub),
            network_weight=self._network_weight,
            hotspot_weight=self._hotspot_weight,
        )[0]
        if candidate.position != sticky.position and candidate_score + _TARGET_SWITCH_THRESHOLD < sticky_score:
            return candidate
        return sticky

    def _sticky_align_target(self, state: MettagridState) -> KnownEntity | None:
        if self._sticky_target_kind != "junction" or self._sticky_target_position is None:
            return None
        team_id = _h.team_id(state)
        hubs = self._world_model.entities(entity_type="hub", predicate=lambda entity: entity.team == team_id)
        friendly_junctions = self._known_junctions(state, predicate=lambda entity: entity.owner == team_id)
        target = next(
            (
                entity
                for entity in self._known_junctions(state, predicate=lambda entity: entity.owner in {None, "neutral"})
                if entity.position == self._sticky_target_position
            ),
            None,
        )
        if target is None:
            self._clear_sticky_target()
            return None
        if not _h.within_alignment_network(target.position, [*hubs, *friendly_junctions]):
            self._clear_sticky_target()
            return None
        return target

    def _preferred_miner_extractor(self, state: MettagridState) -> KnownEntity | None:
        if self._should_force_miner_explore_reset(state):
            self._clear_sticky_target()
            return None

        current_pos = _h.absolute_position(state)
        candidates: list[KnownEntity] = []
        for resource_name in _h.resource_priority(state, resource_bias=self._resource_bias):
            matches = self._world_model.entities(
                entity_type=f"{resource_name}_extractor",
                predicate=lambda entity: _h.is_usable_recent_extractor(entity, step=state.step or self._step_index),
            )
            candidates.extend(
                sorted(
                    matches,
                    key=lambda entity: (_h.manhattan(current_pos, entity.position), entity.position),
                )
            )
        if not candidates:
            return None

        directed_candidate = self._directive_target_candidate(candidates)
        if directed_candidate is not None:
            return directed_candidate

        sticky = self._sticky_miner_target(state)
        if sticky is None:
            return candidates[0]

        candidate = candidates[0]
        sticky_distance = _h.manhattan(current_pos, sticky.position)
        candidate_distance = _h.manhattan(current_pos, candidate.position)
        if candidate.position != sticky.position and candidate_distance + _TARGET_SWITCH_THRESHOLD < sticky_distance:
            return candidate
        return sticky

    def _should_force_miner_explore_reset(self, state: MettagridState) -> bool:
        if self._stalled_steps < 12:
            return False
        if any(entity.entity_type.endswith("_extractor") for entity in state.visible_entities):
            return False
        hub = self._nearest_hub(state)
        if hub is None:
            return False
        return _h.manhattan(_h.absolute_position(state), hub.position) <= 1

    def _sticky_miner_target(self, state: MettagridState) -> KnownEntity | None:
        if self._sticky_target_kind is None or self._sticky_target_position is None:
            return None
        if not self._sticky_target_kind.endswith("_extractor"):
            return None
        target = next(
            (
                entity
                for entity in self._world_model.entities(
                    entity_type=self._sticky_target_kind,
                    predicate=lambda entity: _h.is_usable_recent_extractor(entity, step=state.step or self._step_index),
                )
                if entity.position == self._sticky_target_position
            ),
            None,
        )
        if target is None:
            self._clear_sticky_target()
            return None
        return target

    def _best_scramble_target(self, state: MettagridState) -> KnownEntity | None:
        team_id = _h.team_id(state)
        current_pos = _h.absolute_position(state)
        hub = self._nearest_hub(state)
        neutral_junctions = self._known_junctions(state, predicate=lambda entity: entity.owner in {None, "neutral"})
        friendly_junctions = self._known_junctions(state, predicate=lambda entity: entity.owner == team_id)
        enemy_junctions = self._known_junctions(
            state,
            predicate=lambda entity: entity.owner not in {None, "neutral", team_id},
        )
        if not enemy_junctions:
            return None
        directed_candidate = self._directive_target_candidate(enemy_junctions)
        if directed_candidate is not None:
            return directed_candidate
        hub_position = current_pos if hub is None else hub.position
        return min(
            enemy_junctions,
            key=lambda entity: (
                _h.scramble_target_score(
                    current_position=current_pos,
                    hub_position=hub_position,
                    candidate=entity,
                    neutral_junctions=neutral_junctions,
                    friendly_junctions=friendly_junctions,
                ),
                entity.position,
            ),
        )

    def _directive_target_candidate(self, candidates: list[KnownEntity]) -> KnownEntity | None:
        if not candidates:
            return None
        target_entity_id = self._current_directive.target_entity_id
        if target_entity_id is not None:
            for entity in candidates:
                if f"{entity.entity_type}@{entity.global_x},{entity.global_y}" == target_entity_id:
                    return entity
        target_region = self._current_directive.target_region
        if target_region is None:
            return None
        region = target_region.strip()
        if not region:
            return None
        for entity in candidates:
            if region in entity.labels:
                return entity
            if region in {value for value in entity.attributes.values() if isinstance(value, str)}:
                return entity
        return None

    def _preferred_scramble_target(self, state: MettagridState) -> KnownEntity | None:
        candidate = self._best_scramble_target(state)
        sticky = self._sticky_scramble_target(state)
        if sticky is None:
            return candidate
        if candidate is None:
            return sticky

        current_pos = _h.absolute_position(state)
        hub = self._nearest_hub(state)
        hub_position = current_pos if hub is None else hub.position
        neutral_junctions = self._world_model.entities(
            entity_type="junction",
            predicate=lambda entity: entity.owner in {None, "neutral"},
        )
        sticky_score = _h.scramble_target_score(
            current_position=current_pos,
            hub_position=hub_position,
            candidate=sticky,
            neutral_junctions=neutral_junctions,
        )[0]
        candidate_score = _h.scramble_target_score(
            current_position=current_pos,
            hub_position=hub_position,
            candidate=candidate,
            neutral_junctions=neutral_junctions,
        )[0]
        if candidate.position != sticky.position and candidate_score + _TARGET_SWITCH_THRESHOLD < sticky_score:
            return candidate
        return sticky

    def _sticky_scramble_target(self, state: MettagridState) -> KnownEntity | None:
        if self._sticky_target_kind != "junction" or self._sticky_target_position is None:
            return None
        team_id = _h.team_id(state)
        target = next(
            (
                entity
                for entity in self._known_junctions(
                    state,
                    predicate=lambda entity: entity.owner not in {None, "neutral", team_id},
                )
                if entity.position == self._sticky_target_position
            ),
            None,
        )
        if target is None:
            self._clear_sticky_target()
            return None
        return target

    def _macro_snapshot(self, state: MettagridState, role: str) -> dict[str, int | str | bool]:
        safe_target = self._nearest_friendly_depot(state)
        safe_distance = 0 if safe_target is None else _h.manhattan(_h.absolute_position(state), safe_target.position)
        hp = int(state.self_state.inventory.get("hp", 0))
        team_id = _h.team_id(state)
        in_enemy_aoe = self._in_enemy_aoe(state, _h.absolute_position(state), team_id=team_id)
        low_hp_risk = self._should_retreat(state, role, safe_target)
        payload_at_risk = low_hp_risk and (
            int(state.self_state.inventory.get("heart", 0)) > 0 or _h.resource_total(state) > 0
        )
        pressure_metrics = self._pressure_metrics(state)
        aligner_budget, scrambler_budget = self._pressure_budgets(state)
        heart_supply = _h.heart_supply_capacity(state)

        macro_note = (
            f"frontier={pressure_metrics.frontier_neutral_junctions} "
            f"best_cover={pressure_metrics.best_frontier_coverage} "
            f"best_scramble={pressure_metrics.best_enemy_scramble_block} "
            f"pressure={aligner_budget + scrambler_budget} "
            f"safe_distance={safe_distance}"
        )
        return {
            "hp": hp,
            "safe_distance": safe_distance,
            "low_hp_risk": low_hp_risk,
            "payload_at_risk": payload_at_risk,
            "team_can_afford_role_gear": _h.team_can_afford_gear(state, role),
            "in_enemy_aoe": in_enemy_aoe,
            "frontier_neutral_junctions": pressure_metrics.frontier_neutral_junctions,
            "best_frontier_coverage": pressure_metrics.best_frontier_coverage,
            "best_enemy_scramble_block": pressure_metrics.best_enemy_scramble_block,
            "heart_supply": heart_supply,
            "pressure_budget": aligner_budget + scrambler_budget,
            "aligner_budget": aligner_budget,
            "scrambler_budget": scrambler_budget,
            "macro_note": macro_note,
        }

    def _pressure_metrics(self, state: MettagridState) -> PressureMetrics:
        team_id = _h.team_id(state)
        hub = self._nearest_hub(state)
        friendly_sources = []
        if hub is not None:
            friendly_sources.append(hub)
        friendly_sources.extend(self._known_junctions(state, predicate=lambda entity: entity.owner == team_id))
        neutral_junctions = self._known_junctions(state, predicate=lambda entity: entity.owner in {None, "neutral"})
        frontier_junctions = [
            entity for entity in neutral_junctions if _h.within_alignment_network(entity.position, friendly_sources)
        ]
        unreachable_junctions = [entity for entity in neutral_junctions if entity not in frontier_junctions]
        best_frontier_coverage = max(
            (
                sum(
                    1
                    for neutral in unreachable_junctions
                    if _h.manhattan(candidate.position, neutral.position) <= _h._JUNCTION_ALIGN_DISTANCE
                )
                for candidate in frontier_junctions
            ),
            default=0,
        )
        enemy_junctions = self._known_junctions(
            state,
            predicate=lambda entity: entity.owner not in {None, "neutral", team_id},
        )
        best_enemy_scramble_block = max(
            (
                sum(
                    1
                    for neutral in neutral_junctions
                    if _h.manhattan(enemy.position, neutral.position) <= _h._JUNCTION_AOE_RANGE
                )
                for enemy in enemy_junctions
            ),
            default=0,
        )
        return PressureMetrics(
            frontier_neutral_junctions=len(frontier_junctions),
            best_frontier_coverage=best_frontier_coverage,
            best_enemy_scramble_block=best_enemy_scramble_block,
        )

    def _pressure_budgets(self, state: MettagridState, *, objective: str | None = None) -> tuple[int, int]:
        step = state.step or self._step_index
        min_res = _h.team_min_resource(state)
        can_hearts = _h.team_can_refill_hearts(state)

        # 2 aligners first 30 steps, then ramp up aggressively.
        if step < 30:
            pressure_budget = 2
        elif step < 3000:
            pressure_budget = 5  # 4 aligners + 1 scrambler, 3 miners
            if min_res < 1 and not can_hearts:
                pressure_budget = 2  # Critical: 6 miners
            elif min_res < 3:
                pressure_budget = 4  # Low: 4 miners
        else:
            pressure_budget = 6  # Late game: 4a+2s, 2 miners
            if min_res < 1 and not can_hearts:
                pressure_budget = 3

        # Scramblers to disrupt ship chains
        scrambler_budget = 0
        if step >= 3000:
            scrambler_budget = 2
        elif step >= 100:
            scrambler_budget = 1
        aligner_budget = max(pressure_budget - scrambler_budget, 0)
        if objective == "resource_coverage":
            return 0, 0
        if objective == "economy_bootstrap":
            return min(aligner_budget, _ECONOMY_BOOTSTRAP_ALIGNER_BUDGET), 0
        return aligner_budget, scrambler_budget

    def _junction_hotspot_count(self, entity: KnownEntity, hub: KnownEntity | None) -> int:
        """Return how many times this junction has been scrambled (observed)."""
        if hub is None:
            return 0
        rel = (entity.global_x - hub.global_x, entity.global_y - hub.global_y)
        return self._shared_hotspots.get(rel, 0)

    def _in_enemy_aoe(self, state: MettagridState, position: tuple[int, int], *, team_id: str) -> bool:
        enemies = self._known_junctions(
            state,
            predicate=lambda entity: entity.owner not in {None, "neutral", team_id},
        )
        for enemy in enemies:
            if _h.manhattan(position, enemy.position) <= _h._JUNCTION_AOE_RANGE:
                return True
        return False

    def _should_retreat(self, state: MettagridState, role: str, safe_target: KnownEntity | None) -> bool:
        hp = int(state.self_state.inventory.get("hp", 0))
        if safe_target is None:
            return hp <= _h.retreat_threshold(state, role)

        safe_steps = max(0, _h.manhattan(_h.absolute_position(state), safe_target.position) - _h._JUNCTION_AOE_RANGE)
        margin = _RETREAT_MARGIN
        if self._in_enemy_aoe(state, _h.absolute_position(state), team_id=_h.team_id(state)):
            margin += 10
        margin += int(state.self_state.inventory.get("heart", 0)) * 5
        margin += min(_h.resource_total(state), 12) // 2
        if not _h.has_role_gear(state, role):
            margin += 10
        if (state.step or 0) >= 2_500:
            margin += 10 if role in {"aligner", "scrambler"} else 5
        return hp <= safe_steps + margin

    def _should_deposit_resources(self, state: MettagridState) -> bool:
        cargo = _h.resource_total(state)
        if cargo <= 0:
            return False
        if cargo >= _h.deposit_threshold(state):
            return True

        safe_target = self._nearest_friendly_depot(state)
        if safe_target is None:
            return cargo >= 4

        safe_distance = _h.manhattan(_h.absolute_position(state), safe_target.position)
        if cargo >= 16 and safe_distance > 18:
            return True
        if cargo >= 8 and self._should_retreat(state, "miner", safe_target):
            return True
        if cargo >= 12 and self._in_enemy_aoe(state, _h.absolute_position(state), team_id=_h.team_id(state)):
            return True
        return False

    def _action(self, name: str, *, vibe: str | None = None) -> Action:
        action_name = name if name in self._action_names else self._fallback_action
        vibe_name = vibe if vibe in self._vibe_actions else None
        return Action(name=action_name, vibe=vibe_name)

    def _update_stall_counter(self, state: MettagridState, current_pos: tuple[int, int]) -> None:
        inventory_signature = _h.inventory_signature(state)
        if self._last_global_pos == current_pos and self._last_inventory_signature == inventory_signature:
            self._stalled_steps += 1
        else:
            self._stalled_steps = 0

    def _record_navigation_observation(self, current_pos: tuple[int, int], summary: str) -> None:
        self._recent_navigation.append(
            NavigationObservation(
                position=current_pos,
                subtask=summary,
                target_kind=self._current_target_kind or "",
                target_position=self._current_target_position,
            )
        )
        self._oscillation_steps = self._extractor_oscillation_length()

    def _extractor_oscillation_length(self) -> int:
        if len(self._recent_navigation) < 2:
            return 0
        observations = list(self._recent_navigation)
        max_size = min(len(observations), _OSCILLATION_HISTORY_STEPS)
        for size in range(max_size, 1, -1):
            window = observations[-size:]
            first = window[0]
            second = window[1]
            if first.position == second.position:
                continue
            if not first.subtask.startswith("mine_"):
                continue
            if not first.target_kind.endswith("_extractor"):
                continue
            if first.target_position is None:
                continue
            if any(
                item.subtask != first.subtask
                or item.target_kind != first.target_kind
                or item.target_position != first.target_position
                for item in window
            ):
                continue
            if all(
                item.position == (first.position if index % 2 == 0 else second.position)
                for index, item in enumerate(window)
            ):
                return size
        return 0

    def _unstick_action(self, state: MettagridState, role: str) -> tuple[Action, str]:
        current = _h.absolute_position(state)
        if role == "miner":
            self._world_model.forget_nearest(
                position=current,
                entity_type=f"{self._resource_bias}_extractor",
                max_distance=2,
            )
            for resource_name in _h._ELEMENTS:
                self._world_model.forget_nearest(
                    position=current,
                    entity_type=f"{resource_name}_extractor",
                    max_distance=2,
                )
        self._explore_index += 1
        blocked = self._world_model.occupied_cells()
        blocked.update(cell for cell, until_step in self._temp_blocks.items() if until_step >= self._step_index)
        for direction in _h.unstick_directions(self._agent_id, self._step_index):
            dx, dy = _h._MOVE_DELTAS[direction]
            nxt = (current[0] + dx, current[1] + dy)
            if nxt in blocked:
                continue
            self._last_attempt = MoveAttempt(direction=direction, stationary_use=False)
            return self._action(f"move_{direction}", vibe=_h.role_vibe(role)), f"unstick_{role}"
        return self._hold(summary=f"unstick_{role}_hold", vibe=_h.role_vibe(role))


class MettagridSemanticPolicy(MultiAgentPolicy):
    short_names = ["mettagrid-semantic", "semantic-cog", "sdk-semantic"]

    def __init__(self, policy_env_info: PolicyEnvInterface, device: str = "cpu", **kwargs) -> None:
        super().__init__(policy_env_info, device=device, **kwargs)
        self._agent_policies: dict[int, SemanticCogAgentPolicy] = {}
        self._shared_claims: dict[tuple[int, int], tuple[int, int]] = {}
        self._shared_junctions: dict[tuple[int, int], tuple[str | None, int]] = {}
        self._shared_hotspots: dict[tuple[int, int], int] = {}
        self._shared_team_ids: set[int] = set()

    def agent_policy(self, agent_id: int) -> AgentPolicy:
        self._shared_team_ids.add(agent_id)
        if agent_id not in self._agent_policies:
            self._agent_policies[agent_id] = SemanticCogAgentPolicy(
                self.policy_env_info,
                agent_id=agent_id,
                world_model=SharedWorldModel(),
                shared_claims=self._shared_claims,
                shared_junctions=self._shared_junctions,
                shared_hotspots=self._shared_hotspots,
                shared_team_ids=self._shared_team_ids,
            )
        return self._agent_policies[agent_id]

    def reset(self) -> None:
        self._shared_claims.clear()
        self._shared_junctions.clear()
        self._shared_hotspots.clear()
        for policy in self._agent_policies.values():
            policy.reset()
