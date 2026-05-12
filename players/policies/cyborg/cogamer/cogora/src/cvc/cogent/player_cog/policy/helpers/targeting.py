"""Target scoring, claiming, and alignment network helpers."""

from __future__ import annotations

from cvc.cogent.player_cog.policy.helpers.geometry import manhattan
from cvc.cogent.player_cog.policy.helpers.types import (
    _CLAIMED_TARGET_PENALTY,
    _EXTRACTOR_MEMORY_STEPS,
    _HUB_ALIGN_DISTANCE,
    _JUNCTION_ALIGN_DISTANCE,
    _JUNCTION_AOE_RANGE,
    _STATION_TARGETS_BY_AGENT,
    _TARGET_CLAIM_STEPS,
    KnownEntity,
)


def within_alignment_network(
    candidate: tuple[int, int],
    sources: list[KnownEntity],
) -> bool:
    for source in sources:
        max_distance = _HUB_ALIGN_DISTANCE if source.entity_type == "hub" else _JUNCTION_ALIGN_DISTANCE
        if manhattan(candidate, source.position) <= max_distance:
            return True
    return False


def aligner_target_score(
    *,
    current_position: tuple[int, int],
    candidate: KnownEntity,
    unreachable: list[KnownEntity],
    enemy_junctions: list[KnownEntity],
    claimed_by_other: bool,
    hub_position: tuple[int, int] | None = None,
    friendly_junctions: list[KnownEntity] | None = None,
    hotspot_count: int = 0,
    network_weight: float = 0.5,
    hotspot_weight: float = 8.0,
    expansion_weight: float = 10.0,
    expansion_cap: float = 60.0,
) -> tuple[float, float]:
    distance = float(manhattan(current_position, candidate.position))
    expansion = sum(
        1 for entity in unreachable if manhattan(candidate.position, entity.position) <= _JUNCTION_ALIGN_DISTANCE
    )
    enemy_aoe = (
        1.0
        if any(manhattan(candidate.position, enemy.position) <= _JUNCTION_AOE_RANGE for enemy in enemy_junctions)
        else 0.0
    )
    network_penalty = 0.0
    if network_weight > 0:
        network_dist = 999.0
        if hub_position is not None:
            network_dist = min(network_dist, float(manhattan(hub_position, candidate.position)))
        if friendly_junctions:
            for fj in friendly_junctions:
                d = float(manhattan(fj.position, candidate.position))
                if d < network_dist:
                    network_dist = d
        network_penalty = network_dist * network_weight
    hotspot_penalty = min(hotspot_count, 3) * hotspot_weight
    return (
        distance
        - min(expansion * expansion_weight, expansion_cap)
        + enemy_aoe * 8.0
        + (_CLAIMED_TARGET_PENALTY if claimed_by_other else 0.0)
        + network_penalty
        + hotspot_penalty,
        -float(expansion),
    )


def is_claimed_by_other(
    *,
    claims: dict[tuple[int, int], tuple[int, int]],
    candidate: tuple[int, int],
    agent_id: int,
    step: int,
) -> bool:
    claim = claims.get(candidate)
    if claim is None:
        return False
    owner_id, owner_step = claim
    if owner_id == agent_id:
        return False
    return step - owner_step <= _TARGET_CLAIM_STEPS


def is_usable_recent_extractor(entity: KnownEntity, *, step: int) -> bool:
    return step - entity.last_seen_step <= _EXTRACTOR_MEMORY_STEPS


def scramble_target_score(
    *,
    current_position: tuple[int, int],
    hub_position: tuple[int, int],
    candidate: KnownEntity,
    neutral_junctions: list[KnownEntity],
    friendly_junctions: list[KnownEntity] | None = None,
) -> tuple[float, float]:
    distance = float(manhattan(current_position, candidate.position))
    blocked_neutrals = sum(
        1 for neutral in neutral_junctions if manhattan(candidate.position, neutral.position) <= _JUNCTION_AOE_RANGE
    )
    corner_pressure = min(manhattan(hub_position, candidate.position) / 8.0, 10.0)
    # Strongly prioritize enemy junctions near our friendly network (defending our score)
    threat_bonus = 0.0
    if friendly_junctions:
        threatened = sum(
            1 for f in friendly_junctions if manhattan(candidate.position, f.position) <= _JUNCTION_ALIGN_DISTANCE
        )
        threat_bonus = threatened * 10.0
    return (
        distance - blocked_neutrals * 4.0 - corner_pressure - threat_bonus,
        -float(blocked_neutrals),
    )


def v65_aligner_target_score(
    *,
    current_position: tuple[int, int],
    candidate: KnownEntity,
    unreachable: list[KnownEntity],
    enemy_junctions: list[KnownEntity],
    claimed_by_other: bool,
    hub_position: tuple[int, int] | None = None,
    hotspot_count: int = 0,
    hotspot_weight: float = 0.0,
) -> tuple[float, float]:
    """Original v65-era scoring: tiered hub_penalty, expansion 5.0/30.0.

    Optional hotspot_count/hotspot_weight: negative hotspot_count creates a
    re-alignment bonus for recently scrambled junctions.
    """
    distance = float(manhattan(current_position, candidate.position))
    expansion = sum(
        1 for entity in unreachable if manhattan(candidate.position, entity.position) <= _JUNCTION_ALIGN_DISTANCE
    )
    enemy_aoe = (
        1.0
        if any(manhattan(candidate.position, enemy.position) <= _JUNCTION_AOE_RANGE for enemy in enemy_junctions)
        else 0.0
    )
    hub_penalty = 0.0
    if hub_position is not None:
        hub_dist = float(manhattan(hub_position, candidate.position))
        if hub_dist > 25:
            hub_penalty = (hub_dist - 25) * 8.0 + 50.0
        elif hub_dist > 15:
            hub_penalty = (hub_dist - 15) * 3.0 + 10.0
        elif hub_dist > 10:
            hub_penalty = (hub_dist - 10) * 1.5 + 2.0
        else:
            hub_penalty = hub_dist * 0.3
    hotspot_penalty = min(hotspot_count, 3) * hotspot_weight
    return (
        distance
        - min(expansion * 5.0, 30.0)
        + enemy_aoe * 8.0
        + (_CLAIMED_TARGET_PENALTY if claimed_by_other else 0.0)
        + hub_penalty
        + hotspot_penalty,
        -float(expansion),
    )


def spawn_relative_station_target(agent_id: int, role: str) -> tuple[int, int] | None:
    station_targets = _STATION_TARGETS_BY_AGENT.get(role)
    if station_targets is None:
        return None
    return station_targets.get(agent_id)
