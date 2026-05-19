from __future__ import annotations

from cogames.core import CoGameMissionVariant

from cogony.game.cargo import CargoLimitVariant
from cogony.game.channels import ChannelsVariant
from cogony.game.coherence import CoherenceVariant
from cogony.game.combat import CombatVariant
from cogony.game.creds import CredsVariant
from cogony.game.datacenter import DatacenterVariant
from cogony.game.elements import ElementsVariant
from cogony.game.extractors import ExtractorConfig, ExtractorsVariant
from cogony.game.heart import HeartVariant
from cogony.game.junction import JunctionVariant
from cogony.game.observatory import ObservatoryVariant
from cogony.game.teams import TeamVariant
from cogony.game.teams.cogony import CogonyVariant
from cogony.game.teams.gear_stations import TeamGearStationsVariant
from cogony.game.teams.heart_station import TeamHeartStationVariant
from cogony.game.teams.market_stations import TeamMarketStationsVariant
from cogony.game.teams.hub import TeamHubVariant
from cogony.game.teams.junction import TeamJunctionVariant
from cogony.game.terrain import (
    BaseCompoundVariant,
    BuildingsVariant,
    CavesVariant,
    CityVariant,
    DesertVariant,
    DistantResourcesVariant,
    EmptyBaseVariant,
    ForestVariant,
    QuadrantBuildingsVariant,
    RandomizeSpawnsVariant,
    Small50Variant,
)
from cogony.game.territory import HealTeamVariant, TerritoryVariant
from cogony.game.trap import TrapVariant
from cogony.game.vibes import NoVibesVariant, VibesVariant
from cogony.terrain import TerrainVariant

__all__ = [
    "BaseCompoundVariant",
    "BuildingsVariant",
    "CargoLimitVariant",
    "ChannelsVariant",
    "CoherenceVariant",
    "CavesVariant",
    "CityVariant",
    "CogonyVariant",
    "CombatVariant",
    "CredsVariant",
    "DatacenterVariant",
    "DesertVariant",
    "DistantResourcesVariant",
    "ElementsVariant",
    "EmptyBaseVariant",
    "ExtractorConfig",
    "ExtractorsVariant",
    "ForestVariant",
    "HealTeamVariant",
    "HeartVariant",
    "JunctionVariant",
    "NoVibesVariant",
    "ObservatoryVariant",
    "QuadrantBuildingsVariant",
    "RandomizeSpawnsVariant",
    "Small50Variant",
    "TeamGearStationsVariant",
    "TeamHeartStationVariant",
    "TeamHubVariant",
    "TeamJunctionVariant",
    "TeamMarketStationsVariant",
    "TeamVariant",
    "TerrainVariant",
    "TerritoryVariant",
    "TrapVariant",
    "VibesVariant",
]


VARIANTS: list[CoGameMissionVariant] = [
    CargoLimitVariant(),
    CavesVariant(),
    ChannelsVariant(),
    CoherenceVariant(),
    CombatVariant(),
    CityVariant(),
    CogonyVariant(),
    CredsVariant(),
    DatacenterVariant(),
    DesertVariant(),
    DistantResourcesVariant(),
    ElementsVariant(),
    EmptyBaseVariant(),
    ExtractorsVariant(),
    ForestVariant(),
    HealTeamVariant(),
    HeartVariant(),
    JunctionVariant(),
    ObservatoryVariant(),
    TerrainVariant(),
    NoVibesVariant(),
    QuadrantBuildingsVariant(),
    RandomizeSpawnsVariant(),
    Small50Variant(),
    TeamGearStationsVariant(),
    TeamHeartStationVariant(),
    TeamHubVariant(),
    TeamJunctionVariant(),
    TeamMarketStationsVariant(),
    TeamVariant(),
    TerritoryVariant(),
    TrapVariant(),
    VibesVariant(),
]


def _get_all_variants() -> list[CoGameMissionVariant]:
    return list(VARIANTS)
