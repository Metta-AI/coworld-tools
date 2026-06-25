"""Food variant: adds food resource, agent inventory, and fed reward."""

from __future__ import annotations

from mettagrid.cogame.core import CoGameMissionVariant
from mettagrid.config.game_value import stat
from mettagrid.config.handler_config import Handler, actorHas, allOf
from mettagrid.config.mettagrid_config import (
    MettaGridConfig,
    RenderHudConfig,
    RenderStatusBarConfig,
    ResourceLimitsConfig,
)
from mettagrid.config.mutation.stats_mutation import logActorAgentStat
from mettagrid.config.reward_config import reward


class FoodVariant(CoGameMissionVariant):
    """Add food resource, agent inventory limits/initial, and fed reward."""

    name: str = "food"
    description: str = "Food resource, inventory, and fed reward (1/max_steps per step when food ≥ 1)."

    def modify_env(self, mission, env: MettaGridConfig) -> None:
        env.game.resource_names = list(env.game.resource_names) + ["food"]

        for agent in env.game.agents:
            agent.inventory.limits["food"] = ResourceLimitsConfig(base=100, resources=["food"])
            agent.inventory.initial["food"] = 20
            handler = Handler(
                name="track_food",
                filters=[actorHas({"food": 1})],
                mutations=[logActorAgentStat("fed_ticks")],
            )
            agent.on_tick = allOf([agent.on_tick, handler])
            agent.rewards["food"] = reward(
                stat("fed_ticks"),
                weight=1.0 / env.game.max_steps,
            )

        env.game.render.agent_huds["food"] = RenderHudConfig(resource="food", max=100, rank=0)
        env.game.render.object_status["agent"]["food"] = RenderStatusBarConfig(
            resource="food",
            short_name="F",
            max=100,
            rank=0,
        )
