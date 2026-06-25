"""Rule-based outer-loop decisions for the Orpheus test agent."""

from __future__ import annotations

from dataclasses import dataclass

from orpheus.mode import ModeDirective, ModeParams
from orpheus.types import View


@dataclass(frozen=True)
class ApproachParams(ModeParams):
    """No-argument params for approach-nearest-player mode."""

    pass


@dataclass(frozen=True)
class WanderParams(ModeParams):
    """No-argument params for wander mode."""

    pass


def meta_decide(belief_state, action_memory):
    """Pick a simple gameplay mode from the latest belief snapshot."""
    del action_memory

    view = belief_state.view
    if view in {View.PLAYING, View.HOSTAGE_SELECT, View.LEADER_SUMMIT}:
        known_players = [
            i
            for i, player in belief_state.players.items()
            if player.position is not None
        ]
        if known_players:
            return ModeDirective("approach_nearest", ApproachParams()), None
        return ModeDirective("wander", WanderParams()), None
    return ModeDirective("idle", ModeParams()), None


__all__ = ["ApproachParams", "WanderParams", "meta_decide"]

