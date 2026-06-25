"""
Scout role for CoGsGuard.

Scouts explore the map and patrol to discover objects.
With scout gear, they get +400 HP and +100 energy capacity.

Scouts prioritize filling out their internal map by:
1. Moving towards unexplored frontiers (unexplored cells adjacent to explored cells)
2. Using systematic patrol when no clear frontier is available
"""

from __future__ import annotations

from players.cogsguard._shared.pathfinding import (
    is_traversable as path_is_traversable,
)
from players.cogsguard._shared.types import CellType
from mettagrid.simulator import Action

from .policy import CogsguardAgentPolicyImpl
from .types import CogsguardAgentState, Role, StructureType


class ScoutAgentPolicyImpl(CogsguardAgentPolicyImpl):
    """Scout agent: explore and patrol the map to fill out internal knowledge."""

    ROLE = Role.SCOUT

    def execute_role(self, s: CogsguardAgentState) -> Action:
        """Execute scout behavior: prioritize filling out unexplored areas."""
        if s.energy < s.MOVE_ENERGY_COST:
            if s.get_structure_position(StructureType.HUB) is None:
                return self._noop()
            return self._do_recharge(s)
        if s.last_action.name.startswith("move_") and s.last_action_executed == "noop":
            s.exploration_target = None
            s.cached_path = None
            s.cached_path_target = None
        # Try frontier-based exploration first
        frontier_action = self._explore_frontier(s)
        if frontier_action is not None:
            return frontier_action

        # Fall back to systematic patrol if no frontier found
        return self._patrol(s)

    def _patrol(self, s: CogsguardAgentState) -> Action:
        """Fall back patrol behavior when no frontier is available."""
        # Use longer exploration persistence for scouts
        if s.exploration_target is not None and isinstance(s.exploration_target, str):
            steps_in_direction = s.step_count - s.exploration_target_step
            # Scouts persist longer in each direction (25 steps vs 15)
            if steps_in_direction < 25:
                dr, dc = self._move_deltas.get(s.exploration_target, (0, 0))
                next_r, next_c = s.row + dr, s.col + dc
                if path_is_traversable(s, next_r, next_c, CellType):  # type: ignore[arg-type]
                    return self._move(s.exploration_target)

        # Cycle through directions systematically
        direction_cycle = ["north", "east", "south", "west"]
        current_dir = s.exploration_target
        if current_dir in direction_cycle:
            idx = direction_cycle.index(current_dir)
            next_idx = (idx + 1) % 4
        else:
            next_idx = 0

        for i in range(4):
            direction = direction_cycle[(next_idx + i) % 4]
            dr, dc = self._move_deltas[direction]
            next_r, next_c = s.row + dr, s.col + dc
            if path_is_traversable(s, next_r, next_c, CellType):  # type: ignore[arg-type]
                s.exploration_target = direction
                s.exploration_target_step = s.step_count
                return self._move(direction)

        return self._noop()
