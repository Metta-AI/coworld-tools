"""Carnivore variant: adds carnivore station and carnivore-herbivore handlers."""

from __future__ import annotations

from mettagrid.cogame.core import CoGameMissionVariant, Deps
from hungercog.variants.food import FoodVariant
from mettagrid.config.filter import actorHasAnyOf
from mettagrid.config.handler_config import (
    Handler,
    actorHas,
    firstMatch,
    targetHas,
    updateActor,
    updateTarget,
    withdraw,
)
from mettagrid.config.mettagrid_config import GridObjectConfig, MettaGridConfig
from mettagrid.config.render_config import RenderAsset


class CarnivoreVariant(CoGameMissionVariant):
    """Add carnivores: carnivore gear, carnivore station, and carnivore-herbivore interactions."""

    name: str = "carnivore"
    description: str = "Carnivores can tag herbivores and steal food."

    def dependencies(self) -> Deps:
        return Deps(required=[FoodVariant])

    @staticmethod
    def carnivore_station_config() -> GridObjectConfig:
        """Gear station that gives carnivore role. Once picked, cannot be changed."""
        return GridObjectConfig(
            name="carnivore_station",
            on_use_handler=firstMatch(
                [
                    Handler(
                        name="has_gear",
                        filters=[actorHasAnyOf(["carnivore", "herbivore"])],
                        mutations=[],
                    ),
                    Handler(
                        name="get_gear",
                        filters=[],
                        mutations=[updateActor({"carnivore": 1})],
                    ),
                ]
            ),
        )

    def modify_env(self, mission, env: MettaGridConfig) -> None:
        env.game.resource_names.append("carnivore")
        env.game.objects["carnivore_station"] = self.carnivore_station_config()

        for agent in env.game.agents:
            agent.inventory.limits["gear"].resources.append("carnivore")
            agent.on_use_handler = firstMatch(
                [
                    Handler(
                        name="eat_prey",
                        filters=[actorHas({"carnivore": 1}), targetHas({"herbivore": 1})],
                        mutations=[withdraw({"food": 9999})],
                    ),
                    Handler(
                        name="fight_predator",
                        filters=[actorHas({"carnivore": 1}), targetHas({"carnivore": 1})],
                        mutations=[updateActor({"egg": -1}), updateTarget({"egg": -1})],
                    ),
                ]
            )

        instance = getattr(env.game.map_builder, "instance", None)
        if instance is not None and hasattr(instance, "hub") and instance.hub is not None:
            instance.hub.stations.append("carnivore_station")
            instance.hub.stations.append("carnivore_station")

        env.game.render.assets["agent"].append(RenderAsset(asset="scrambler", resources={"carnivore": 1}))
        env.game.render.assets["carnivore_station"] = [RenderAsset(asset="scrambler")]
