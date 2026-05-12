"""Pressure budgets, retreat logic, and role selection mixin."""

from __future__ import annotations

from typing import TYPE_CHECKING

from cogamer.cvc.agent import (
    _JUNCTION_AOE_RANGE,
    KnownEntity,
    absolute_position,
    deposit_threshold,
    has_role_gear,
    heart_supply_capacity,
    manhattan,
    resource_total,
    retreat_threshold,
    team_can_afford_gear,
    team_can_refill_hearts,
    team_id,
    team_min_resource,
)
from cogamer.cvc.agent.budgets import (
    PressureMetrics,
    assign_role,
    compute_pressure_budgets,
    compute_pressure_metrics,
    compute_retreat_margin,
)
from mettagrid.sdk.agent import MettagridState

if TYPE_CHECKING:
    from cogamer.cvc.agent.world_model import WorldModel


class PressureMixin:
    _world_model: WorldModel
    _agent_id: int
    _role_id: int
    _step_index: int

    def _desired_role(self, state: MettagridState, *, objective: str | None = None) -> str:
        aligner_budget, scrambler_budget = self._pressure_budgets(state, objective=objective)
        return assign_role(self._role_id, aligner_budget, scrambler_budget)

    def _macro_snapshot(self, state: MettagridState, role: str) -> dict[str, int | str | bool]:
        safe_target = self._nearest_friendly_depot(state)  # type: ignore[attr-defined]
        safe_distance = 0 if safe_target is None else manhattan(absolute_position(state), safe_target.position)
        hp = int(state.self_state.inventory.get("hp", 0))
        team = team_id(state)
        in_enemy_aoe = self._in_enemy_aoe(state, absolute_position(state), team_id=team)
        low_hp_risk = self._should_retreat(state, role, safe_target)
        payload_at_risk = low_hp_risk and (
            int(state.self_state.inventory.get("heart", 0)) > 0 or resource_total(state) > 0
        )
        pressure_metrics = self._pressure_metrics(state)
        aligner_budget, scrambler_budget = self._pressure_budgets(state)
        heart_supply = heart_supply_capacity(state)

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
            "team_can_afford_role_gear": team_can_afford_gear(state, role),
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
        team = team_id(state)
        hub = self._nearest_hub(state)  # type: ignore[attr-defined]
        friendly_sources: list[KnownEntity] = []
        if hub is not None:
            friendly_sources.append(hub)
        friendly_sources.extend(self._known_junctions(state, predicate=lambda entity: entity.owner == team))  # type: ignore[attr-defined]
        neutral_junctions = self._known_junctions(state, predicate=lambda entity: entity.owner in {None, "neutral"})  # type: ignore[attr-defined]
        enemy_junctions = self._known_junctions(  # type: ignore[attr-defined]
            state,
            predicate=lambda entity: entity.owner not in {None, "neutral", team},
        )
        return compute_pressure_metrics(
            friendly_sources=friendly_sources,
            neutral_junctions=neutral_junctions,
            enemy_junctions=enemy_junctions,
        )

    def _pressure_budgets(self, state: MettagridState, *, objective: str | None = None) -> tuple[int, int]:
        return compute_pressure_budgets(
            step=state.step or self._step_index,
            min_resource=team_min_resource(state),
            can_refill_hearts=team_can_refill_hearts(state),
            objective=objective,
        )

    def _in_enemy_aoe(self, state: MettagridState, position: tuple[int, int], *, team_id: str) -> bool:
        enemies = self._known_junctions(  # type: ignore[attr-defined]
            state,
            predicate=lambda entity: entity.owner not in {None, "neutral", team_id},
        )
        for enemy in enemies:
            if manhattan(position, enemy.position) <= _JUNCTION_AOE_RANGE:
                return True
        return False

    def _near_enemy_territory(self, state: MettagridState, position: tuple[int, int], *, team_id: str) -> bool:
        """Wider enemy detection (radius 20) for retreat decisions, matching alpha.0."""
        enemies = self._known_junctions(  # type: ignore[attr-defined]
            state,
            predicate=lambda entity: entity.owner not in {None, "neutral", team_id},
        )
        for enemy in enemies:
            if manhattan(position, enemy.position) <= 20:
                return True
        return False

    def _should_retreat(self, state: MettagridState, role: str, safe_target: KnownEntity | None) -> bool:
        hp = int(state.self_state.inventory.get("hp", 0))
        if safe_target is None:
            return hp <= retreat_threshold(state, role)

        safe_steps = max(0, manhattan(absolute_position(state), safe_target.position) - _JUNCTION_AOE_RANGE)
        current_pos = absolute_position(state)
        team = team_id(state)
        return compute_retreat_margin(
            hp=hp,
            safe_steps=safe_steps,
            in_enemy_aoe=self._in_enemy_aoe(state, current_pos, team_id=team),
            near_enemy_territory=self._near_enemy_territory(state, current_pos, team_id=team),
            heart_count=int(state.self_state.inventory.get("heart", 0)),
            resource_cargo=resource_total(state),
            has_gear=has_role_gear(state, role),
            late_game=(state.step or 0) >= 2_500,
            role=role,
        )

    def _should_deposit_resources(self, state: MettagridState) -> bool:
        cargo = resource_total(state)
        if cargo <= 0:
            return False
        if cargo >= deposit_threshold(state):
            return True

        safe_target = self._nearest_friendly_depot(state)  # type: ignore[attr-defined]
        if safe_target is None:
            return cargo >= 4

        safe_distance = manhattan(absolute_position(state), safe_target.position)
        if cargo >= 16 and safe_distance > 18:
            return True
        if cargo >= 8 and self._should_retreat(state, "miner", safe_target):
            return True
        if cargo >= 12 and self._in_enemy_aoe(state, absolute_position(state), team_id=team_id(state)):
            return True
        return False
