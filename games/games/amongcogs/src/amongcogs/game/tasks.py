"""Among Us task station interaction mechanics."""

from __future__ import annotations

from cogames.core import CoGameMissionVariant, Deps
from amongcogs.constants import TASK_STATION_NAMES, task_station_config
from amongcogs.game.roles import RolesVariant
from mettagrid.config.mettagrid_config import MettaGridConfig


class TasksVariant(CoGameMissionVariant):
    name: str = "tasks"
    description: str = "Crew task completion and impostor sabotage interactions at task stations."

    def dependencies(self) -> Deps:
        return Deps(required=[RolesVariant])

    def modify_env(self, mission, env: MettaGridConfig) -> None:
        del mission
        for station_name in TASK_STATION_NAMES:
            env.game.objects[station_name] = task_station_config(station_name)
