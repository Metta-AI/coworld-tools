"""Goal classes for Cogas policy."""

from .aligner import AlignJunctionGoal, GetAlignerGearGoal
from .gear import GetGearGoal
from .miner import DepositCargoGoal, GetMinerGearGoal, MineResourceGoal, PickResourceGoal
from .scout import ExploreGoal, GetScoutGearGoal
from .scrambler import GetScramblerGearGoal, ScrambleJunctionGoal
from .shared import GetHeartsGoal
from .stem import SelectRoleGoal
from .survive import SurviveGoal

__all__ = [
    "SurviveGoal",
    "GetGearGoal",
    "GetAlignerGearGoal",
    "GetMinerGearGoal",
    "GetScoutGearGoal",
    "GetScramblerGearGoal",
    "GetHeartsGoal",
    "PickResourceGoal",
    "DepositCargoGoal",
    "MineResourceGoal",
    "ExploreGoal",
    "AlignJunctionGoal",
    "ScrambleJunctionGoal",
    "SelectRoleGoal",
]
