"""Hidden timing stress variants for Among Us."""

from __future__ import annotations

from mettagrid.cogame.core import CoGameMissionVariant, Deps
from amongcogs.defaults import (
    DEFAULT_INITIAL_KILL_COOLDOWN_STEPS,
    DEFAULT_KILL_COOLDOWN_STEPS,
    DEFAULT_LIGHTS_SABOTAGE_TIMER_STEPS,
    DEFAULT_MEETING_DURATION_STEPS,
    DEFAULT_OXYGEN_SABOTAGE_TIMER_STEPS,
    DEFAULT_REACTOR_SABOTAGE_TIMER_STEPS,
)
from amongcogs.game.combat import CombatVariant
from amongcogs.game.meetings import MeetingsVariant
from amongcogs.game.station_events import StationEventsVariant

SHORT_MEETING_DURATION_STEPS = max(1, DEFAULT_MEETING_DURATION_STEPS // 2)
FAST_KILL_COOLDOWN_STEPS = max(1, DEFAULT_KILL_COOLDOWN_STEPS // 2)
FAST_INITIAL_KILL_COOLDOWN_STEPS = max(1, DEFAULT_INITIAL_KILL_COOLDOWN_STEPS // 2)
RAPID_REACTOR_SABOTAGE_TIMER_STEPS = max(1, DEFAULT_REACTOR_SABOTAGE_TIMER_STEPS // 2)
RAPID_OXYGEN_SABOTAGE_TIMER_STEPS = max(1, DEFAULT_OXYGEN_SABOTAGE_TIMER_STEPS // 2)
RAPID_LIGHTS_SABOTAGE_TIMER_STEPS = max(1, DEFAULT_LIGHTS_SABOTAGE_TIMER_STEPS // 2)


class ShortMeetingVariant(CoGameMissionVariant):
    name: str = "short_meeting"
    description: str = "Shorten the meeting window for timing stress tests."

    def dependencies(self) -> Deps:
        return Deps(required=[MeetingsVariant])

    def modify_mission(self, mission) -> None:
        mission.meeting_duration_steps = SHORT_MEETING_DURATION_STEPS


class FastKillCooldownVariant(CoGameMissionVariant):
    name: str = "fast_kill_cooldown"
    description: str = "Tighten impostor kill cooldowns for combat stress tests."

    def dependencies(self) -> Deps:
        return Deps(required=[CombatVariant])

    def modify_mission(self, mission) -> None:
        mission.initial_kill_cooldown_steps = FAST_INITIAL_KILL_COOLDOWN_STEPS
        mission.kill_cooldown_steps = FAST_KILL_COOLDOWN_STEPS


class RapidCriticalVariant(CoGameMissionVariant):
    name: str = "rapid_critical"
    description: str = "Shorten reactor, oxygen, and lights sabotage timers for readiness stress tests."

    def dependencies(self) -> Deps:
        return Deps(required=[StationEventsVariant])

    def modify_mission(self, mission) -> None:
        mission.reactor_sabotage_timer_steps = RAPID_REACTOR_SABOTAGE_TIMER_STEPS
        mission.oxygen_sabotage_timer_steps = RAPID_OXYGEN_SABOTAGE_TIMER_STEPS
        mission.lights_sabotage_timer_steps = RAPID_LIGHTS_SABOTAGE_TIMER_STEPS
