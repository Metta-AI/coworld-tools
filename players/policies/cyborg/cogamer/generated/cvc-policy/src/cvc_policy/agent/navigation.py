"""Navigation, pathfinding, and movement mixin."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import TYPE_CHECKING

from cvc_policy.agent import (
    ELEMENTS,
    _MOVE_DELTAS,
    KnownEntity,
    absolute_position,
    direction_from_step,
    explore_offsets,
    inventory_signature,
    manhattan,
    role_vibe,
    unstick_directions,
)
from cvc_policy.agent.pathfinding import (
    NavigationObservation,
    astar_next_step,
    detect_extractor_oscillation,
)
from mettagrid.sdk.agent import MettagridState
from mettagrid.simulator import Action

if TYPE_CHECKING:
    from cvc_policy.agent.world_model import WorldModel

_TEMP_BLOCK_STEPS = 10


@dataclass(slots=True)
class MoveAttempt:
    direction: str
    stationary_use: bool


class NavigationMixin:
    _world_model: WorldModel
    _step_index: int
    _agent_id: int
    _role_id: int
    _last_attempt: MoveAttempt | None
    _last_global_pos: tuple[int, int] | None
    _temp_blocks: dict[tuple[int, int], int]
    _stalled_steps: int
    _oscillation_steps: int
    _recent_navigation: deque[NavigationObservation]
    _current_target_position: tuple[int, int] | None
    _current_target_kind: str | None
    _explore_index: int
    _action_names: set[str]
    _vibe_actions: set[str]
    _fallback_action: str
    _resource_bias: str
    _last_inventory_signature: tuple[tuple[str, int], ...] | None

    def _action(self, name: str, *, vibe: str | None = None) -> Action:
        action_name = name if name in self._action_names else self._fallback_action
        vibe_name = vibe if vibe in self._vibe_actions else None
        return Action(name=action_name, vibe=vibe_name)

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
        current = absolute_position(state)
        next_step = self._next_step(current, target)
        if next_step is None:
            self._last_attempt = None
            return self._hold(summary=f"{summary}_hold", vibe=vibe)

        direction = direction_from_step(current, next_step)
        stationary_use = next_step == target and self._world_model.is_occupied(target)
        self._last_attempt = MoveAttempt(direction=direction, stationary_use=stationary_use)
        return self._action(f"move_{direction}", vibe=vibe), summary

    def _hold(self, *, summary: str, vibe: str | None = None) -> tuple[Action, str]:
        self._last_attempt = None
        if "retreat" in summary:
            self._current_target_kind = "retreat"
        return self._action(self._fallback_action, vibe=vibe), summary

    def _next_step(self, current: tuple[int, int], target: tuple[int, int]) -> tuple[int, int] | None:
        blocked = self._world_model.occupied_cells(exclude={target})
        blocked.update(cell for cell, until_step in self._temp_blocks.items() if until_step >= self._step_index)
        return astar_next_step(current, target, blocked)

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
        dx, dy = _MOVE_DELTAS[self._last_attempt.direction]
        blocked_cell = (current_pos[0] + dx, current_pos[1] + dy)
        self._temp_blocks[blocked_cell] = self._step_index + _TEMP_BLOCK_STEPS

    def _explore_action(self, state: MettagridState, *, role: str, summary: str) -> tuple[Action, str]:
        current_pos = absolute_position(state)
        hub = self._nearest_hub(state)  # type: ignore[attr-defined]
        center = (hub.global_x, hub.global_y) if hub is not None else current_pos
        offsets = explore_offsets(role)
        offset_index = (self._explore_index + self._role_id) % len(offsets)
        target = offsets[offset_index]
        absolute_target = (center[0] + target[0], center[1] + target[1])
        if manhattan(current_pos, absolute_target) <= 2:
            self._explore_index += 1
            offset_index = (self._explore_index + self._role_id) % len(offsets)
            target = offsets[offset_index]
            absolute_target = (center[0] + target[0], center[1] + target[1])
        return self._move_to_position(state, absolute_target, summary=summary, vibe=role_vibe(role))

    def _unstick_action(self, state: MettagridState, role: str) -> tuple[Action, str]:
        current = absolute_position(state)
        if role == "miner":
            self._world_model.forget_nearest(
                position=current,
                entity_type=f"{self._resource_bias}_extractor",
                max_distance=2,
            )
            for resource_name in ELEMENTS:
                self._world_model.forget_nearest(
                    position=current,
                    entity_type=f"{resource_name}_extractor",
                    max_distance=2,
                )
        self._explore_index += 1
        blocked = self._world_model.occupied_cells()
        blocked.update(cell for cell, until_step in self._temp_blocks.items() if until_step >= self._step_index)
        for direction in unstick_directions(self._agent_id, self._step_index):
            dx, dy = _MOVE_DELTAS[direction]
            nxt = (current[0] + dx, current[1] + dy)
            if nxt in blocked:
                continue
            self._last_attempt = MoveAttempt(direction=direction, stationary_use=False)
            return self._action(f"move_{direction}", vibe=role_vibe(role)), f"unstick_{role}"
        return self._hold(summary=f"unstick_{role}_hold", vibe=role_vibe(role))

    def _update_stall_counter(self, state: MettagridState, current_pos: tuple[int, int]) -> None:
        inv_sig = inventory_signature(state)
        if self._last_global_pos == current_pos and self._last_inventory_signature == inv_sig:
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
        self._oscillation_steps = detect_extractor_oscillation(list(self._recent_navigation))
