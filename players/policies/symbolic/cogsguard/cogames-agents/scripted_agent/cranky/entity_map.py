"""Sparse entity map for Cogas policy."""

from __future__ import annotations

from cogames_agents.policy.scripted_agent.common.entity_map import Entity, ScriptedAgentEntityMap


class EntityMap(ScriptedAgentEntityMap):
    """Sparse map of entities. Only stores non-empty cells."""


__all__ = ["Entity", "EntityMap"]
