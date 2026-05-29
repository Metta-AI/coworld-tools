"""Among Us vent-travel mechanic slice."""

from __future__ import annotations

from mettagrid.cogame.core import CoGameMissionVariant, Deps
from amongcogs.constants import VENT_COOLDOWN_RESOURCE, VENT_NETWORK_BY_NAME, vent_station_config
from amongcogs.game.common import vent_cooldown_steps
from amongcogs.game.roles import RolesVariant
from mettagrid.config.event_config import EventConfig, periodic
from mettagrid.config.filter import targetHas
from mettagrid.config.handler_config import updateTarget
from mettagrid.config.mettagrid_config import MettaGridConfig
from mettagrid.config.query import query
from mettagrid.config.tag import typeTag


class VentsVariant(CoGameMissionVariant):
    name: str = "vents"
    description: str = "Impostor-only vent travel between Skeld vent networks."

    def dependencies(self) -> Deps:
        return Deps(required=[RolesVariant])

    def modify_env(self, mission, env: MettaGridConfig) -> None:
        cooldown_steps = vent_cooldown_steps(mission)
        for station_name, network_tag in VENT_NETWORK_BY_NAME.items():
            env.game.objects[station_name] = vent_station_config(
                station_name,
                network_tag=network_tag,
                cooldown_steps=cooldown_steps,
            )
        env.game.events["vent_cooldown_tick"] = EventConfig(
            name="vent_cooldown_tick",
            target_query=query(typeTag("agent")),
            timesteps=periodic(start=1, period=1, end=env.game.max_steps),
            filters=[targetHas({VENT_COOLDOWN_RESOURCE: 1})],
            mutations=[updateTarget({VENT_COOLDOWN_RESOURCE: -1})],
        )
