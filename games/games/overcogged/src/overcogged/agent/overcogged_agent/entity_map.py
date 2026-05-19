"""Sparse entity map for the Overcogged scripted policy."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Entity:
    type: str
    properties: dict[str, int] = field(default_factory=dict)
    last_seen: int = 0


def _is_within_obs_shape(dr: int, dc: int, hr: int, hc: int) -> bool:
    """Elliptical observation mask matching mettagrid's C++ implementation."""
    if hr == 0 and hc == 0:
        return dr == 0 and dc == 0
    if hr == 0:
        return dr == 0 and abs(dc) <= hc
    if hc == 0:
        return dc == 0 and abs(dr) <= hr

    r2, c2 = dr * dr, dc * dc
    hr2, hc2 = hr * hr, hc * hc
    if hr == hc:
        d2 = r2 + c2
        if d2 <= hr2:
            return True
        return hr >= 2 and d2 == hr2 + 1 and (abs(dr) == hr or abs(dc) == hc)
    return r2 * hc2 + c2 * hr2 <= hr2 * hc2


class EntityMap:
    def __init__(self) -> None:
        self.entities: dict[tuple[int, int], Entity] = {}
        self.explored: set[tuple[int, int]] = set()
        self._step = 0

    def update_from_observation(
        self,
        agent_pos: tuple[int, int],
        obs_half_h: int,
        obs_half_w: int,
        visible: dict[tuple[int, int], Entity],
        step: int,
    ) -> None:
        self._step = step
        observed: set[tuple[int, int]] = set()
        for dr in range(-obs_half_h, obs_half_h + 1):
            for dc in range(-obs_half_w, obs_half_w + 1):
                if not _is_within_obs_shape(dr, dc, obs_half_h, obs_half_w):
                    continue
                pos = (agent_pos[0] + dr, agent_pos[1] + dc)
                self.explored.add(pos)
                observed.add(pos)

        for pos in list(self.entities):
            if pos in observed and pos not in visible:
                del self.entities[pos]

        for pos, entity in visible.items():
            entity.last_seen = step
            self.entities[pos] = entity

    def find(self, type_name: str) -> list[tuple[tuple[int, int], Entity]]:
        return [(pos, e) for pos, e in self.entities.items() if e.type == type_name]

    def find_nearest(
        self,
        from_pos: tuple[int, int],
        type_name: str,
        max_dist: int | None = None,
    ) -> tuple[tuple[int, int], Entity] | None:
        best: tuple[tuple[int, int], Entity] | None = None
        best_d = float("inf")
        for pos, entity in self.entities.items():
            if entity.type != type_name:
                continue
            dist = abs(pos[0] - from_pos[0]) + abs(pos[1] - from_pos[1])
            if max_dist is not None and dist > max_dist:
                continue
            if dist < best_d:
                best = (pos, entity)
                best_d = dist
        return best

    def is_wall(self, pos: tuple[int, int]) -> bool:
        entity = self.entities.get(pos)
        return entity is not None and entity.type == "wall"

    def is_structure(self, pos: tuple[int, int]) -> bool:
        entity = self.entities.get(pos)
        return entity is not None and entity.type not in ("wall", "agent")

    def is_free(self, pos: tuple[int, int]) -> bool:
        return pos in self.explored and pos not in self.entities

    def has_agent(self, pos: tuple[int, int]) -> bool:
        entity = self.entities.get(pos)
        return entity is not None and entity.type == "agent" and self._step - entity.last_seen <= 2
