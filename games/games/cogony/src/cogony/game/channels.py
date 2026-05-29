"""Channel-stat resources for the four subsystems (RULES.md section 2).

Four subsystems: Core, OS, Generator, Storage.
Each subsystem has two stats: Attack (Dmg) and Defense (Res).
That gives 8 inventory resources total, named by their gear type:

  Attack:  core_a (Core), os_a (OS), gen_a (Generator), storage_a (Storage)
  Defense: core_d (Core), os_d (OS), gen_d (Generator), storage_d (Storage)

All stats start at 0 for agents (gear is the only source of combat stats).
Nodes (extractors, junctions) also carry the 8 resources so the combat
formula can read them uniformly.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, override

from mettagrid.cogame.core import CoGameMissionVariant
from mettagrid.config.mettagrid_config import MettaGridConfig, ResourceLimitsConfig

if TYPE_CHECKING:
    from cogony.mission import CogonyMission

# Per-subsystem gear names: (attack, defense) for Core, OS, Generator, Storage.
CHANNEL_GEAR: list[tuple[str, str]] = [
    ("core_a", "core_d"),         # Core
    ("os_a", "os_d"),             # OS
    ("gen_a", "gen_d"),           # Generator
    ("storage_a", "storage_d"),   # Storage
]

# Flat lists by stat category (useful for the combat formula).
DMG_STATS: list[str] = [g[0] for g in CHANNEL_GEAR]
RES_STATS: list[str] = [g[1] for g in CHANNEL_GEAR]

# All 8 resource names in a stable order.
CHANNEL_STATS: list[str] = DMG_STATS + RES_STATS

# Per-subsystem damage tracking resources.
SYS_DAMAGE_STATS: list[str] = [
    "sys_damage_core",
    "sys_damage_os",
    "sys_damage_gen",
    "sys_damage_storage",
]

STAT_CAP = 100


class ChannelsVariant(CoGameMissionVariant):
    """Register the 8 channel-stat inventory resources on agents and nodes.

    Resources: core_a, os_a, gen_a, storage_a,
               core_d, os_d, gen_d, storage_d.

    All start at 0. Cap defaults to 100.
    """

    name: str = "channels"
    description: str = "Four subsystems with Attack/Defense stats."

    stat_cap: int = STAT_CAP

    @override
    def modify_env(self, mission: CogonyMission, env: MettaGridConfig) -> None:
        # Register each channel stat as a game resource.
        for stat in CHANNEL_STATS:
            env.game.add_resource(stat)
        for stat in SYS_DAMAGE_STATS:
            env.game.add_resource(stat)

        # Add to every agent.
        for agent in env.game.agents:
            for stat in CHANNEL_STATS:
                agent.inventory.limits.setdefault(
                    stat,
                    ResourceLimitsConfig(
                        base=self.stat_cap,
                        max=self.stat_cap,
                        resources=[stat],
                    ),
                )
                agent.inventory.initial.setdefault(stat, 0)

        # Add to node objects (extractors, junctions) so the combat formula
        # can read Dmg/Res uniformly. Nodes set their own initial values
        # based on level (RULES.md section 4); setdefault preserves those.
        for obj in env.game.objects.values():
            for stat in CHANNEL_STATS:
                obj.inventory.limits.setdefault(
                    stat,
                    ResourceLimitsConfig(
                        base=self.stat_cap,
                        max=self.stat_cap,
                        resources=[stat],
                    ),
                )
                obj.inventory.initial.setdefault(stat, 0)
