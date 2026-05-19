from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Generic, Literal, TypeVar
from typing_extensions import override

from pydantic import Field

from cogames.core import CoGameMissionVariant, Deps

if TYPE_CHECKING:
    from cogsguard.missions.mission import CvCMission
from mettagrid.config.mettagrid_config import MettaGridConfig
from mettagrid.mapgen.mapgen import MapGen, MapGenConfig
from mettagrid.mapgen.scenes.biome_arena import (
    BiomeArena,
    BiomeArenaConfig,
    SequentialBiomeArena,
    SequentialBiomeArenaConfig,
    find_biome_arena,
)
from mettagrid.mapgen.scenes.compound import CompoundConfig
from mettagrid.mapgen.scenes.ensure_hub_reachable_junction import (
    EnsureHubReachableJunction,
    EnsureHubReachableJunctionConfig,
)
from mettagrid.mapgen.scenes.map_corner_placements import MapCornerPlacements, MapCornerPlacementsConfig
from mettagrid.mapgen.scenes.perimeter_placements import PerimeterPlacements, PerimeterPlacementsConfig
from mettagrid.mapgen.scenes.random_transform import RandomTransform, RandomTransformConfig

# Back-compat aliases. The scenes were moved to mettagrid and renamed
# Machina* → Biome*. Existing cogsguard missions, maps, and job specs that
# reference these names (either by Python import or by FQCN string in JSON
# via mettagrid's type-tagged serialization) keep working.
MachinaArena = BiomeArena
MachinaArenaConfig = BiomeArenaConfig
SequentialMachinaArena = SequentialBiomeArena
SequentialMachinaArenaConfig = SequentialBiomeArenaConfig
find_machina_arena = find_biome_arena

__all__ = [
    "BiomeArena",
    "BiomeArenaConfig",
    "SequentialBiomeArena",
    "SequentialBiomeArenaConfig",
    "MachinaArena",
    "MachinaArenaConfig",
    "SequentialMachinaArena",
    "SequentialMachinaArenaConfig",
    "MapCornerPlacements",
    "MapCornerPlacementsConfig",
    "PerimeterPlacements",
    "PerimeterPlacementsConfig",
    "EnsureHubReachableJunction",
    "EnsureHubReachableJunctionConfig",
    "RandomTransform",
    "RandomTransformConfig",
    "find_biome_arena",
    "find_machina_arena",
    "EnvNodeVariant",
    "MapGenVariant",
    "MapSeedVariant",
    "MachinaArenaVariant",
    "SequentialMachinaArenaVariant",
    "MachinaTerrainVariant",
]


T = TypeVar("T")


class EnvNodeVariant(CoGameMissionVariant, ABC, Generic[T]):
    @abstractmethod
    def extract_node(self, env: MettaGridConfig) -> T: ...

    @abstractmethod
    def modify_node(self, node: T): ...

    @override
    def modify_env(self, mission, env) -> None:
        node = self.extract_node(env)
        self.modify_node(node)


class MapGenVariant(EnvNodeVariant[MapGenConfig]):
    @classmethod
    def extract_node(cls, env: MettaGridConfig) -> MapGenConfig:
        map_builder = env.game.map_builder
        if not isinstance(map_builder, MapGen.Config):
            raise TypeError("MapGenConfigVariant can only be applied to MapGen.Config builders")
        return map_builder


class MapSeedVariant(MapGenVariant):
    """Variant that sets the MapGen seed for deterministic map generation.

    This is primarily meant for programmatic control from experiments / pipelines:

        mission = base_mission.with_variants([MapSeedVariant(seed=1234)])
        env_cfg = mission.make_env()

    """

    name: str = "map_seed"
    description: str = "Set MapGen seed for deterministic map generation."
    seed: int

    @override
    def modify_node(self, node: MapGenConfig) -> None:
        node.seed = int(self.seed)


class MachinaArenaVariant(EnvNodeVariant[BiomeArenaConfig]):
    def compat(self, mission: CvCMission) -> bool:
        env = mission.make_env()
        return isinstance(env.game.map_builder, MapGen.Config) and isinstance(
            env.game.map_builder.instance, BiomeArena.Config
        )

    @classmethod
    def extract_node(cls, env: MettaGridConfig) -> BiomeArenaConfig:
        assert isinstance(env.game.map_builder, MapGen.Config)
        assert isinstance(env.game.map_builder.instance, BiomeArena.Config)
        return env.game.map_builder.instance


class SequentialMachinaArenaVariant(EnvNodeVariant[SequentialBiomeArenaConfig]):
    def compat(self, mission: CvCMission) -> bool:
        env = mission.make_env()
        return isinstance(env.game.map_builder, MapGen.Config) and isinstance(
            env.game.map_builder.instance, SequentialBiomeArena.Config
        )

    @classmethod
    def extract_node(cls, env: MettaGridConfig) -> SequentialBiomeArenaConfig:
        assert isinstance(env.game.map_builder, MapGen.Config)
        assert isinstance(env.game.map_builder.instance, SequentialBiomeArena.Config)
        return env.game.map_builder.instance


CompoundLocation = Literal["center", "nw", "ne", "sw", "se"]


class MachinaTerrainVariant(CoGameMissionVariant):
    """Configure map size and compound placements for a machina arena.

    Default: single compound in the center (standard machina1).
    Override compounds to place multiple compounds at corners.
    """

    name: str = "machina_terrain"
    description: str = "Map size and compound layout."
    map_width: int = Field(default=88)
    map_height: int = Field(default=88)
    building_coverage_scale: float = Field(default=1.0)
    compound_placements: list[tuple[CompoundLocation, CompoundConfig]] = Field(default_factory=list)

    @override
    def dependencies(self) -> Deps:
        from cogsguard.game.teams.gear_stations import TeamGearStationsVariant  # noqa: PLC0415
        from cogsguard.game.teams.team import TeamVariant  # noqa: PLC0415

        return Deps(required=[TeamVariant], optional=[TeamGearStationsVariant])

    @override
    def modify_env(self, mission, env: MettaGridConfig) -> None:
        arena = find_biome_arena(env.game.map_builder)
        if arena is None:
            return

        # Resize map.
        map_builder = env.game.map_builder
        if isinstance(map_builder, MapGen.Config):
            map_builder.width = self.map_width
            map_builder.height = self.map_height
            if self.compound_placements:
                map_builder.set_team_by_instance = True

        # Scale building density.
        if self.building_coverage_scale != 1.0:
            arena.building_coverage = arena.building_coverage * self.building_coverage_scale

        # Set compound placements. When empty, the arena uses its default single hub.
        if self.compound_placements:
            hub_stations = list(arena.hub.stations)
            placements: list[tuple[str, CompoundConfig]] = []
            for loc, compound in self.compound_placements:
                compound = compound.model_copy(deep=True)
                prefix = compound.hub_object.split(":")[0] + ":"
                compound.stations = [s for s in hub_stations if s.startswith(prefix)]
                placements.append((loc, compound))
            arena.compounds = placements
