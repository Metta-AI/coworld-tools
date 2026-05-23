"""Junction station config and variant."""

from __future__ import annotations

from typing import TYPE_CHECKING
from typing_extensions import override

from cogsguard.core import CogsguardMissionVariant, Deps
from cogsguard.game.terrain import BuildingsVariant
from cogsguard.variants import ResolvedDeps
from mettagrid.config.mettagrid_config import GridObjectConfig, MettaGridConfig

if TYPE_CHECKING:
    from cogsguard.missions.mission import CvCMission


class JunctionVariant(CogsguardMissionVariant):
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
    def modify_env(self, mission: CvCMission, env: MettaGridConfig) -> None:
        env.game.objects["junction"] = GridObjectConfig(name="junction")
