"""Target selection mixin."""

from __future__ import annotations

from typing import TYPE_CHECKING

from cvc_policy.agent import (
    KnownEntity,
    absolute_position,
    aligner_target_score,
    is_usable_extractor,
    manhattan,
    resource_priority,
    scramble_target_score,
    team_id,
    teammate_closer_to_target,
    within_alignment_network,
)
from mettagrid.sdk.agent import MacroDirective, MettagridState

if TYPE_CHECKING:
    from cvc_policy.agent.world_model import WorldModel

_TARGET_SWITCH_THRESHOLD = 3.0


class TargetingMixin:
    _world_model: WorldModel
    _hotspots: dict[tuple[int, int], int]
    _agent_id: int
    _step_index: int
    _sticky_target_position: tuple[int, int] | None
    _sticky_target_kind: str | None
    _current_directive: MacroDirective
    _resource_bias: str
    _stalled_steps: int

    def _set_sticky_target(self, position: tuple[int, int], entity_type: str) -> None:
        self._sticky_target_position = position
        self._sticky_target_kind = entity_type

    def _clear_sticky_target(self) -> None:
        self._sticky_target_position = None
        self._sticky_target_kind = None

    # ── Directive targeting ─────────────────────────────────────────

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

    # ── Junction targeting ──────────────────────────────────────────

    def _teammate_aligner_positions(self, state: MettagridState) -> list[tuple[int, int]]:
        """Get positions of teammate aligners from team_summary."""
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

    def _nearest_alignable_neutral_junction(self, state: MettagridState) -> KnownEntity | None:
        team = team_id(state)
        current_pos = absolute_position(state)
        hub = self._nearest_hub(state)  # type: ignore[attr-defined]
        hub_pos = hub.position if hub is not None else None
        hubs = self._world_model.entities(entity_type="hub", predicate=lambda entity: entity.team == team)
        friendly_junctions = self._known_junctions(state, predicate=lambda entity: entity.owner == team)  # type: ignore[attr-defined]
        network_sources = [*hubs, *friendly_junctions]
        candidates = []
        for entity in self._known_junctions(state, predicate=lambda junction: junction.owner in {None, "neutral"}):  # type: ignore[attr-defined]
            if not within_alignment_network(entity.position, network_sources):
                continue
            candidates.append(entity)
        if not candidates:
            return None
        directed_candidate = self._directive_target_candidate(candidates)
        if directed_candidate is not None:
            return directed_candidate
        enemy_junctions = self._known_junctions(  # type: ignore[attr-defined]
            state,
            predicate=lambda junction: junction.owner not in {None, "neutral", team},
        )
        unreachable = [
            entity
            for entity in self._known_junctions(state, predicate=lambda junction: junction.owner in {None, "neutral"})  # type: ignore[attr-defined]
            if entity not in candidates
        ]
        teammate_positions = self._teammate_aligner_positions(state)
        return min(
            candidates,
            key=lambda entity: (
                aligner_target_score(
                    current_position=current_pos,
                    candidate=entity,
                    unreachable=unreachable,
                    enemy_junctions=enemy_junctions,
                    hub_position=hub_pos,
                    friendly_sources=network_sources,
                    hotspot_count=self._hotspots.get(entity.position, 0),
                    teammate_closer=teammate_closer_to_target(
                        current_position=current_pos,
                        target=entity.position,
                        teammate_positions=teammate_positions,
                    ),
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

        current_pos = absolute_position(state)
        team = team_id(state)
        neutral_junctions = self._world_model.entities(
            entity_type="junction",
            predicate=lambda junction: junction.owner in {None, "neutral"},
        )
        enemy_junctions = self._world_model.entities(
            entity_type="junction",
            predicate=lambda junction: junction.owner not in {None, "neutral", team},
        )
        hub = self._nearest_hub(state)  # type: ignore[attr-defined]
        hub_pos = hub.position if hub is not None else None
        hubs = self._world_model.entities(entity_type="hub", predicate=lambda entity: entity.team == team)
        friendly_junctions = self._known_junctions(state, predicate=lambda entity: entity.owner == team)  # type: ignore[attr-defined]
        network_sources = [*hubs, *friendly_junctions]
        sticky_score = aligner_target_score(
            current_position=current_pos,
            candidate=sticky,
            unreachable=[entity for entity in neutral_junctions if entity.position != sticky.position],
            enemy_junctions=enemy_junctions,
            hub_position=hub_pos,
            friendly_sources=network_sources,
            hotspot_count=self._hotspots.get(sticky.position, 0),
        )[0]
        candidate_score = aligner_target_score(
            current_position=current_pos,
            candidate=candidate,
            unreachable=[entity for entity in neutral_junctions if entity.position != candidate.position],
            enemy_junctions=enemy_junctions,
            hub_position=hub_pos,
            friendly_sources=network_sources,
            hotspot_count=self._hotspots.get(candidate.position, 0),
        )[0]
        if candidate.position != sticky.position and candidate_score + _TARGET_SWITCH_THRESHOLD < sticky_score:
            return candidate
        return sticky

    def _sticky_align_target(self, state: MettagridState) -> KnownEntity | None:
        if self._sticky_target_kind != "junction" or self._sticky_target_position is None:
            return None
        team = team_id(state)
        hubs = self._world_model.entities(entity_type="hub", predicate=lambda entity: entity.team == team)
        friendly_junctions = self._known_junctions(state, predicate=lambda entity: entity.owner == team)  # type: ignore[attr-defined]
        target = next(
            (
                entity
                for entity in self._known_junctions(state, predicate=lambda entity: entity.owner in {None, "neutral"})  # type: ignore[attr-defined]
                if entity.position == self._sticky_target_position
            ),
            None,
        )
        if target is None:
            self._clear_sticky_target()
            return None
        if not within_alignment_network(target.position, [*hubs, *friendly_junctions]):
            self._clear_sticky_target()
            return None
        return target

    # ── Extractor targeting ─────────────────────────────────────────

    def _preferred_miner_extractor(self, state: MettagridState) -> KnownEntity | None:
        if self._should_force_miner_explore_reset(state):
            self._clear_sticky_target()
            return None

        current_pos = absolute_position(state)
        current_step = state.step or self._step_index
        candidates: list[KnownEntity] = []
        for resource_name in resource_priority(state, resource_bias=self._resource_bias):
            matches = self._world_model.entities(
                entity_type=f"{resource_name}_extractor",
                predicate=lambda entity: is_usable_extractor(entity),
            )
            candidates.extend(
                sorted(
                    matches,
                    key=lambda entity: (
                        manhattan(current_pos, entity.position)
                        + max(0, current_step - entity.last_seen_step) * 0.05,
                        entity.position,
                    ),
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
        sticky_distance = manhattan(current_pos, sticky.position)
        candidate_distance = manhattan(current_pos, candidate.position)
        if candidate.position != sticky.position and candidate_distance + _TARGET_SWITCH_THRESHOLD < sticky_distance:
            return candidate
        return sticky

    def _should_force_miner_explore_reset(self, state: MettagridState) -> bool:
        if self._stalled_steps < 12:
            return False
        if any(entity.entity_type.endswith("_extractor") for entity in state.visible_entities):
            return False
        hub = self._nearest_hub(state)  # type: ignore[attr-defined]
        if hub is None:
            return False
        return manhattan(absolute_position(state), hub.position) <= 1

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
                    predicate=lambda entity: is_usable_extractor(entity),
                )
                if entity.position == self._sticky_target_position
            ),
            None,
        )
        if target is None:
            self._clear_sticky_target()
            return None
        return target

    # ── Scramble targeting ──────────────────────────────────────────

    def _best_scramble_target(self, state: MettagridState) -> KnownEntity | None:
        team = team_id(state)
        current_pos = absolute_position(state)
        hub = self._nearest_hub(state)  # type: ignore[attr-defined]
        neutral_junctions = self._known_junctions(state, predicate=lambda entity: entity.owner in {None, "neutral"})  # type: ignore[attr-defined]
        friendly_junctions = self._known_junctions(state, predicate=lambda entity: entity.owner == team)  # type: ignore[attr-defined]
        enemy_junctions = self._known_junctions(  # type: ignore[attr-defined]
            state,
            predicate=lambda entity: entity.owner not in {None, "neutral", team},
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
                scramble_target_score(
                    current_position=current_pos,
                    hub_position=hub_position,
                    candidate=entity,
                    neutral_junctions=neutral_junctions,
                    friendly_junctions=friendly_junctions,
                ),
                entity.position,
            ),
        )

    def _preferred_scramble_target(self, state: MettagridState) -> KnownEntity | None:
        candidate = self._best_scramble_target(state)
        sticky = self._sticky_scramble_target(state)
        if sticky is None:
            return candidate
        if candidate is None:
            return sticky

        team = team_id(state)
        current_pos = absolute_position(state)
        hub = self._nearest_hub(state)  # type: ignore[attr-defined]
        hub_position = current_pos if hub is None else hub.position
        neutral_junctions = self._world_model.entities(
            entity_type="junction",
            predicate=lambda entity: entity.owner in {None, "neutral"},
        )
        friendly_junctions = self._known_junctions(state, predicate=lambda entity: entity.owner == team)  # type: ignore[attr-defined]
        sticky_score = scramble_target_score(
            current_position=current_pos,
            hub_position=hub_position,
            candidate=sticky,
            neutral_junctions=neutral_junctions,
            friendly_junctions=friendly_junctions,
        )[0]
        candidate_score = scramble_target_score(
            current_position=current_pos,
            hub_position=hub_position,
            candidate=candidate,
            neutral_junctions=neutral_junctions,
            friendly_junctions=friendly_junctions,
        )[0]
        if candidate.position != sticky.position and candidate_score + _TARGET_SWITCH_THRESHOLD < sticky_score:
            return candidate
        return sticky

    def _sticky_scramble_target(self, state: MettagridState) -> KnownEntity | None:
        if self._sticky_target_kind != "junction" or self._sticky_target_position is None:
            return None
        team = team_id(state)
        target = next(
            (
                entity
                for entity in self._known_junctions(  # type: ignore[attr-defined]
                    state,
                    predicate=lambda entity: entity.owner not in {None, "neutral", team},
                )
                if entity.position == self._sticky_target_position
            ),
            None,
        )
        if target is None:
            self._clear_sticky_target()
            return None
        return target
