"""Role-specific action logic mixin (miner, aligner, scrambler)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from cogamer.cvc.agent import (
    absolute_position,
    resource_total,
    should_batch_hearts,
    spawn_relative_station_target,
    team_can_refill_hearts,
)
from mettagrid.sdk.agent import MettagridState
from mettagrid.simulator import Action

if TYPE_CHECKING:
    from cogamer.cvc.agent.world_model import WorldModel

_STATION_OFFSETS = {
    "aligner": (-3, 4),
    "scrambler": (-1, 4),
    "miner": (1, 4),
    "scout": (3, 4),
}


class RolesMixin:
    _world_model: WorldModel
    _agent_id: int
    _step_index: int

    def _acquire_role_gear(self, state: MettagridState, role: str) -> tuple[Action, str]:
        station_type = f"{role}_station"
        current_pos = absolute_position(state)
        station = self._world_model.nearest(position=current_pos, entity_type=station_type)
        if station is not None:
            return self._move_to_known(state, station, summary=f"get_{role}_gear", vibe="change_vibe_gear")  # type: ignore[attr-defined]

        target = spawn_relative_station_target(self._role_id, role)
        if target is None:
            hub = self._nearest_hub(state)  # type: ignore[attr-defined]
            if hub is None:
                return self._explore_action(state, role=role, summary=f"find_{role}_station")  # type: ignore[attr-defined]
            dx, dy = _STATION_OFFSETS[role]
            target = (hub.global_x + dx, hub.global_y + dy)
        return self._move_to_position(state, target, summary=f"search_{role}_station", vibe="change_vibe_gear")  # type: ignore[attr-defined]

    def _miner_action(self, state: MettagridState, summary_prefix: str = "") -> tuple[Action, str]:
        if self._should_deposit_resources(state):  # type: ignore[attr-defined]
            depot = self._nearest_friendly_depot(state)  # type: ignore[attr-defined]
            if depot is not None:
                return self._move_to_known(  # type: ignore[attr-defined]
                    state,
                    depot,
                    summary=f"{summary_prefix}deposit_resources",
                    vibe="change_vibe_miner",
                )

        extractor = self._preferred_miner_extractor(state)  # type: ignore[attr-defined]
        if extractor is not None:
            self._set_sticky_target(extractor.position, extractor.entity_type)  # type: ignore[attr-defined]
            return self._move_to_known(  # type: ignore[attr-defined]
                state,
                extractor,
                summary=f"{summary_prefix}mine_{extractor.entity_type.removesuffix('_extractor')}",
                vibe="change_vibe_miner",
            )

        self._clear_sticky_target()  # type: ignore[attr-defined]
        return self._explore_action(state, role="miner", summary=f"{summary_prefix}find_extractors")  # type: ignore[attr-defined]

    def _aligner_action(self, state: MettagridState) -> tuple[Action, str]:
        hearts = int(state.self_state.inventory.get("heart", 0))
        hub = self._nearest_hub(state)  # type: ignore[attr-defined]
        if hearts <= 0:
            self._clear_target_claim()  # type: ignore[attr-defined]
            self._clear_sticky_target()  # type: ignore[attr-defined]
            if not team_can_refill_hearts(state):
                return self._miner_action(state, summary_prefix="rebuild_hearts_")
            if hub is not None:
                return self._move_to_known(state, hub, summary="acquire_heart", vibe="change_vibe_heart")  # type: ignore[attr-defined]
            return self._explore_action(state, role="aligner", summary="find_hub_for_heart")  # type: ignore[attr-defined]
        if should_batch_hearts(state, role="aligner", hub_position=hub.position if hub else None):
            self._clear_target_claim()  # type: ignore[attr-defined]
            self._clear_sticky_target()  # type: ignore[attr-defined]
            assert hub is not None
            return self._move_to_known(state, hub, summary="batch_hearts", vibe="change_vibe_heart")  # type: ignore[attr-defined]

        target = self._preferred_alignable_neutral_junction(state)  # type: ignore[attr-defined]
        if target is not None:
            self._claim_target(target.position)  # type: ignore[attr-defined]
            self._set_sticky_target(target.position, target.entity_type)  # type: ignore[attr-defined]
            return self._move_to_known(state, target, summary="align_junction", vibe="change_vibe_aligner")  # type: ignore[attr-defined]

        self._clear_target_claim()  # type: ignore[attr-defined]
        self._clear_sticky_target()  # type: ignore[attr-defined]
        if resource_total(state) > 0:
            depot = self._nearest_friendly_depot(state)  # type: ignore[attr-defined]
            if depot is not None:
                return self._move_to_known(state, depot, summary="deposit_cargo", vibe="change_vibe_aligner")  # type: ignore[attr-defined]

        return self._explore_action(state, role="aligner", summary="find_neutral_junction")  # type: ignore[attr-defined]

    def _scrambler_action(self, state: MettagridState) -> tuple[Action, str]:
        hearts = int(state.self_state.inventory.get("heart", 0))
        hub = self._nearest_hub(state)  # type: ignore[attr-defined]
        if hearts <= 0:
            self._clear_sticky_target()  # type: ignore[attr-defined]
            if not team_can_refill_hearts(state):
                return self._miner_action(state, summary_prefix="rebuild_hearts_")
            if hub is not None:
                return self._move_to_known(state, hub, summary="acquire_heart", vibe="change_vibe_heart")  # type: ignore[attr-defined]
            return self._explore_action(state, role="scrambler", summary="find_hub_for_heart")  # type: ignore[attr-defined]
        if should_batch_hearts(state, role="scrambler", hub_position=hub.position if hub else None):
            self._clear_sticky_target()  # type: ignore[attr-defined]
            assert hub is not None
            return self._move_to_known(state, hub, summary="batch_hearts", vibe="change_vibe_heart")  # type: ignore[attr-defined]

        target = self._preferred_scramble_target(state)  # type: ignore[attr-defined]
        if target is not None:
            self._set_sticky_target(target.position, target.entity_type)  # type: ignore[attr-defined]
            return self._move_to_known(state, target, summary="scramble_junction", vibe="change_vibe_scrambler")  # type: ignore[attr-defined]

        self._clear_sticky_target()  # type: ignore[attr-defined]
        return self._explore_action(state, role="scrambler", summary="find_enemy_junction")  # type: ignore[attr-defined]
