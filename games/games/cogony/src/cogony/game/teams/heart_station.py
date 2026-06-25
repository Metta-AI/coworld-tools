"""Heart altar: a single station at map center where cogs buy hearts."""

from __future__ import annotations

from typing import TYPE_CHECKING, override

from mettagrid.cogame.core import CoGameMissionVariant, Deps
from cogony.game.creds import CredsVariant
from cogony.game.heart import HeartVariant
from cogony.terrain import find_arena
from mettagrid.config.filter import actorHas
from mettagrid.config.handler_config import Handler, updateActor
from mettagrid.config.mettagrid_config import GridObjectConfig, InventoryConfig, MettaGridConfig
from mettagrid.config.render_config import RenderAsset

if TYPE_CHECKING:
    from cogony.mission import CogonyMission

HEART_PRICE = 100
MAP_NAME = "heart_altar"


class TeamHeartStationVariant(CoGameMissionVariant):
    """Place a single heart altar at the center of the map."""

    name: str = "team_heart_station"
    description: str = "Single heart altar at map center: buy hearts for creds."

    @override
    def dependencies(self) -> Deps:
        return Deps(required=[CredsVariant, HeartVariant])

    @override
    def modify_env(self, mission: CogonyMission, env: MettaGridConfig) -> None:
        cfg = GridObjectConfig(
            name="heart_station",
            map_name=MAP_NAME,
            inventory=InventoryConfig(initial={"creds": HEART_PRICE, "heart": 1}),
            on_use_handler=Handler(
                name="buy_heart",
                filters=[actorHas({"creds": HEART_PRICE})],
                mutations=[updateActor({"creds": -HEART_PRICE, "heart": 1})],
            ),
        )
        env.game.objects.setdefault(MAP_NAME, cfg)
        env.game.render.symbols[MAP_NAME] = "♥"
        env.game.render.assets[MAP_NAME] = [RenderAsset(asset="heart_station")]

        arena = find_arena(env.game.map_builder)
        if arena is not None:
            arena.map_center_objects = [MAP_NAME]
