"""Among Us winner declaration mechanics."""

from __future__ import annotations

from typing import cast

from cogames.core import CoGameMissionVariant, Deps
from amongcogs.constants import (
    ALIVE_RESOURCE,
    CRITICAL_TIMER_RESOURCE,
    FORCE_ROLE_ASSIGN_STEP,
    ROLE_CREW,
    ROLE_IMPOSTOR,
    STATION_SABOTAGED_TAG,
    SYSTEM_OXYGEN_TAG,
    SYSTEM_REACTOR_TAG,
    WIN_REWARD_RESOURCE,
    crew_task_goal_for_lobby,
)
from amongcogs.game.meetings import MeetingsVariant
from amongcogs.game.station_events import StationEventsVariant
from mettagrid.config.event_config import EventConfig, periodic
from mettagrid.config.filter import GameValueFilter, HandlerTarget, hasTag, isNot, targetHas
from mettagrid.config.game_value import num, stat, weighted_sum
from mettagrid.config.handler_config import queryDelta
from mettagrid.config.mettagrid_config import MettaGridConfig
from mettagrid.config.mutation.stats_mutation import logStatToGame
from mettagrid.config.query import query
from mettagrid.config.tag import typeTag


class WinConditionsVariant(CoGameMissionVariant):
    name: str = "win_conditions"
    description: str = "Crew task/elimination wins and impostor parity/critical-sabotage wins."

    def dependencies(self) -> Deps:
        return Deps(required=[StationEventsVariant, MeetingsVariant])

    def modify_env(self, mission, env: MettaGridConfig) -> None:
        num_cogs = cast(int, mission.num_cogs)
        max_steps = env.game.max_steps
        crew_task_goal = crew_task_goal_for_lobby(num_cogs)
        role_resolution_start = FORCE_ROLE_ASSIGN_STEP + 2
        alive_impostors = num(typeTag("agent"), [targetHas({ROLE_IMPOSTOR: 1, ALIVE_RESOURCE: 1})])

        no_winner_declared = isNot(
            GameValueFilter(
                target=HandlerTarget.TARGET,
                value=stat("game.winner_declared"),
                min=1,
            )
        )

        env.game.events["crew_win_check"] = EventConfig(
            name="crew_win_check",
            target_query=query(typeTag("agent")),
            timesteps=periodic(start=1, period=1, end=max_steps),
            filters=[
                GameValueFilter(
                    target=HandlerTarget.TARGET,
                    value=stat("game.crew_tasks_completed"),
                    min=crew_task_goal,
                ),
                no_winner_declared,
            ],
            mutations=[
                queryDelta(query(typeTag("agent"), [targetHas({ROLE_CREW: 1})]), {WIN_REWARD_RESOURCE: 1}),
                logStatToGame("crew_win"),
                logStatToGame("crew_win_tasks"),
                logStatToGame("winner_declared"),
            ],
            max_targets=1,
        )
        env.game.events["crew_win_elimination_check"] = EventConfig(
            name="crew_win_elimination_check",
            target_query=query(typeTag("agent")),
            timesteps=periodic(start=role_resolution_start, period=1, end=max_steps),
            filters=[
                isNot(
                    GameValueFilter(
                        target=HandlerTarget.TARGET,
                        value=num(typeTag("agent"), [targetHas({ROLE_IMPOSTOR: 1, ALIVE_RESOURCE: 1})]),
                        min=1,
                    )
                ),
                GameValueFilter(
                    target=HandlerTarget.TARGET,
                    value=num(typeTag("agent"), [targetHas({ROLE_CREW: 1, ALIVE_RESOURCE: 1})]),
                    min=1,
                ),
                no_winner_declared,
            ],
            mutations=[
                queryDelta(query(typeTag("agent"), [targetHas({ROLE_CREW: 1})]), {WIN_REWARD_RESOURCE: 1}),
                logStatToGame("crew_win"),
                logStatToGame("crew_win_elimination"),
                logStatToGame("winner_declared"),
            ],
            max_targets=1,
        )
        env.game.events["impostor_win_parity_check"] = EventConfig(
            name="impostor_win_parity_check",
            target_query=query(typeTag("agent")),
            timesteps=periodic(start=role_resolution_start, period=1, end=max_steps),
            filters=[
                GameValueFilter(
                    target=HandlerTarget.TARGET,
                    value=num(typeTag("agent"), [targetHas({ROLE_IMPOSTOR: 1, ALIVE_RESOURCE: 1})]),
                    min=1,
                ),
                GameValueFilter(
                    target=HandlerTarget.TARGET,
                    value=weighted_sum(
                        [
                            (1.0, num(typeTag("agent"), [targetHas({ROLE_IMPOSTOR: 1, ALIVE_RESOURCE: 1})])),
                            (-1.0, num(typeTag("agent"), [targetHas({ROLE_CREW: 1, ALIVE_RESOURCE: 1})])),
                        ]
                    ),
                    min=0,
                ),
                no_winner_declared,
            ],
            mutations=[
                queryDelta(query(typeTag("agent"), [targetHas({ROLE_IMPOSTOR: 1})]), {WIN_REWARD_RESOURCE: 1}),
                logStatToGame("impostor_win"),
                logStatToGame("impostor_win_elimination"),
                logStatToGame("winner_declared"),
            ],
            max_targets=1,
        )
        env.game.events["impostor_win_reactor_check"] = EventConfig(
            name="impostor_win_reactor_check",
            target_query=query(SYSTEM_REACTOR_TAG),
            timesteps=periodic(start=1, period=1, end=max_steps),
            filters=[
                hasTag(STATION_SABOTAGED_TAG),
                isNot(targetHas({CRITICAL_TIMER_RESOURCE: 1})),
                no_winner_declared,
            ],
            mutations=[
                queryDelta(query(typeTag("agent"), [targetHas({ROLE_IMPOSTOR: 1})]), {WIN_REWARD_RESOURCE: 1}),
                logStatToGame("impostor_win"),
                logStatToGame("impostor_win_reactor"),
                logStatToGame("winner_declared"),
            ],
            max_targets=1,
        )
        env.game.events["impostor_win_oxygen_check"] = EventConfig(
            name="impostor_win_oxygen_check",
            target_query=query(SYSTEM_OXYGEN_TAG),
            timesteps=periodic(start=1, period=1, end=max_steps),
            filters=[
                hasTag(STATION_SABOTAGED_TAG),
                isNot(targetHas({CRITICAL_TIMER_RESOURCE: 1})),
                no_winner_declared,
            ],
            mutations=[
                queryDelta(query(typeTag("agent"), [targetHas({ROLE_IMPOSTOR: 1})]), {WIN_REWARD_RESOURCE: 1}),
                logStatToGame("impostor_win"),
                logStatToGame("impostor_win_oxygen"),
                logStatToGame("winner_declared"),
            ],
            max_targets=1,
        )
        env.game.events["crew_win_timeout_check"] = EventConfig(
            name="crew_win_timeout_check",
            target_query=query(typeTag("agent")),
            timesteps=[max_steps],
            filters=[
                isNot(
                    GameValueFilter(
                        target=HandlerTarget.TARGET,
                        value=alive_impostors,
                        min=1,
                    )
                ),
                no_winner_declared,
            ],
            mutations=[
                queryDelta(query(typeTag("agent"), [targetHas({ROLE_CREW: 1})]), {WIN_REWARD_RESOURCE: 1}),
                logStatToGame("crew_win"),
                logStatToGame("crew_win_timeout"),
                logStatToGame("winner_declared"),
            ],
            max_targets=1,
        )
        env.game.events["impostor_win_timeout_check"] = EventConfig(
            name="impostor_win_timeout_check",
            target_query=query(typeTag("agent")),
            timesteps=[max_steps],
            filters=[
                GameValueFilter(
                    target=HandlerTarget.TARGET,
                    value=alive_impostors,
                    min=1,
                ),
                no_winner_declared,
            ],
            mutations=[
                queryDelta(query(typeTag("agent"), [targetHas({ROLE_IMPOSTOR: 1})]), {WIN_REWARD_RESOURCE: 1}),
                logStatToGame("impostor_win"),
                logStatToGame("impostor_win_timeout"),
                logStatToGame("winner_declared"),
            ],
            max_targets=1,
        )

        env.game.end_episode_on_game_stats = {"winner_declared": 1}
