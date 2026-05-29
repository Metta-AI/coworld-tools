"""Timing stress variants for Werewolf/Mafia phase cadence."""

from __future__ import annotations

from mettagrid.cogame.core import CoGameMissionVariant, Deps
from werecog.defaults import DEFAULT_DAY_STEPS, DEFAULT_NIGHT_STEPS
from werecog.variants.meetings import MeetingsVariant

SHORT_NIGHT_STEPS = max(1, DEFAULT_NIGHT_STEPS // 2)
LONG_NIGHT_STEPS = DEFAULT_NIGHT_STEPS * 2
SHORT_DAY_STEPS = max(1, DEFAULT_DAY_STEPS // 2)


class ShortNightVariant(CoGameMissionVariant):
    name: str = "short_night"
    description: str = "Shorten the werewolf hunt window for timing stress tests."

    def dependencies(self) -> Deps:
        return Deps(required=[MeetingsVariant])

    def modify_mission(self, mission) -> None:
        mission.night_steps = SHORT_NIGHT_STEPS


class LongNightVariant(CoGameMissionVariant):
    name: str = "long_night"
    description: str = "Lengthen the werewolf hunt window for timing stress tests."

    def dependencies(self) -> Deps:
        return Deps(required=[MeetingsVariant])

    def modify_mission(self, mission) -> None:
        mission.night_steps = LONG_NIGHT_STEPS


class ShortDayVariant(CoGameMissionVariant):
    name: str = "short_day"
    description: str = "Tighten the daytime accusation window for timing stress tests."

    def dependencies(self) -> Deps:
        return Deps(required=[MeetingsVariant])

    def modify_mission(self, mission) -> None:
        mission.day_steps = SHORT_DAY_STEPS
