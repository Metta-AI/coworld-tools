"""Datacenter config and variant.

Datacenters are research nodes (like junctions) that generate 100 creds
per 100 ticks when aligned to a CAO. Same subsystem/exploit stats as junctions.
"""

from __future__ import annotations

import random as _rng
from typing import TYPE_CHECKING, override

from cogames.core import CoGameMissionVariant, Deps
from cogony.game.channels import DMG_STATS, RES_STATS, SYS_DAMAGE_STATS
from mettagrid.config.mettagrid_config import (
    GridObjectConfig,
    InventoryConfig,
    MettaGridConfig,
    ResourceLimitsConfig,
)

if TYPE_CHECKING:
    from cogony.mission import CogonyMission


def datacenter_config() -> GridObjectConfig:
    max_coh = 10
    limits: dict[str, ResourceLimitsConfig] = {
        "coherence": ResourceLimitsConfig(base=10, max=65535, resources=["coherence"], modifiers={"core_d": 5}),
        "reboot": ResourceLimitsConfig(base=65535, max=65535, resources=["reboot"]),
        "scrambled": ResourceLimitsConfig(base=65535, max=65535, resources=["scrambled"]),
        "level": ResourceLimitsConfig(base=65535, max=65535, resources=["level"]),
    }
    for sd in SYS_DAMAGE_STATS:
        limits[sd] = ResourceLimitsConfig(base=65535, max=65535, resources=[sd])
    initial: dict[str, int] = {
        "coherence": max_coh,
        "reboot": 0,
        "scrambled": 0,
        "level": 1,
    }
    for sd in SYS_DAMAGE_STATS:
        initial[sd] = 0
    for stat in RES_STATS:
        initial[stat] = 0
    for stat in DMG_STATS:
        initial[stat] = 0
    initial[_rng.choice(RES_STATS)] = 1
    initial[_rng.choice(DMG_STATS)] = 1

    return GridObjectConfig(
        name="datacenter",
        tags=["node"],
        inventory=InventoryConfig(limits=limits, initial=initial),
    )


class DatacenterVariant(CoGameMissionVariant):
    name: str = "datacenter"
    description: str = "Add datacenter objects to the map."

    @override
    def modify_env(self, mission: CogonyMission, env: MettaGridConfig) -> None:
        env.game.objects["datacenter"] = datacenter_config()
