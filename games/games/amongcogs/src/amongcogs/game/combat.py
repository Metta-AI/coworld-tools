"""Among Us impostor kill mechanics."""

from __future__ import annotations

from mettagrid.cogame.core import CoGameMissionVariant, Deps
from amongcogs.constants import (
    ALIVE_RESOURCE,
    CORPSE_RESOURCE,
    KILL_COOLDOWN_RESOURCE,
    MEETING_ACTIVE_RESOURCE,
    ROLE_CREW,
    ROLE_IMPOSTOR,
    VIBE_KILL,
)
from amongcogs.game.common import kill_cooldown_steps
from amongcogs.game.roles import RolesVariant
from mettagrid.config.event_config import EventConfig, periodic
from mettagrid.config.filter import GameValueFilter, HandlerTarget, isNot, maxDistance, targetHas, targetVibe
from mettagrid.config.game_value import num
from mettagrid.config.handler_config import queryDelta, updateTarget
from mettagrid.config.mettagrid_config import MettaGridConfig
from mettagrid.config.mutation.stats_mutation import logActorAgentStat, logStatToGame
from mettagrid.config.query import Query, query
from mettagrid.config.tag import typeTag


class CombatVariant(CoGameMissionVariant):
    name: str = "combat"
    description: str = "Impostor cooldown + proximity kill loop."

    def dependencies(self) -> Deps:
        return Deps(required=[RolesVariant])

    def modify_env(self, mission, env: MettaGridConfig) -> None:
        max_steps = env.game.max_steps
        nearby_alive_crew_query = Query(
            source=typeTag("agent"),
            filters=[targetHas({ROLE_CREW: 1, ALIVE_RESOURCE: 1}), maxDistance(1)],
            max_items=1,
            order_by="random",
        )

        env.game.events["impostor_kill_cooldown_tick"] = EventConfig(
            name="impostor_kill_cooldown_tick",
            target_query=query(typeTag("agent")),
            timesteps=periodic(start=1, period=1, end=max_steps),
            filters=[targetHas({ROLE_IMPOSTOR: 1, KILL_COOLDOWN_RESOURCE: 1})],
            mutations=[updateTarget({KILL_COOLDOWN_RESOURCE: -1})],
        )
        env.game.events["impostor_kill_nearby_crew"] = EventConfig(
            name="impostor_kill_nearby_crew",
            target_query=query(typeTag("agent")),
            timesteps=periodic(start=1, period=1, end=max_steps),
            filters=[
                targetHas({ROLE_IMPOSTOR: 1, ALIVE_RESOURCE: 1}),
                isNot(targetHas({MEETING_ACTIVE_RESOURCE: 1})),
                isNot(targetHas({KILL_COOLDOWN_RESOURCE: 1})),
                targetVibe(VIBE_KILL),
                GameValueFilter(
                    target=HandlerTarget.TARGET,
                    value=num(
                        typeTag("agent"),
                        filters=[targetHas({ROLE_CREW: 1, ALIVE_RESOURCE: 1}), maxDistance(1)],
                    ),
                    min=1,
                ),
            ],
            mutations=[
                queryDelta(nearby_alive_crew_query, {ALIVE_RESOURCE: -1, CORPSE_RESOURCE: 1}),
                updateTarget({KILL_COOLDOWN_RESOURCE: kill_cooldown_steps(mission)}),
                logActorAgentStat("kills"),
                logStatToGame("impostor_kills"),
            ],
        )
