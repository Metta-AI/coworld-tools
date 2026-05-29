"""Kids variant: adds egg/kid lifecycle, kid reward, and egg events."""

from __future__ import annotations

from mettagrid.cogame.core import CoGameMissionVariant, Deps
from hungercog.variants.food import FoodVariant
from hungercog.variants.seasons import (
    FOOD_DRAIN_PERIOD,
    SEASON_LENGTH,
    STARVATION_CHECK_PERIOD,
    YEAR_LENGTH,
)
from mettagrid.config.event_config import EventConfig, periodic
from mettagrid.config.filter.filter import isNot
from mettagrid.config.game_value import InventoryValue
from mettagrid.config.handler_config import targetHas, updateTarget
from mettagrid.config.mettagrid_config import MettaGridConfig, ResourceLimitsConfig
from mettagrid.config.query import query
from mettagrid.config.render_config import RenderHudConfig, RenderStatusBarConfig
from mettagrid.config.reward_config import reward
from mettagrid.config.tag import typeTag


class KidsVariant(CoGameMissionVariant):
    """Add egg/kid resources, limits, kid reward, and egg lifecycle events."""

    name: str = "kids"
    description: str = "Seasonal egg lifecycle: fall drop, spring hatch, kid reward."

    def dependencies(self) -> Deps:
        return Deps(required=[FoodVariant])

    def modify_env(self, mission, env: MettaGridConfig) -> None:
        for r in ("egg", "kid"):
            if r not in env.game.resource_names:
                env.game.resource_names = list(env.game.resource_names) + [r]

        max_steps = env.game.max_steps
        num_years = max_steps // YEAR_LENGTH
        kid_weight = 1.0 / max(1, num_years)

        for agent in env.game.agents:
            inv = agent.inventory
            inv.limits["egg"] = ResourceLimitsConfig(base=1, resources=["egg"])
            inv.limits["kid"] = ResourceLimitsConfig(base=100, resources=["kid"])
            agent.rewards["kids"] = reward(InventoryValue(item="kid"), weight=kid_weight)

        agent_query = query(typeTag("agent"))
        env.game.events["food_drain"] = EventConfig(
            name="food_drain",
            target_query=agent_query,
            timesteps=periodic(start=0, period=FOOD_DRAIN_PERIOD, end=max_steps),
            mutations=[updateTarget({"food": -1})],
        )

        egg_drop_timesteps = [y * YEAR_LENGTH + SEASON_LENGTH for y in range(num_years)]
        egg_hatch_timesteps = [y * YEAR_LENGTH + 3 * SEASON_LENGTH for y in range(num_years)]

        env.game.events["egg_drop"] = EventConfig(
            name="egg_drop",
            target_query=agent_query,
            timesteps=egg_drop_timesteps,
            mutations=[updateTarget({"egg": 1})],
        )
        env.game.events["egg_hatch"] = EventConfig(
            name="egg_hatch",
            target_query=agent_query,
            timesteps=egg_hatch_timesteps,
            filters=[targetHas({"egg": 1})],
            mutations=[updateTarget({"egg": -1}), updateTarget({"kid": 1})],
        )
        env.game.events["starvation_check"] = EventConfig(
            name="starvation_check",
            target_query=agent_query,
            timesteps=periodic(start=0, period=STARVATION_CHECK_PERIOD, end=max_steps),
            filters=[targetHas({"egg": 1}), isNot(targetHas({"food": 1}))],
            mutations=[updateTarget({"egg": -1})],
        )

        env.game.render.agent_huds["egg"] = RenderHudConfig(resource="egg", max=1, rank=2)
        env.game.render.agent_huds["kid"] = RenderHudConfig(resource="kid", max=5, rank=3)
        env.game.render.object_status["agent"]["egg"] = RenderStatusBarConfig(
            resource="egg",
            short_name="EG",
            max=1,
            divisions=10,
            rank=2,
        )
        env.game.render.object_status["agent"]["kid"] = RenderStatusBarConfig(
            resource="kid",
            short_name="KD",
            max=5,
            divisions=10,
            rank=3,
        )
