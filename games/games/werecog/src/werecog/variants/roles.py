"""Role assignment mechanics for Werewolf/Mafia."""

from __future__ import annotations

from cogames.core import CoGameMissionVariant
from werecog.variants.common import (
    ALIVE,
    ROLE_VILLAGER,
    ROLE_WEREWOLF,
    append_unique,
)
from mettagrid.config.game_value import inv
from mettagrid.config.mettagrid_config import MettaGridConfig, ResourceLimitsConfig

_PACKMATE_STAT_PREFIX = "wolf_pack_"


def _packmate_slots(mission, num_agents: int) -> int:
    max_cogs = getattr(mission, "max_cogs", num_agents)
    return max(0, max(1, int(max_cogs) // 4) - 1)


class RolesVariant(CoGameMissionVariant):
    name: str = "roles"
    description: str = "Assign secret werewolf/villager roles."

    def modify_env(self, mission, env: MettaGridConfig) -> None:
        append_unique(env.game.resource_names, ALIVE)
        append_unique(env.game.resource_names, ROLE_WEREWOLF)
        append_unique(env.game.resource_names, ROLE_VILLAGER)
        env.game.obs.global_obs.obs["role_werewolf"] = inv(ROLE_WEREWOLF)
        env.game.obs.global_obs.obs["role_villager"] = inv(ROLE_VILLAGER)

        num_agents = len(env.game.agents)
        werewolf_count = max(1, num_agents // 4)
        packmate_slots = _packmate_slots(mission, num_agents)
        for index, agent in enumerate(env.game.agents):
            inventory = agent.inventory
            inventory.initial[ALIVE] = 1
            inventory.initial[ROLE_WEREWOLF] = int(index < werewolf_count)
            inventory.initial[ROLE_VILLAGER] = int(index >= werewolf_count)
            inventory.limits["alive"] = ResourceLimitsConfig(base=1, max=1, resources=[ALIVE])
            inventory.limits["role"] = ResourceLimitsConfig(
                base=1,
                max=1,
                resources=[ROLE_WEREWOLF, ROLE_VILLAGER],
            )

            for slot in range(packmate_slots):
                stat_name = f"{_PACKMATE_STAT_PREFIX}{slot}"
                append_unique(env.game.resource_names, stat_name)
                ally_id = slot + 1 if index < werewolf_count else 0
                if index < werewolf_count:
                    allies = [ally_index + 1 for ally_index in range(werewolf_count) if ally_index != index]
                    ally_id = allies[slot] if slot < len(allies) else 0
                inventory.initial[stat_name] = ally_id
                inventory.limits[stat_name] = ResourceLimitsConfig(
                    base=max(1, num_agents),
                    max=max(1, num_agents),
                    resources=[stat_name],
                )
                env.game.obs.global_obs.obs[stat_name] = inv(stat_name)
