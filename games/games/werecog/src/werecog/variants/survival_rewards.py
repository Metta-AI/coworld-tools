"""Survival reward shaping variant."""

from __future__ import annotations

from mettagrid.cogame.core import CoGameMissionVariant, Deps
from werecog.variants.common import ALIVE, agent_is_werewolf
from werecog.variants.roles import RolesVariant
from mettagrid.config.game_value import stat
from mettagrid.config.handler_config import Handler, actorHas, allOf
from mettagrid.config.mettagrid_config import MettaGridConfig
from mettagrid.config.mutation.stats_mutation import logActorAgentStat
from mettagrid.config.reward_config import reward


class SurvivalRewardsVariant(CoGameMissionVariant):
    name: str = "survival_rewards"
    description: str = "Reward survival ticks for both roles."

    def dependencies(self) -> Deps:
        return Deps(required=[RolesVariant])

    def modify_env(self, mission, env: MettaGridConfig) -> None:
        step_scale = 1.0 / max(1, env.game.max_steps)
        for agent in env.game.agents:
            agent.on_tick = allOf(
                [
                    agent.on_tick,
                    Handler(
                        name="alive_tick",
                        filters=[actorHas({ALIVE: 1})],
                        mutations=[logActorAgentStat("alive_ticks")],
                    ),
                ]
            )
            survival_weight = 0.20 * step_scale if agent_is_werewolf(agent) else 0.40 * step_scale
            agent.rewards["survival"] = reward(stat("alive_ticks"), weight=survival_weight)
