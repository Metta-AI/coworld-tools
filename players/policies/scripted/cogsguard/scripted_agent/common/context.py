"""Shared context and observation snapshot types for Python scripted agents."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional, Protocol

from policies.scripted.cogsguard.scripted_agent.common.trace import TraceLog
from mettagrid.simulator import Action


@dataclass
class StateSnapshot:
    """Rebuilt every tick from observation tokens. Observation is source of truth."""

    position: tuple[int, int] = (0, 0)

    # Inventory
    carbon: int = 0
    oxygen: int = 0
    germanium: int = 0
    silicon: int = 0
    heart: int = 0
    influence: int = 0
    hp: int = 100
    energy: int = 100

    # Gear flags
    miner_gear: bool = False
    scout_gear: bool = False
    aligner_gear: bool = False
    scrambler_gear: bool = False

    # Vibe
    vibe: str = "default"

    # Team (hub) inventory
    team_carbon: int = 0
    team_oxygen: int = 0
    team_germanium: int = 0
    team_silicon: int = 0
    team_heart: int = 0
    team_influence: int = 0

    @property
    def cargo_total(self) -> int:
        return self.carbon + self.oxygen + self.germanium + self.silicon

    @property
    def cargo_capacity(self) -> int:
        return 40 if self.miner_gear else 4


class ScriptedAgentEntityMap(Protocol):
    entities: dict[tuple[int, int], Any]
    explored: set[tuple[int, int]]
    claims: dict[tuple[int, int], tuple[int, int]]

    def find(
        self,
        type: Optional[str] = None,
        type_contains: Optional[str] = None,
        property_filter: Optional[dict[str, Any]] = None,
    ) -> list[tuple[tuple[int, int], Any]]: ...

    def find_nearest(
        self,
        from_pos: tuple[int, int],
        type: Optional[str] = None,
        type_contains: Optional[str] = None,
        property_filter: Optional[dict[str, Any]] = None,
        max_dist: Optional[int] = None,
    ) -> Optional[tuple[tuple[int, int], Any]]: ...

    def is_passable(self, pos: tuple[int, int]) -> bool: ...

    def is_wall(self, pos: tuple[int, int]) -> bool: ...

    def is_structure(self, pos: tuple[int, int]) -> bool: ...

    def is_free(self, pos: tuple[int, int]) -> bool: ...

    def has_agent(self, pos: tuple[int, int]) -> bool: ...


class ScriptedAgentNavigator(Protocol):
    _cached_path: Any
    _cached_target: Any

    def explore(
        self,
        agent_pos: tuple[int, int],
        entity_map: ScriptedAgentEntityMap,
        *,
        direction_bias: str | None = None,
    ) -> Action: ...

    def get_action(
        self,
        agent_pos: tuple[int, int],
        target_pos: tuple[int, int],
        entity_map: ScriptedAgentEntityMap,
        *,
        reach_adjacent: bool = False,
    ) -> Action: ...


@dataclass
class ScriptedAgentContext:
    """Shared decision-making context passed to scripted goals."""

    state: StateSnapshot
    map: ScriptedAgentEntityMap
    blackboard: dict[str, Any]
    navigator: ScriptedAgentNavigator
    trace: Optional[TraceLog]
    action_names: list[str]
    agent_id: int
    step: int
