"""Shared sparse entity-map implementation for Python scripted agents."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from agent_policies.policies.scripted.cogsguard.scripted_agent.common.geometry import is_within_observation_shape


@dataclass
class Entity:
    """An object on the map."""

    type: str  # e.g. "carbon_extractor", "miner", "wall", "agent"
    properties: dict  # alignment, inventory_amount, cooldown, etc.
    last_seen: int = 0


class ScriptedAgentEntityMap:
    """Sparse map of entities. Only stores non-empty cells."""

    def __init__(self, *, agent_last_seen_ttl: int | None = None) -> None:
        self.entities: dict[tuple[int, int], Entity] = {}
        self.explored: set[tuple[int, int]] = set()
        self.claims: dict[tuple[int, int], tuple[int, int]] = {}
        self._agent_last_seen_ttl = agent_last_seen_ttl
        self._step = 0

    def update_from_observation(
        self,
        agent_pos: tuple[int, int],
        obs_half_height: int,
        obs_half_width: int,
        visible_entities: dict[tuple[int, int], Entity],
        step: int,
    ) -> None:
        """Update map from current observation window.

        All observable cells in the current observation mask are marked as explored.
        Entities in the window are overwritten with fresh data.
        Entities no longer visible in the window are removed.
        """
        self._step = step
        observed_positions: set[tuple[int, int]] = set()
        for dr in range(-obs_half_height, obs_half_height + 1):
            for dc in range(-obs_half_width, obs_half_width + 1):
                if not is_within_observation_shape(
                    row_offset=dr,
                    col_offset=dc,
                    row_radius=obs_half_height,
                    col_radius=obs_half_width,
                ):
                    continue
                pos = (agent_pos[0] + dr, agent_pos[1] + dc)
                self.explored.add(pos)
                observed_positions.add(pos)

        to_remove = []
        for pos in self.entities:
            if pos in observed_positions and pos not in visible_entities:
                to_remove.append(pos)
        for pos in to_remove:
            del self.entities[pos]

        for pos, entity in visible_entities.items():
            entity.last_seen = step
            self.entities[pos] = entity

    def find(
        self,
        type: Optional[str] = None,
        type_contains: Optional[str] = None,
        property_filter: Optional[dict] = None,
    ) -> list[tuple[tuple[int, int], Entity]]:
        """Query entities by type and/or properties.

        Args:
            type: Exact type match.
            type_contains: Substring match on type.
            property_filter: Dict of property key-value pairs that must match.
        """
        results = []
        for pos, entity in self.entities.items():
            if type is not None and entity.type != type:
                continue
            if type_contains is not None and type_contains not in entity.type:
                continue
            if property_filter is not None and not all(
                entity.properties.get(k) == v for k, v in property_filter.items()
            ):
                continue
            results.append((pos, entity))
        return results

    def find_nearest(
        self,
        from_pos: tuple[int, int],
        type: Optional[str] = None,
        type_contains: Optional[str] = None,
        property_filter: Optional[dict] = None,
        max_dist: Optional[int] = None,
    ) -> Optional[tuple[tuple[int, int], Entity]]:
        """Find the nearest entity matching the criteria."""
        matches = self.find(type=type, type_contains=type_contains, property_filter=property_filter)
        if not matches:
            return None

        best = None
        best_dist = float("inf")
        for pos, entity in matches:
            dist = abs(pos[0] - from_pos[0]) + abs(pos[1] - from_pos[1])
            if max_dist is not None and dist > max_dist:
                continue
            if dist < best_dist:
                best = (pos, entity)
                best_dist = dist
        return best

    def is_passable(self, pos: tuple[int, int]) -> bool:
        """Check if a position is passable (explored and not a wall/obstacle)."""
        if pos not in self.explored:
            return False
        entity = self.entities.get(pos)
        if entity is None:
            return True  # Explored empty cell
        # Agents are temporary obstacles, everything else is permanent
        if entity.type == "agent":
            return False
        # Walls are obstacles
        if entity.type == "wall":
            return False
        # Structures are passable for pathfinding; goals that need adjacency
        # handle that via reach_adjacent=True.
        return True

    def is_wall(self, pos: tuple[int, int]) -> bool:
        """Check if a position contains a wall."""
        entity = self.entities.get(pos)
        return entity is not None and entity.type == "wall"

    def is_structure(self, pos: tuple[int, int]) -> bool:
        """Check if a position has a structure (non-wall, non-agent entity)."""
        entity = self.entities.get(pos)
        return entity is not None and entity.type not in ("wall", "agent")

    def is_free(self, pos: tuple[int, int]) -> bool:
        """Check if a position is explored and currently empty."""
        return pos in self.explored and pos not in self.entities

    def has_agent(self, pos: tuple[int, int]) -> bool:
        """Check if a position contains a currently relevant agent."""
        entity = self.entities.get(pos)
        if entity is None or entity.type != "agent":
            return False
        if self._agent_last_seen_ttl is None:
            return True
        return self._step - entity.last_seen <= self._agent_last_seen_ttl
