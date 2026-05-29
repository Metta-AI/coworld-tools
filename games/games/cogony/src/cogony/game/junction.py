"""Junction station config and variant (RULES.md section 5).

Junctions have a level (starting at 1). Stats derived from level:
- Max coherence: level * 10
- Resist stats (core_d/os_d/gen_d/storage_d): level each
- Dmg stats (core_a/os_a/gen_a/storage_a): max(0, level - 3) each
- patch: 1
- No element inventory.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, override

from mettagrid.cogame.core import CoGameMissionVariant, Deps
from cogony.game.channels import DMG_STATS, RES_STATS, SYS_DAMAGE_STATS
from cogony.game.terrain import BuildingsVariant
from mettagrid.cogame.variants import ResolvedDeps
from mettagrid.config.mettagrid_config import (
    GridObjectConfig,
    InventoryConfig,
    MettaGridConfig,
    ResourceLimitsConfig,
)

if TYPE_CHECKING:
    from cogony.mission import CogonyMission

# Starting level for junctions.
JUNCTION_LEVEL = 1


def junction_config(level: int = JUNCTION_LEVEL) -> GridObjectConfig:
    """Build a junction GridObjectConfig for the given level."""
    max_coh = 10
    res_val = level
    dmg_val = max(0, level - 3)

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
        "level": level,
    }
    for sd in SYS_DAMAGE_STATS:
        initial[sd] = 0

    for stat in RES_STATS:
        initial[stat] = 0
    for stat in DMG_STATS:
        initial[stat] = 0
    import random as _rng
    initial[_rng.choice(RES_STATS)] = 1
    initial[_rng.choice(DMG_STATS)] = 1

    return GridObjectConfig(
        name="junction",
        tags=["node"],
        inventory=InventoryConfig(limits=limits, initial=initial),
    )


class JunctionVariant(CoGameMissionVariant):
    """Add bare junction objects to the environment."""

    name: str = "junction"
    description: str = "Add junction objects to the map."

    @override
    def dependencies(self) -> Deps:
        return Deps(required=[BuildingsVariant])

    @override
    def configure(self, deps: ResolvedDeps) -> None:
        deps.required(BuildingsVariant).building_density["junction"] = 0.3

    @override
    def modify_env(self, mission: CogonyMission, env: MettaGridConfig) -> None:
        env.game.objects["junction"] = junction_config()
