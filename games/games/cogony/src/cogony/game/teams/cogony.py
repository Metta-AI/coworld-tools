"""Four Corners variant: 1-4 teams in corner compounds.

Compound layout (relative to hub center):

    NW: core_a, core_d
    NE: os_a, os_d
    SW: gen_a, gen_d
    SE: storage_a, storage_d
    Above hub: heart (altar)
    Below hub: market

Extractors are NOT in the compound -- they spawn in the wild.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, override

from pydantic import Field

from mettagrid.cogame.core import CoGameMissionVariant, Deps
from mettagrid.cogame.variants import ResolvedDeps
from cogony.base import BaseVariant
from cogony.game.datacenter import DatacenterVariant
from cogony.game.extractors import ExtractorsVariant
from cogony.game.observatory import ObservatoryVariant
from cogony.game.teams.gear_stations import SUBSYSTEM_GEAR
from cogony.game.teams.team import TeamConfig, TeamVariant
from cogony.terrain import CompoundLocation, TerrainVariant
from mettagrid.config.game_value import SumGameValue, num_tagged, val, weighted_sum
from mettagrid.config.handler_config import Handler, allOf
from mettagrid.config.mettagrid_config import MettaGridConfig
from mettagrid.config.mutation import logStatToGame
from mettagrid.config.render_config import RenderAsset
from mettagrid.mapgen.scenes.compound import CompoundConfig

if TYPE_CHECKING:
    from cogony.mission import CogonyMission

TEAM_COLORS = ["red", "blue", "green", "yellow"]
CORNER_LOCS: list[CompoundLocation] = ["nw", "ne", "sw", "se"]


_STATION_OFFSETS: dict[str, tuple[int, int]] = {
    # Attack cross (top-right, 3x3 plaza centered at 7,-7).
    # Buildings at midpoints of each side.
    "core_a":    (7, -9),   # top
    "storage_a": (7, -5),   # bottom
    "os_a":      (5, -7),   # left
    "gen_a":     (9, -7),   # right
    # Defense cross (bottom-right, 3x3 plaza centered at 7,7).
    "core_d":    (7, 5),    # top
    "storage_d": (7, 9),    # bottom
    "os_d":      (5, 7),    # left
    "gen_d":     (9, 7),    # right
    # Stake buy/sell near hub. Market below hub.
    "stake_buy":  (-2, -3),
    "stake_sell": (2, -3),
    "market":     (0, 3),
}


def _build_station_layout(team_short: str) -> tuple[list[str], list[tuple[int, int]]]:
    """Build the station names and offsets for one compound.

    The names/offsets are just placeholders — TerrainVariant.modify_env
    replaces the stations list with arena.hub.stations filtered by team
    prefix (line 922 of terrain.py). So the offsets must be keyed by
    station suffix to survive the reorder.
    """
    names: list[str] = []
    offsets: list[tuple[int, int]] = []
    for suffix, offset in _STATION_OFFSETS.items():
        names.append(f"{team_short}:{suffix}_st")
        offsets.append(offset)
    return names, offsets


class CogonyVariant(CoGameMissionVariant):
    """Set up 1-4 teams with corner compounds."""

    name: str = "cogony"
    description: str = "Multi-team corner compounds."
    num_teams: int = Field(default=4, ge=1, le=4)

    @override
    def dependencies(self) -> Deps:
        return Deps(
            required=[
                BaseVariant,
                DatacenterVariant,
                ObservatoryVariant,
                TeamVariant,
                TerrainVariant,
                ExtractorsVariant,
            ]
        )

    @override
    def configure(self, deps: ResolvedDeps) -> None:
        team_v = deps.required(TeamVariant)
        team_v.teams = {
            f"cogs_{TEAM_COLORS[i]}": TeamConfig(
                name=f"cogs_{TEAM_COLORS[i]}",
                short_name=TEAM_COLORS[i][:3],
            )
            for i in range(self.num_teams)
        }

        deps.required(ExtractorsVariant).initial_amount = 100

        terrain = deps.required(TerrainVariant)
        terrain.map_width = 180
        terrain.map_height = 180
        terrain.building_coverage_scale = 1.5
        terrain.cave_border = 42

        terrain.compound_placements = []
        for i in range(self.num_teams):
            short = TEAM_COLORS[i][:3]
            stations, offsets = _build_station_layout(short)
            terrain.compound_placements.append((
                CORNER_LOCS[i],
                CompoundConfig(
                    hub_object=f"{short}:hub",
                    hub_width=21,
                    hub_height=21,
                    corner_bundle="none",
                    cross_objects=["", "", "", ""],
                    cross_distance=4,
                    outer_clearance=1,
                    spawn_symbol=f"agent.team_{i}",
                    stations=stations,
                    station_offsets=offsets,
                ),
            ))

    @override
    def modify_env(self, mission: "CogonyMission", env: MettaGridConfig) -> None:
        from cogony.terrain import find_arena  # noqa: PLC0415

        arena = find_arena(env.game.map_builder)
        if arena is not None:
            arena.dungeon_weights = {"maze": 1.0, "radial": 0.5}
            arena.map_edge_midpoint_objects = [
                "datacenter", "datacenter", "datacenter", "datacenter",
            ]
            arena.map_center_objects.extend([
                "observatory", "observatory", "observatory", "observatory",
            ])

        team_v = mission.required_variant(TeamVariant)
        all_teams = list(team_v.teams.values())
        for obj_type in ("observatory", "datacenter"):
            env.game.render.assets[obj_type] = [
                *[RenderAsset(asset=f"{obj_type}.working", tags=[t.team_tag()]) for t in all_teams],
                RenderAsset(asset=obj_type),
            ]

        seen_team_names: set[str] = set()
        held_junction_stats: list[SumGameValue] = []

        for agent in env.game.agents:
            team_name = team_v.team_name(agent.team_id)
            assert team_name is not None, f"agent team_id={agent.team_id} has no team name"
            if team_name in seen_team_names:
                continue
            held_junction_stats.append(SumGameValue(values=[num_tagged(f"net:{team_name}"), val(-1.0)]))
            seen_team_names.add(team_name)

        if held_junction_stats:
            avg_held_junctions = weighted_sum(
                [(1.0 / len(held_junction_stats), held_stat) for held_stat in held_junction_stats]
            )
            handler = Handler(
                name="aligned_junction_held_cogony_avg",
                mutations=[logStatToGame("cogony/aligned.junction.held.avg", source=avg_held_junctions)],
            )
            env.game.on_tick = allOf([env.game.on_tick, handler])
