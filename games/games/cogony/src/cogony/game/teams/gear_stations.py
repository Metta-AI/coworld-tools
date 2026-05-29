"""Per-team gear stations (RULES.md section 2).

9 gear types (each +1 to a combat/utility stat):
  Attack:   core_a (Core), os_a (OS), gen_a (Generator), storage_a (Storage)
  Defense:  core_d (Core), os_d (OS), gen_d (Generator), storage_d (Storage)
  Utility:  patch (Heal +1)

Gear cost scales: 10 * gear_held creds per purchase.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, override

from mettagrid.cogame.core import CoGameMissionVariant, Deps
from cogony.game.creds import CredsVariant
from cogony.game.teams.team import TeamConfig, TeamVariant
from cogony.terrain import find_arena
from mettagrid.config.filter import GameValueFilter, HandlerTarget
from mettagrid.config.game_value import ExpGameValue, InventoryValue, Scope, SumGameValue
from mettagrid.config.handler_config import Handler, updateActor, updateTarget
from mettagrid.config.mettagrid_config import GridObjectConfig, InventoryConfig, MettaGridConfig, ResourceLimitsConfig
from mettagrid.config.mutation.game_value_mutation import SetGameValueMutation
from mettagrid.config.mutation.mutation import EntityTarget
from mettagrid.config.render_config import RenderAsset

if TYPE_CHECKING:
    from cogony.mission import CogonyMission

GEAR_COST_BASE = 2
GEAR_COST_OFFSET = 2

# All 9 gear resource names (cargo removed — no cargo station).
GEAR_NAMES: list[str] = [
    "core_a", "os_a", "gen_a", "storage_a",    # Attack
    "core_d", "os_d", "gen_d", "storage_d",    # Defense
]

# Per-subsystem gear grouping (subsystem_name -> [attack, defense]).
SUBSYSTEM_GEAR: dict[str, list[str]] = {
    "core": ["core_a", "core_d"],
    "os": ["os_a", "os_d"],
    "generator": ["gen_a", "gen_d"],
    "storage": ["storage_a", "storage_d"],
}


def _gear_used_sum() -> SumGameValue:
    """GameValue that sums all 10 gear inventory resources on the actor."""
    return SumGameValue(
        values=[InventoryValue(item=g, scope=Scope.AGENT) for g in GEAR_NAMES],
        weights=[1.0] * len(GEAR_NAMES),
    )


def _gear_cost() -> ExpGameValue:
    """Dynamic gear cost: 2^(4 + gear_held)."""
    from mettagrid.config.game_value import ConstValue
    exponent = SumGameValue(
        values=[ConstValue(value=float(GEAR_COST_OFFSET)), _gear_used_sum()],
    )
    return ExpGameValue(base=float(GEAR_COST_BASE), exponent=exponent)


def _gear_station(
    team: TeamConfig, gear_name: str,
) -> tuple[str, GridObjectConfig]:
    """Factory for a single gear station selling *gear_name*.

    Cost = 2^(4 + gear_held). With 0 gear: 2^4=16. With 1: 2^5=32, etc.
    """
    key = f"{team.short_name}:{gear_name}_st"
    cost = _gear_cost()
    negative_cost = SumGameValue(values=[cost], weights=[-1.0])

    cfg = GridObjectConfig(
        name=f"{gear_name}_station",
        map_name=key,
        inventory=InventoryConfig(
            limits={
                "sold": ResourceLimitsConfig(base=65535, max=65535, resources=["sold"]),
            },
            initial={"creds": 4, gear_name: 1, "sold": 0},
        ),
        on_use_handler=Handler(
            name=f"buy_{gear_name}_{team.short_name}",
            filters=[
                GameValueFilter(
                    target=HandlerTarget.ACTOR,
                    value=InventoryValue(item="creds", scope=Scope.AGENT),
                    min=cost,
                ),
            ],
            mutations=[
                SetGameValueMutation(
                    value=InventoryValue(item="creds", scope=Scope.AGENT),
                    target=EntityTarget.ACTOR,
                    source=negative_cost,
                ),
                updateActor({gear_name: 1}),
                updateTarget({"sold": 1}),
            ],
        ),
    )
    return key, cfg


class TeamGearStationsVariant(CoGameMissionVariant):
    """Add gear stations to every team compound (one per gear type)."""

    name: str = "team_gear_stations"
    description: str = "Per-team gear stations (one per gear type) + slot station."

    @override
    def dependencies(self) -> Deps:
        return Deps(required=[TeamVariant, CredsVariant])

    @override
    def modify_env(self, mission: CogonyMission, env: MettaGridConfig) -> None:
        team_v = mission.required_variant(TeamVariant)
        arena = find_arena(env.game.map_builder)
        station_keys: list[str] = []
        env.game.add_resource("sold")

        for team in team_v.teams.values():
            for gear_name in GEAR_NAMES:
                key, cfg = _gear_station(team, gear_name)
                env.game.objects.setdefault(key, cfg)
                env.game.render.symbols[key] = "⚙"
                env.game.render.assets[key] = [RenderAsset(asset=gear_name)]
                station_keys.append(key)

        if arena is not None:
            existing = set(arena.hub.stations)
            arena.hub.stations.extend(k for k in station_keys if k not in existing)
