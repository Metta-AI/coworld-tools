"""Solar variant: day/night cycle that modulates agent solar resource."""

from __future__ import annotations

from cogames.core import CoGameMissionVariant, Deps
from hungercog.variants.energy import EnergyVariant
from mettagrid.config.event_config import EventConfig, periodic
from mettagrid.config.game_value import InventoryValue
from mettagrid.config.handler_config import Handler, allOf, updateTarget
from mettagrid.config.mettagrid_config import MettaGridConfig, ResourceLimitsConfig
from mettagrid.config.mutation.game_value_mutation import SetGameValueMutation
from mettagrid.config.mutation.mutation import EntityTarget
from mettagrid.config.query import query
from mettagrid.config.tag import typeTag

DAY_LENGTH = 50
DAY_SOLAR_DELTA = 2


class SolarVariant(CoGameMissionVariant):
    """Add day/night cycle: solar oscillates, affecting energy regen."""

    name: str = "solar"
    description: str = "Day/night cycle: solar varies, affecting energy regen."

    def dependencies(self) -> Deps:
        return Deps(required=[EnergyVariant])

    def modify_env(self, mission, env: MettaGridConfig) -> None:
        env.game.resource_names.append("solar")

        for agent in env.game.agents:
            agent.inventory.limits["solar"] = ResourceLimitsConfig(base=1, resources=["solar"])
            agent.inventory.initial["solar"] = 1
            handler = Handler(
                name="solar_to_energy",
                mutations=[
                    SetGameValueMutation(
                        value=InventoryValue(item="energy"),
                        source=InventoryValue(item="solar"),
                        target=EntityTarget.ACTOR,
                    )
                ],
            )
            agent.on_tick = allOf([agent.on_tick, handler])

        max_steps = env.game.max_steps
        half_day = DAY_LENGTH // 2

        env.game.events["day_solar"] = EventConfig(
            name="day_solar",
            target_query=query(typeTag("agent")),
            timesteps=periodic(start=0, period=DAY_LENGTH, end=max_steps),
            mutations=[updateTarget({"solar": DAY_SOLAR_DELTA})],
        )
        env.game.events["night_solar"] = EventConfig(
            name="night_solar",
            target_query=query(typeTag("agent")),
            timesteps=periodic(start=half_day, period=DAY_LENGTH, end=max_steps),
            mutations=[updateTarget({"solar": -DAY_SOLAR_DELTA})],
        )
