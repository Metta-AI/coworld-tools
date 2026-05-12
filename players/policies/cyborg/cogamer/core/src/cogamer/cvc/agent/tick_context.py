"""Per-tick read-only game context, built once and passed to decision checks."""

from __future__ import annotations

from dataclasses import dataclass

from cogamer.cvc.agent.geometry import manhattan
from cogamer.cvc.agent.resources import absolute_position, resource_total, team_id
from cogamer.cvc.agent.types import _JUNCTION_AOE_RANGE, KnownEntity
from mettagrid.sdk.agent import MettagridState

_NEAR_ENEMY_RADIUS = 20


@dataclass(frozen=True, slots=True)
class TickContext:
    """Computed once per tick, read by all decision checks."""

    state: MettagridState
    position: tuple[int, int]
    hp: int
    step: int
    team: str
    resource_bias: str
    hearts: int
    cargo: int

    hub: KnownEntity | None
    hub_distance: int

    in_enemy_aoe: bool
    near_enemy_territory: bool

    friendly_junctions: list[KnownEntity]
    enemy_junctions: list[KnownEntity]
    neutral_junctions: list[KnownEntity]
    network_sources: list[KnownEntity]

    stalled_steps: int
    oscillation_steps: int

    teammate_aligner_positions: list[tuple[int, int]]


def teammate_aligner_positions(state: MettagridState) -> list[tuple[int, int]]:
    """Extract teammate aligner positions from team_summary."""
    if state.team_summary is None:
        return []
    my_entity_id = str(state.self_state.attributes.get("entity_id", ""))
    positions = []
    for member in state.team_summary.members:
        if member.entity_id == my_entity_id:
            continue
        if member.role == "aligner":
            positions.append((member.position.x, member.position.y))
    return positions


def build_tick_context(
    state: MettagridState,
    *,
    world_model: object,
    nearest_hub_fn: object,
    known_junctions_fn: object,
    stalled_steps: int,
    oscillation_steps: int,
    resource_bias: str,
    step_index: int,
) -> TickContext:
    """Build TickContext from state and engine components.

    Takes callable accessors instead of the engine directly to avoid
    circular imports.
    """
    position = absolute_position(state)
    team = team_id(state)
    hub = nearest_hub_fn(state)  # type: ignore[operator]
    hub_distance = 0 if hub is None else manhattan(position, hub.position)

    friendly_junctions = known_junctions_fn(state, predicate=lambda e: e.owner == team)  # type: ignore[operator]
    enemy_junctions = known_junctions_fn(  # type: ignore[operator]
        state, predicate=lambda e: e.owner not in {None, "neutral", team}
    )
    neutral_junctions = known_junctions_fn(  # type: ignore[operator]
        state, predicate=lambda e: e.owner in {None, "neutral"}
    )
    hubs = world_model.entities(entity_type="hub", predicate=lambda e: e.team == team)  # type: ignore[attr-defined]
    network_sources = [*hubs, *friendly_junctions]

    return TickContext(
        state=state,
        position=position,
        hp=int(state.self_state.inventory.get("hp", 0)),
        step=state.step or step_index,
        team=team,
        resource_bias=resource_bias,
        hearts=int(state.self_state.inventory.get("heart", 0)),
        cargo=resource_total(state),
        hub=hub,
        hub_distance=hub_distance,
        in_enemy_aoe=any(manhattan(position, j.position) <= _JUNCTION_AOE_RANGE for j in enemy_junctions),
        near_enemy_territory=any(manhattan(position, j.position) <= _NEAR_ENEMY_RADIUS for j in enemy_junctions),
        friendly_junctions=friendly_junctions,
        enemy_junctions=enemy_junctions,
        neutral_junctions=neutral_junctions,
        network_sources=network_sources,
        stalled_steps=stalled_steps,
        oscillation_steps=oscillation_steps,
        teammate_aligner_positions=teammate_aligner_positions(state),
    )
