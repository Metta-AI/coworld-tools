"""Pure functions for pressure budgets, role assignment, and retreat logic."""

from __future__ import annotations

from dataclasses import dataclass

from cogamer.cvc.agent.geometry import manhattan
from cogamer.cvc.agent.scoring import within_alignment_network
from cogamer.cvc.agent.types import (
    _JUNCTION_ALIGN_DISTANCE,
    _JUNCTION_AOE_RANGE,
    KnownEntity,
)

_RETREAT_MARGIN = 15
_ECONOMY_BOOTSTRAP_ALIGNER_BUDGET = 2
_ALIGNER_PRIORITY = (4, 5, 6, 7, 3, 2, 1, 0)
_SCRAMBLER_PRIORITY = (7, 6, 3, 2, 1, 0)


@dataclass(slots=True)
class PressureMetrics:
    frontier_neutral_junctions: int
    best_frontier_coverage: int
    best_enemy_scramble_block: int


def assign_role(
    role_id: int,
    aligner_budget: int,
    scrambler_budget: int,
) -> str:
    scrambler_ids = set(_SCRAMBLER_PRIORITY[:scrambler_budget])
    aligner_ids: list[int] = []
    for agent_id in _ALIGNER_PRIORITY:
        if agent_id in scrambler_ids:
            continue
        if len(aligner_ids) == aligner_budget:
            break
        aligner_ids.append(agent_id)
    if role_id in scrambler_ids:
        return "scrambler"
    if role_id in aligner_ids:
        return "aligner"
    return "miner"


def compute_pressure_budgets(
    *,
    step: int,
    min_resource: int,
    can_refill_hearts: bool,
    objective: str | None = None,
) -> tuple[int, int]:
    if step < 30:
        pressure_budget = 2
    elif step < 3000:
        pressure_budget = 5
        if min_resource < 1 and not can_refill_hearts:
            pressure_budget = 2
        elif min_resource < 3:
            pressure_budget = 4
    else:
        pressure_budget = 6
        if min_resource < 1 and not can_refill_hearts:
            pressure_budget = 3

    scrambler_budget = 0
    if step >= 100:
        scrambler_budget = 1
    aligner_budget = max(pressure_budget - scrambler_budget, 0)
    if objective == "resource_coverage":
        return 0, 0
    if objective == "economy_bootstrap":
        return min(aligner_budget, _ECONOMY_BOOTSTRAP_ALIGNER_BUDGET), 0
    return aligner_budget, scrambler_budget


def compute_retreat_margin(
    *,
    hp: int,
    safe_steps: int,
    in_enemy_aoe: bool,
    near_enemy_territory: bool,
    heart_count: int,
    resource_cargo: int,
    has_gear: bool,
    late_game: bool,
    role: str,
) -> bool:
    margin = _RETREAT_MARGIN
    if in_enemy_aoe:
        margin += 10
    elif near_enemy_territory:
        margin += 5
    margin += heart_count * 5
    margin += min(resource_cargo, 12) // 2
    if not has_gear:
        margin += 10
    if late_game:
        margin += 10 if role in {"aligner", "scrambler"} else 5
    return hp <= safe_steps + margin


def compute_pressure_metrics(
    *,
    friendly_sources: list[KnownEntity],
    neutral_junctions: list[KnownEntity],
    enemy_junctions: list[KnownEntity],
) -> PressureMetrics:
    frontier_junctions = [
        entity for entity in neutral_junctions if within_alignment_network(entity.position, friendly_sources)
    ]
    unreachable_junctions = [entity for entity in neutral_junctions if entity not in frontier_junctions]
    best_frontier_coverage = max(
        (
            sum(
                1
                for neutral in unreachable_junctions
                if manhattan(candidate.position, neutral.position) <= _JUNCTION_ALIGN_DISTANCE
            )
            for candidate in frontier_junctions
        ),
        default=0,
    )
    best_enemy_scramble_block = max(
        (
            sum(
                1 for neutral in neutral_junctions if manhattan(enemy.position, neutral.position) <= _JUNCTION_AOE_RANGE
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
