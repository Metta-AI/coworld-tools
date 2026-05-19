"""Digest variant: agents consume 1 food every 10 ticks."""

from __future__ import annotations

from cogames.core import CoGameMissionVariant, Deps
from hungercog.variants.food import FoodVariant
from mettagrid.config.event_config import EventConfig, periodic
from mettagrid.config.handler_config import updateTarget
from mettagrid.config.mettagrid_config import MettaGridConfig
from mettagrid.config.query import query
from mettagrid.config.tag import typeTag

DIGEST_PERIOD = 10


class DigestVariant(CoGameMissionVariant):
    """Agents consume 1 food every 10 ticks."""

    name: str = "digest"
    description: str = "Agents consume 1 food every 10 ticks."

    def dependencies(self) -> Deps:
        return Deps(required=[FoodVariant])

    def modify_env(self, mission, env: MettaGridConfig) -> None:
        max_steps = env.game.max_steps
        env.game.events["digest"] = EventConfig(
            name="digest",
            target_query=query(typeTag("agent")),
            timesteps=periodic(start=0, period=DIGEST_PERIOD, end=max_steps),
            mutations=[updateTarget({"food": -1})],
        )
