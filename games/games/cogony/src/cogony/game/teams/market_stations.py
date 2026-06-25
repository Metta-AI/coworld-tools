"""Per-team market station. Bump to sell elements for creds.

Prices are dynamic: rarest element pays 4 creds, most common pays 1.
Market tracks sales history and recalculates after each transaction.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, override

from mettagrid.cogame.core import CoGameMissionVariant, Deps
from cogony.game.creds import CredsVariant
from cogony.game.elements import ElementsVariant
from cogony.game.teams.team import TeamConfig, TeamVariant
from cogony.terrain import find_arena
from mettagrid.config.handler_config import Handler
from mettagrid.config.mettagrid_config import GridObjectConfig, InventoryConfig, MettaGridConfig, ResourceLimitsConfig
from mettagrid.config.mutation import CogonyMarketMutation
from mettagrid.config.render_config import RenderAsset

if TYPE_CHECKING:
    from cogony.mission import CogonyMission

ELEMENTS = ["carbon", "oxygen", "germanium", "silicon"]
SOLD_RESOURCES = ["sold_carbon", "sold_oxygen", "sold_germanium", "sold_silicon"]

# Initial prices: C=1, O=2, G=3, S=4 (rarest = silicon = most valuable).
INITIAL_PRICES = {"carbon": 1, "oxygen": 2, "germanium": 3, "silicon": 4}


def _market_station(team: TeamConfig) -> GridObjectConfig:
    """Market station: sell all cargo for creds at dynamic prices."""
    key = f"{team.short_name}:market_st"

    limits: dict[str, ResourceLimitsConfig] = {}
    initial: dict[str, int] = {}
    for elem in ELEMENTS:
        limits[elem] = ResourceLimitsConfig(base=10, max=10, resources=[elem])
        initial[elem] = INITIAL_PRICES[elem]
    for sr in SOLD_RESOURCES:
        limits[sr] = ResourceLimitsConfig(base=65535, max=65535, resources=[sr])
        initial[sr] = 0

    return GridObjectConfig(
        name="market_station",
        map_name=key,
        inventory=InventoryConfig(limits=limits, initial=initial),
        on_use_handler=Handler(
            name=f"market_{team.short_name}",
            mutations=[
                CogonyMarketMutation(
                    elements=ELEMENTS,
                    price_resources=ELEMENTS,
                    sold_resources=SOLD_RESOURCES,
                    creds="creds",
                    history_window=10,
                    tax_percent=0,
                ),
            ],
        ),
    )


class TeamMarketStationsVariant(CoGameMissionVariant):
    """Add a market station to every team's compound."""

    name: str = "team_market_stations"
    description: str = "Per-team market: sell elements for creds (dynamic prices)."

    @override
    def dependencies(self) -> Deps:
        return Deps(required=[TeamVariant, CredsVariant, ElementsVariant])

    @override
    def modify_env(self, mission: CogonyMission, env: MettaGridConfig) -> None:
        # Register sold-tracking resources (elements already registered by ElementsVariant).
        for r in SOLD_RESOURCES:
            env.game.add_resource(r)

        team_v = mission.required_variant(TeamVariant)
        arena = find_arena(env.game.map_builder)
        station_keys: list[str] = []
        for team in team_v.teams.values():
            cfg = _market_station(team)
            key = cfg.map_name
            env.game.objects.setdefault(key, cfg)
            env.game.render.symbols[key] = "🪙"
            env.game.render.assets[key] = [RenderAsset(asset="market_station")]
            station_keys.append(key)

        if arena is not None:
            existing = set(arena.hub.stations)
            arena.hub.stations.extend(k for k in station_keys if k not in existing)
