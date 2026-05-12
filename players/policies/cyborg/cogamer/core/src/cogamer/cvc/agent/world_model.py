"""Per-agent world model: tracks known entities from observations."""

from __future__ import annotations

from collections.abc import Callable

from cogamer.cvc.agent import KnownEntity, attr_int, attr_str, manhattan
from mettagrid.sdk.agent import MettagridState, SemanticEntity


class WorldModel:
    def __init__(self) -> None:
        self._entities: dict[str, KnownEntity] = {}

    def reset(self) -> None:
        self._entities.clear()

    def update(self, state: MettagridState) -> None:
        step = state.step or 0
        for entity in state.visible_entities:
            if entity.entity_type == "agent":
                continue
            global_x = attr_int(entity, "global_x", entity.position.x)
            global_y = attr_int(entity, "global_y", entity.position.y)
            key = f"{entity.entity_type}@{global_x},{global_y}"
            self._entities[key] = KnownEntity(
                entity_type=entity.entity_type,
                global_x=global_x,
                global_y=global_y,
                labels=tuple(entity.labels),
                team=attr_str(entity, "team"),
                owner=attr_str(entity, "owner"),
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
                attr_int(entity, "global_x", entity.position.x),
                attr_int(entity, "global_y", entity.position.y),
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
        return min(candidates, key=lambda entity: (manhattan(position, entity.position), entity.position))

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
        if nearest is None or manhattan(position, nearest.position) > max_distance:
            return False
        key = f"{nearest.entity_type}@{nearest.global_x},{nearest.global_y}"
        self._entities.pop(key, None)
        return True
