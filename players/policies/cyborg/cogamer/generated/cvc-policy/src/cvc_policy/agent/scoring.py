"""Target scoring and alignment network helpers."""

from __future__ import annotations

from cvc_policy.agent.geometry import manhattan
from cvc_policy.agent.types import (
    HUB_ALIGN_DISTANCE,
    JUNCTION_ALIGN_DISTANCE,
    JUNCTION_AOE_RANGE,
    _STATION_TARGETS_BY_AGENT,
    KnownEntity,
)


def within_alignment_network(
    candidate: tuple[int, int],
    sources: list[KnownEntity],
) -> bool:
    for source in sources:
        max_distance = HUB_ALIGN_DISTANCE if source.entity_type == "hub" else JUNCTION_ALIGN_DISTANCE
        if manhattan(candidate, source.position) <= max_distance:
            return True
    return False


def teammate_closer_to_target(
    *,
    current_position: tuple[int, int],
    target: tuple[int, int],
    teammate_positions: list[tuple[int, int]],
) -> bool:
    """Check if any teammate aligner is closer to the target than we are."""
    my_dist = manhattan(current_position, target)
    for pos in teammate_positions:
        if manhattan(pos, target) < my_dist:
            return True
    return False


def aligner_target_score(
    *,
    current_position: tuple[int, int],
    candidate: KnownEntity,
    unreachable: list[KnownEntity],
    enemy_junctions: list[KnownEntity],
    hub_position: tuple[int, int] | None = None,
    friendly_sources: list[KnownEntity] | None = None,
    hotspot_count: int = 0,
    teammate_closer: bool = False,
) -> tuple[float, float]:
    distance = float(manhattan(current_position, candidate.position))
    expansion = sum(
        1 for entity in unreachable if manhattan(candidate.position, entity.position) <= JUNCTION_ALIGN_DISTANCE
    )
    enemy_aoe = (
        1.0
        if any(manhattan(candidate.position, enemy.position) <= JUNCTION_AOE_RANGE for enemy in enemy_junctions)
        else 0.0
    )
    # Strongly prefer hub-proximal junctions: less travel, safer, faster cycling
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
    # Reduce hotspot penalty for hub-proximal junctions (worth defending)
    hotspot_weight = 8.0
    if hub_position is not None:
        hub_dist = float(manhattan(hub_position, candidate.position))
        if hub_dist <= 10:
            hotspot_weight = 2.0  # near hub: still recapture despite contest
        elif hub_dist <= 15:
            hotspot_weight = 5.0
    hotspot_penalty = min(hotspot_count, 3) * hotspot_weight
    # Small bonus for junctions near existing friendly network (chain-building)
    # Matching alpha.0's _DEFAULT_NETWORK_WEIGHT = 0.5
    network_bonus = 0.0
    if friendly_sources:
        nearby_friendly = sum(
            1
            for source in friendly_sources
            if source.entity_type != "hub"
            and manhattan(candidate.position, source.position) <= JUNCTION_ALIGN_DISTANCE
        )
        network_bonus = min(nearby_friendly, 4) * 0.5
    teammate_penalty = 6.0 if teammate_closer else 0.0
    return (
        distance
        - min(expansion * 5.0, 30.0)
        + enemy_aoe * 8.0
        + hub_penalty
        + hotspot_penalty
        - network_bonus
        + teammate_penalty,
        -float(expansion),
    )


def is_usable_extractor(entity: KnownEntity) -> bool:
    """Check if a remembered extractor still has resources.

    Resource extractors expose remaining inventory under the resource name
    (e.g., carbon_extractor -> attributes["carbon"]). When the extractor is
    drained the key is *removed* from attributes entirely (not set to 0);
    so "missing" must be treated as empty, not unknown.
    """
    resource = entity.entity_type.removesuffix("_extractor")
    if resource == entity.entity_type:
        return True  # non-resource extractor kind, e.g., generic
    return int(entity.attributes.get(resource, 0)) > 0


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
        1 for neutral in neutral_junctions if manhattan(candidate.position, neutral.position) <= JUNCTION_AOE_RANGE
    )
    corner_pressure = min(manhattan(hub_position, candidate.position) / 8.0, 10.0)
    # Strongly prioritize enemy junctions near our friendly network (defending our score)
    threat_bonus = 0.0
    if friendly_junctions:
        threatened = sum(
            1 for f in friendly_junctions if manhattan(candidate.position, f.position) <= JUNCTION_ALIGN_DISTANCE
        )
        threat_bonus = threatened * 10.0
    return (
        distance - blocked_neutrals * 6.0 - corner_pressure - threat_bonus,
        -float(blocked_neutrals),
    )


def spawn_relative_station_target(agent_id: int, role: str) -> tuple[int, int] | None:
    station_targets = _STATION_TARGETS_BY_AGENT.get(role)
    if station_targets is None:
        return None
    return station_targets.get(agent_id)
