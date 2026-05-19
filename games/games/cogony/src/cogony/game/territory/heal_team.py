"""Heal-team variant: territory heals coherence for team members."""

from __future__ import annotations

from typing import TYPE_CHECKING, override

from cogames.core import CoGameMissionVariant, Deps
from cogony.game.territory.territory import TerritoryVariant
from mettagrid.config.filter import sharedTagPrefix
from mettagrid.config.handler_config import Handler, updateTarget
from mettagrid.config.mettagrid_config import MettaGridConfig

if TYPE_CHECKING:
    from cogony.mission import CogonyMission

COHERENCE_HEAL_RATE = 2


class HealTeamVariant(CoGameMissionVariant):
    """Territory heals team members' coherence each tick they remain inside."""

    name: str = "heal_team"
    description: str = "Territory heals coherence for team members."

    coherence_heal_rate: int = COHERENCE_HEAL_RATE

    @override
    def dependencies(self) -> Deps:
        return Deps(required=[TerritoryVariant])

    @override
    def modify_env(self, mission: CogonyMission, env: MettaGridConfig) -> None:
        territory = env.game.territories.get("team_territory")
        if territory is None:
            return

        if self.coherence_heal_rate and "coherence" in env.game.resource_names:
            territory.presence["heal_coherence"] = Handler(
                filters=[sharedTagPrefix("team:")],
                mutations=[updateTarget({"coherence": self.coherence_heal_rate})],
            )
