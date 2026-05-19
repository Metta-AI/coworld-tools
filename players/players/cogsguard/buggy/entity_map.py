"""Sparse entity map for Planky policy."""

from __future__ import annotations

from players.cogsguard._shared.common.entity_map import Entity, ScriptedAgentEntityMap


class EntityMap(ScriptedAgentEntityMap):
    """Sparse map of entities. Only stores non-empty cells."""

    def __init__(self) -> None:
        super().__init__(agent_last_seen_ttl=2)


__all__ = ["Entity", "EntityMap"]
