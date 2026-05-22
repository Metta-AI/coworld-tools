from __future__ import annotations

from cogsguard.core import CogsguardMissionVariant
from cogsguard.game.cargo import CargoLimitVariant
from cogsguard.game.clear_vibes import ClearVibesVariant
from cogsguard.game.clips import (
    AdaptiveClipsVariant,
    AngryClipsVariant,
    ClipsVariant,
    GreedyClipsVariant,
    NoClipsVariant,
)
from cogsguard.game.damage import DamageVariant
from cogsguard.game.days import DaysVariant
from cogsguard.game.endless import EndlessVariant
from cogsguard.game.energy import EnergyVariant
from cogsguard.game.extractors import CvCExtractorConfig, ExtractorsVariant
from cogsguard.game.forced_role_vibes import ForcedRoleVibesVariant
from cogsguard.game.gear import GearVariant
from cogsguard.game.gear_stations import GearStationsVariant, WildGearStationsVariant
from cogsguard.game.heart import HeartVariant
from cogsguard.game.junction import JunctionVariant
from cogsguard.game.multi_team import GEAR, MultiTeamVariant
from cogsguard.game.roles.aligner import AlignerVariant
from cogsguard.game.roles.miner import MinerVariant
from cogsguard.game.roles.scout import ScoutVariant
from cogsguard.game.roles.scrambler import ScramblerVariant
from cogsguard.game.solar import SolarVariant
from cogsguard.game.talk import TalkVariant
from cogsguard.game.teams import TeamVariant
from cogsguard.game.teams.four_score import FourScoreVariant
from cogsguard.game.teams.gear_stations import TeamGearStationsVariant
from cogsguard.game.teams.hub import TeamHubVariant
from cogsguard.game.teams.hub_observations import HubObservationsVariant
from cogsguard.game.teams.junction import TeamJunctionVariant
from cogsguard.game.teams.junction_deposit import JunctionDepositVariant
from cogsguard.game.terrain import (
    BaseCompoundVariant,
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
from cogsguard.game.territory import DamageStrangersVariant, HealTeamVariant, TerritoryVariant
from cogsguard.game.territory import TerritoryVariant as JunctionNetVariant
from cogsguard.game.vibes import NoVibesVariant, VibesVariant
from cogsguard.missions.terrain import MachinaTerrainVariant

__all__ = [
    "AdaptiveClipsVariant",
    "AlignerVariant",
    "AngryClipsVariant",
    "BaseCompoundVariant",
    "CargoLimitVariant",
    "ClearVibesVariant",
    "CavesVariant",
    "CityVariant",
    "ClipsVariant",
    "NoClipsVariant",
    "CvCExtractorConfig",
    "DamageStrangersVariant",
    "DamageVariant",
    "DaysVariant",
    "DesertVariant",
    "DistantResourcesVariant",
    "EmptyBaseVariant",
    "EndlessVariant",
    "EnergyVariant",
    "ForcedRoleVibesVariant",
    "ForestVariant",
    "FourScoreVariant",
    "MachinaTerrainVariant",
    "GreedyClipsVariant",
    "GEAR",
    "GearStationsVariant",
    "GearVariant",
    "HealTeamVariant",
    "HeartVariant",
    "HubObservationsVariant",
    "JunctionDepositVariant",
    "JunctionNetVariant",
    "JunctionVariant",
    "MinerVariant",
    "MultiTeamVariant",
    "NoVibesVariant",
    "QuadrantBuildingsVariant",
    "RandomizeSpawnsVariant",
    "ScoutVariant",
    "ScramblerVariant",
    "Small50Variant",
    "SolarVariant",
    "TeamGearStationsVariant",
    "TeamHubVariant",
    "TeamJunctionVariant",
    "TeamVariant",
    "TerritoryVariant",
    "TalkVariant",
    "VibesVariant",
    "WildGearStationsVariant",
]


def _get_tutorial_variants() -> list[CogsguardMissionVariant]:
    # Lazy import to break circular dependency:
    # game/__init__ -> missions.tutorial -> missions.machina_1 -> game.cargo -> game/__init__
    from cogsguard.missions.tutorial import (  # noqa: PLC0415
        AlignerRewardsVariant,
        MinerRewardsVariant,
        OverrunVariant,
        ScoutRewardsVariant,
        ScramblerRewardsVariant,
    )

    return [
        AlignerRewardsVariant(),
        MinerRewardsVariant(),
        ScoutRewardsVariant(),
        ScramblerRewardsVariant(),
        OverrunVariant(),
    ]


VARIANTS: list[CogsguardMissionVariant] = [
    AlignerVariant(),
    CargoLimitVariant(),
    CavesVariant(),
    CityVariant(),
    AngryClipsVariant(),
    ClipsVariant(),
    GreedyClipsVariant(),
    NoClipsVariant(),
    AdaptiveClipsVariant(),
    DamageStrangersVariant(),
    DamageVariant(),
    DaysVariant(),
    DesertVariant(),
    EmptyBaseVariant(),
    EndlessVariant(),
    EnergyVariant(),
    ExtractorsVariant(),
    ForcedRoleVibesVariant(),
    ForestVariant(),
    FourScoreVariant(),
    MachinaTerrainVariant(),
    GearStationsVariant(),
    HealTeamVariant(),
    HeartVariant(),
    HubObservationsVariant(),
    JunctionDepositVariant(),
    JunctionVariant(),
    MinerVariant(),
    MultiTeamVariant(),
    QuadrantBuildingsVariant(),
    RandomizeSpawnsVariant(),
    ScoutVariant(),
    ScramblerVariant(),
    Small50Variant(),
    SolarVariant(),
    TeamGearStationsVariant(),
    TeamHubVariant(),
    TeamJunctionVariant(),
    TeamVariant(),
    TerritoryVariant(),
    TalkVariant(),
    ClearVibesVariant(),
    VibesVariant(),
    NoVibesVariant(),
    WildGearStationsVariant(),
]


def _get_all_variants() -> list[CogsguardMissionVariant]:
    return list(VARIANTS) + _get_tutorial_variants()
