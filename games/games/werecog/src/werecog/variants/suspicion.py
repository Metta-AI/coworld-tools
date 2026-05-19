"""Suspicion/fear mechanics for Werewolf/Mafia."""

from __future__ import annotations

from cogames.core import CoGameMissionVariant, Deps
from werecog.variants.common import SUSPICION, append_unique
from werecog.variants.meetings import MeetingsVariant
from mettagrid.config.handler_config import updateTarget
from mettagrid.config.mettagrid_config import MettaGridConfig, ResourceLimitsConfig


class SuspicionVariant(CoGameMissionVariant):
    name: str = "suspicion"
    description: str = "Night builds fear; daytime meetings relieve it slightly."

    def dependencies(self) -> Deps:
        return Deps(required=[MeetingsVariant])

    def modify_env(self, mission, env: MettaGridConfig) -> None:
        append_unique(env.game.resource_names, SUSPICION)

        for agent in env.game.agents:
            inv = agent.inventory
            inv.initial[SUSPICION] = 0
            inv.limits["suspicion"] = ResourceLimitsConfig(base=50, max=50, resources=[SUSPICION])

        env.game.events["night_phase_start"].mutations.append(updateTarget({SUSPICION: 1}))
        env.game.events["day_phase_start"].mutations.append(updateTarget({SUSPICION: -2}))
