"""Plant variant: adds plant objects (harvest requires herbivore). Use seasons variant for food drops."""

from __future__ import annotations

from mettagrid.cogame.core import CoGameMissionVariant, Deps
from hungercog.variants.food import FoodVariant
from mettagrid.config.filter.filter import isNot
from mettagrid.config.handler_config import Handler, actorHas, firstMatch, targetHas, withdraw
from mettagrid.config.mettagrid_config import GridObjectConfig, InventoryConfig, MettaGridConfig
from mettagrid.config.render_config import RenderAsset, RenderStatusBarConfig

INITIAL_PLANT_FOOD = 1
MAX_PLANT_FOOD = 100
PLANT_DENSITY = 0.016
MAP_WIDTH = 88
MAP_HEIGHT = 88
HUB_PLANT_OBJECT_COUNT = 8


class PlantVariant(CoGameMissionVariant):
    """Add plant objects: scatter on map, hub placement. Harvest requires herbivore."""

    name: str = "plant"
    description: str = "Plant objects scatter the map. Herbivores harvest for food."

    def dependencies(self) -> Deps:
        return Deps(required=[FoodVariant])

    def modify_env(self, mission, env: MettaGridConfig) -> None:
        env.game.objects["plant"] = plant_config()
        env.game.render.assets["plant"] = [
            RenderAsset(asset="junction.working", resources={"food": 1}),
            RenderAsset(asset="junction"),
        ]
        env.game.render.object_status["plant"] = {
            "food": RenderStatusBarConfig(resource="food", short_name="F", max=50, divisions=10, rank=0),
        }

        instance = getattr(env.game.map_builder, "instance", None)
        if instance is not None:
            instance.building_coverage = PLANT_DENSITY
            instance.building_names = ["plant"]
            instance.building_weights = {"plant": 1.0}
            # Compound places corner/cross objects after spawn pads, so reserve pads for those object cells.
            instance.spawn_count += HUB_PLANT_OBJECT_COUNT
            if instance.hub is not None:
                instance.hub.hub_object = "plant"
                instance.hub.corner_bundle = "custom"
                instance.hub.corner_objects = ["plant", "plant", "plant", "plant"]
                instance.hub.cross_bundle = "custom"
                instance.hub.cross_objects = ["plant", "plant", "plant", "plant"]


def plant_config() -> GridObjectConfig:
    """Plant with harvest handlers. Requires herbivore gear."""
    return GridObjectConfig(
        name="plant",
        inventory=InventoryConfig(initial={"food": INITIAL_PLANT_FOOD}, default_limit=MAX_PLANT_FOOD),
        on_use_handler=firstMatch(
            [
                Handler(
                    name="harvest_last",
                    filters=[actorHas({"herbivore": 1}), isNot(targetHas({"food": 2}))],
                    mutations=[withdraw({"food": 100})],
                ),
                Handler(
                    name="harvest",
                    filters=[actorHas({"herbivore": 1})],
                    mutations=[withdraw({"food": 100})],
                ),
            ]
        ),
    )
