"""Among Us full mechanic bundle variant."""

from __future__ import annotations

from mettagrid.cogame.core import CoGameMissionVariant, Deps
from amongcogs.game.combat import CombatVariant
from amongcogs.game.meetings import MeetingsVariant
from amongcogs.game.metrics import MetricsVariant
from amongcogs.game.roles import RolesVariant
from amongcogs.game.station_events import StationEventsVariant
from amongcogs.game.tasks import TasksVariant
from amongcogs.game.vents import VentsVariant
from amongcogs.game.win_conditions import WinConditionsVariant


class FullVariant(CoGameMissionVariant):
    name: str = "full"
    description: str = "Complete Among Us mechanics bundle."

    def dependencies(self) -> Deps:
        return Deps(
            required=[
                RolesVariant,
                TasksVariant,
                VentsVariant,
                StationEventsVariant,
                CombatVariant,
                MeetingsVariant,
                WinConditionsVariant,
                MetricsVariant,
            ]
        )
