"""Among Us role-assignment mechanics."""

from __future__ import annotations

from typing import cast

from mettagrid.cogame.core import CoGameMissionVariant
from amongcogs.constants import (
    FORCE_ROLE_ASSIGN_STEP,
    KILL_COOLDOWN_RESOURCE,
    ROLE_CREW,
    ROLE_IMPOSTOR,
    SABOTAGE_COOLDOWN_RESOURCE,
    crew_station_config,
    impostor_count_for_lobby,
    impostor_station_config,
)
from amongcogs.game.common import initial_kill_cooldown_steps, initial_sabotage_cooldown_steps
from mettagrid.config.event_config import EventConfig
from mettagrid.config.filter import isNot, targetHasAnyOf
from mettagrid.config.handler_config import updateTarget
from mettagrid.config.mettagrid_config import MettaGridConfig
from mettagrid.config.mutation.stats_mutation import logStatToGame
from mettagrid.config.query import Query, query
from mettagrid.config.tag import typeTag


class RolesVariant(CoGameMissionVariant):
    name: str = "roles"
    description: str = "Automatic round-start crew/impostor role assignment."

    def modify_env(self, mission, env: MettaGridConfig) -> None:
        num_cogs = cast(int, mission.num_cogs)
        env.game.objects["crew_station"] = crew_station_config()
        env.game.objects["impostor_station"] = impostor_station_config()

        unassigned_agents = [isNot(targetHasAnyOf([ROLE_CREW, ROLE_IMPOSTOR]))]
        random_unassigned_query = Query(
            source=typeTag("agent"),
            filters=unassigned_agents,
            order_by="random",
        )

        env.game.events["force_assign_impostor_role"] = EventConfig(
            name="force_assign_impostor_role",
            target_query=random_unassigned_query,
            timesteps=[FORCE_ROLE_ASSIGN_STEP],
            filters=unassigned_agents,
            mutations=[
                updateTarget(
                    {
                        ROLE_IMPOSTOR: 1,
                        KILL_COOLDOWN_RESOURCE: initial_kill_cooldown_steps(mission),
                        SABOTAGE_COOLDOWN_RESOURCE: initial_sabotage_cooldown_steps(mission),
                    }
                ),
                logStatToGame("force_role_assign_impostor"),
            ],
            max_targets=impostor_count_for_lobby(num_cogs),
        )
        env.game.events["force_assign_crew_roles"] = EventConfig(
            name="force_assign_crew_roles",
            target_query=query(typeTag("agent")),
            timesteps=[FORCE_ROLE_ASSIGN_STEP + 1],
            filters=unassigned_agents,
            mutations=[
                updateTarget({ROLE_CREW: 1}),
                logStatToGame("force_role_assign_crew"),
            ],
        )
