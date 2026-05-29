"""Among Us observability mechanics."""

from __future__ import annotations

from mettagrid.cogame.core import CoGameMissionVariant, Deps
from amongcogs.game.meetings import MeetingsVariant
from amongcogs.game.station_events import StationEventsVariant
from mettagrid.config.mettagrid_config import MettaGridConfig


class MetricsVariant(CoGameMissionVariant):
    name: str = "metrics"
    description: str = "Headless audit marker variant for observability slices."

    def dependencies(self) -> Deps:
        return Deps(required=[StationEventsVariant, MeetingsVariant])

    def modify_env(self, mission, env: MettaGridConfig) -> None:
        del mission, env
