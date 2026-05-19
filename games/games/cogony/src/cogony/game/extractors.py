from __future__ import annotations

from typing import TYPE_CHECKING, override

from cogames.core import CoGameMissionVariant, CvCStationConfig, Deps
from cogony.game.channels import DMG_STATS, RES_STATS, SYS_DAMAGE_STATS
from cogony.game.elements import ElementsVariant
from cogony.game.terrain import BuildingsVariant
from cogony.terrain import find_arena
from cogames.variants import ResolvedDeps
from mettagrid.config.filter import isNot, targetHas
from mettagrid.config.handler_config import (
    Handler,
    withdraw,
)
from mettagrid.config.mettagrid_config import (
    GridObjectConfig,
    InventoryConfig,
    MettaGridConfig,
    ResourceLimitsConfig,
)
from mettagrid.config.render_config import RenderAsset
from mettagrid.mapgen.scenes.building_distributions import DistributionConfig, DistributionType

if TYPE_CHECKING:
    from cogony.mission import CogonyMission

# Starting level for extractors.
EXTRACTOR_LEVEL = 1

# On reboot, each extractor gains +1 to its primary subsystem (attack +
# defense) and +1 to one secondary subsystem. All four stats go up every level.
_REBOOT_STATS: dict[str, list[str]] = {
    "carbon":    ["core_a", "core_d", "os_a", "os_d"],
    "oxygen":    ["os_a", "os_d", "gen_a", "gen_d"],
    "germanium": ["gen_a", "gen_d", "storage_a", "storage_d"],
    "silicon":   ["storage_a", "storage_d", "core_a", "core_d"],
}


def extractor_config(resource: str, *, level: int = EXTRACTOR_LEVEL, initial_amount: int | None = None) -> GridObjectConfig:
    """Build an extractor GridObjectConfig for the given resource and level.

    Args:
        resource: Element name (carbon, oxygen, germanium, silicon).
        level: Node level (default 1). Determines coherence, resist, dmg stats.
        initial_amount: Override for element inventory. If None, uses ``level``.
    """
    max_coh = 10
    res_val = level
    dmg_val = max(0, level - 3)
    element_amount = initial_amount if initial_amount is not None else level

    limits: dict[str, ResourceLimitsConfig] = {
        "coherence": ResourceLimitsConfig(base=10, max=65535, resources=["coherence"], modifiers={"core_d": 5}),
        "reboot": ResourceLimitsConfig(base=65535, max=65535, resources=["reboot"]),
        "scrambled": ResourceLimitsConfig(base=65535, max=65535, resources=["scrambled"]),
        "level": ResourceLimitsConfig(base=65535, max=65535, resources=["level"]),
        "creds": ResourceLimitsConfig(base=65535, max=65535, resources=["creds"]),
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
        name=f"{resource}_extractor",
        tags=["node"],
        on_use_handler=Handler(
            name="extract",
            mutations=[withdraw({resource: 1}, remove_when_empty=False)],
        ),
        inventory=InventoryConfig(
            limits=limits,
            initial=initial,
            default_limit=65535,
        ),
    )


class ExtractorConfig(CvCStationConfig):
    """Station config for a single-resource extractor."""

    resource: str
    initial_amount: int = 200
    small_amount: int = 1

    def station_cfg(self) -> GridObjectConfig:
        return GridObjectConfig(
            name=f"{self.resource}_extractor",
            on_use_handler=Handler(
                name="extract",
                mutations=[withdraw({self.resource: self.small_amount}, remove_when_empty=True)],
            ),
            inventory=InventoryConfig(initial={self.resource: self.initial_amount}),
        )


class ExtractorsVariant(CoGameMissionVariant):
    """Add resource extractors to the environment."""

    name: str = "extractors"
    description: str = "Place extractors for each element on the map."
    extractor_density: float = 0.15
    initial_amount: int = 200

    @override
    def dependencies(self) -> Deps:
        return Deps(required=[BuildingsVariant, ElementsVariant])

    @override
    def configure(self, deps: ResolvedDeps) -> None:
        terrain = deps.required(BuildingsVariant)
        for element in deps.required(ElementsVariant).elements:
            terrain.building_density[f"{element}_extractor"] = self.extractor_density

    QUADRANT_CENTERS: dict[str, tuple[float, float]] = {
        "carbon": (0.2, 0.2),
        "oxygen": (0.2, 0.8),
        "germanium": (0.8, 0.2),
        "silicon": (0.8, 0.8),
    }

    @override
    def modify_env(self, mission: CogonyMission, env: MettaGridConfig) -> None:
        arena = find_arena(env.game.map_builder)
        if arena is not None:
            arena.hub.corner_bundle = "extractors"
            dists = arena.building_distributions or {}
            for element, (cy, cx) in self.QUADRANT_CENTERS.items():
                dists[f"{element}_extractor"] = DistributionConfig(
                    type=DistributionType.NORMAL,
                    mean_x=cx,
                    mean_y=cy,
                    std_x=0.25,
                    std_y=0.25,
                )
            arena.building_distributions = dists

        for resource in mission.required_variant(ElementsVariant).elements:
            key = f"{resource}_extractor"
            env.game.objects[key] = extractor_config(resource)
            env.game.render.assets[key] = [
                RenderAsset(asset=key, resources={"coherence": 1}),
                RenderAsset(asset=f"{key}.depleted"),
            ]
            # Loot drops are handled by CogonyAttackMutation (death_drop)
            # in combat.py — no event needed here.
