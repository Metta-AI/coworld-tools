"""Role-specific action reward shaping."""

from __future__ import annotations

from cogames.core import CoGameMissionVariant, Deps
from werecog.variants.common import agent_is_werewolf
from werecog.variants.hunt import HuntVariant
from werecog.variants.voting import VotingVariant
from mettagrid.config.game_value import stat
from mettagrid.config.mettagrid_config import MettaGridConfig
from mettagrid.config.reward_config import reward


class RoleActionRewardsVariant(CoGameMissionVariant):
    name: str = "role_action_rewards"
    description: str = "Reward role-specific elimination and voting actions."

    def dependencies(self) -> Deps:
        return Deps(required=[HuntVariant, VotingVariant])

    def modify_env(self, mission, env: MettaGridConfig) -> None:
        step_scale = 1.0 / max(1, env.game.max_steps)
        for agent in env.game.agents:
            if agent_is_werewolf(agent):
                agent.rewards["hunt"] = reward(stat("villager_eliminations"), weight=1.0 * step_scale)
            else:
                agent.rewards["vote"] = reward(stat("werewolf_votes"), weight=1.0 * step_scale)
