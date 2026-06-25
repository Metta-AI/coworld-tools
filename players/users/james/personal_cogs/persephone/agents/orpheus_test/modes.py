"""Minimal modes used to exercise the Orpheus framework end to end."""

from __future__ import annotations

import math

from agents.orpheus_test.meta_decide import ApproachParams, WanderParams
from orpheus.belief_state import PlayerInfo
from orpheus.idle import IdleMode, IdleTask
from orpheus.mode import Mode, ModeDirective
from orpheus.task import Task
from orpheus.tasks import FollowTask, WanderTask


class WanderMode(Mode):
    """Select a framework WanderTask every tick."""

    params_type = WanderParams

    def select_task(self, belief_state, action_memory) -> Task | None:
        """Return the built-in wandering movement task."""
        del belief_state, action_memory
        return WanderTask()

    def mode_enter(self, belief_state, action_memory) -> None:
        """No one-time setup is needed."""
        pass

    def mode_switch_cleanup(
        self,
        belief_state,
        action_memory,
        new_mode_directive: ModeDirective,
    ) -> None:
        """No cleanup is needed when leaving wander mode."""
        pass


class ApproachNearestPlayerMode(Mode):
    """Follow the nearest known player position, falling back to idle."""

    params_type = ApproachParams

    def select_task(self, belief_state, action_memory) -> Task | None:
        """Return a FollowTask for the nearest known player."""
        del action_memory

        self_position = _position2d(getattr(belief_state, "position", None))
        if self_position is None:
            return IdleTask()

        nearest = _nearest_known_player(
            self_position,
            getattr(belief_state, "players", {}),
        )
        if nearest is None:
            return IdleTask()

        return FollowTask(nearest, stop_distance=10)

    def mode_enter(self, belief_state, action_memory) -> None:
        """No one-time setup is needed."""
        pass

    def mode_switch_cleanup(
        self,
        belief_state,
        action_memory,
        new_mode_directive: ModeDirective,
    ) -> None:
        """No cleanup is needed when leaving approach mode."""
        pass


def _nearest_known_player(
    self_position: tuple[int, int],
    players: dict[int, PlayerInfo],
) -> int | None:
    nearest_index: int | None = None
    nearest_distance = math.inf

    for index, player in players.items():
        player_position = _position2d(player.position)
        if player_position is None:
            continue

        distance = math.hypot(
            player_position[0] - self_position[0],
            player_position[1] - self_position[1],
        )
        if distance < nearest_distance:
            nearest_distance = distance
            nearest_index = index

    return nearest_index


def _position2d(value) -> tuple[int, int] | None:
    if value is None or len(value) < 2:
        return None
    return int(value[0]), int(value[1])


__all__ = ["IdleMode", "WanderMode", "ApproachNearestPlayerMode"]

