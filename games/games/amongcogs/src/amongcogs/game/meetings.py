"""Among Us report/meeting/vote mechanics."""

from __future__ import annotations

from cogames.core import CoGameMissionVariant, Deps
from amongcogs.constants import (
    ALIVE_RESOURCE,
    CORPSE_RESOURCE,
    CRITICAL_STATION_TAG,
    EJECTED_RESOURCE,
    MEETING_ACTIVE_RESOURCE,
    MEETING_BALLOT_RESOURCE,
    MEETING_DISCUSSION_RESOURCE,
    MEETING_DISCUSSION_TIMER_RESOURCE,
    MEETING_DISCUSSION_TURNS,
    MEETING_REPORTED_BODY_RESOURCE,
    MEETING_STATION_TAG,
    MEETING_TIMER_RESOURCE,
    MEETING_TOKEN_RESOURCE,
    STATION_SABOTAGED_TAG,
    VIBE_CALL_MEETING,
    VIBE_REPORT,
    VIBE_VOTE_SKIP,
    VOTE_IMPOSTOR_RESOURCE,
    VOTE_SKIP_RESOURCE,
    VOTED_RESOURCE,
    agent_id_resource,
    named_vote_target_count,
    vote_target_resource,
    vote_target_vibe,
)
from amongcogs.game.combat import CombatVariant
from amongcogs.game.common import meeting_duration_steps
from mettagrid.config.event_config import EventConfig, periodic
from mettagrid.config.filter import GameValueFilter, HandlerTarget, hasTag, isNear, isNot, targetHas, targetVibe
from mettagrid.config.game_value import num, weighted_sum
from mettagrid.config.handler_config import queryDelta, updateTarget
from mettagrid.config.mettagrid_config import MettaGridConfig
from mettagrid.config.mutation import EntityTarget, queryPlaceAdjacent
from mettagrid.config.mutation.stats_mutation import logActorAgentStat, logStatToGame
from mettagrid.config.query import Query, query
from mettagrid.config.tag import typeTag


class MeetingsVariant(CoGameMissionVariant):
    name: str = "meetings"
    description: str = "Corpse reports, Cafeteria emergency button, vote intents, and meeting resolution."

    def dependencies(self) -> Deps:
        return Deps(required=[CombatVariant])

    def modify_env(self, mission, env: MettaGridConfig) -> None:
        duration_steps = meeting_duration_steps(mission)
        max_steps = env.game.max_steps
        all_agents_query = query(typeTag("agent"))
        alive_agents_query = Query(
            source=typeTag("agent"),
            filters=[targetHas({ALIVE_RESOURCE: 1})],
        )
        corpse_query = Query(
            source=typeTag("agent"),
            filters=[targetHas({CORPSE_RESOURCE: 1})],
            max_items=1,
            order_by="random",
        )
        vote_target_resources = [
            vote_target_resource(agent_id) for agent_id in range(named_vote_target_count(mission.num_cogs))
        ]
        vote_target_counts = [
            num(
                typeTag("agent"),
                [targetHas({ALIVE_RESOURCE: 1, MEETING_ACTIVE_RESOURCE: 1, resource_name: 1})],
            )
            for resource_name in vote_target_resources
        ]
        vote_skip_count = num(
            typeTag("agent"),
            [targetHas({ALIVE_RESOURCE: 1, MEETING_ACTIVE_RESOURCE: 1, VOTE_SKIP_RESOURCE: 1})],
        )
        votes_cast_count = num(
            typeTag("agent"),
            [targetHas({ALIVE_RESOURCE: 1, MEETING_ACTIVE_RESOURCE: 1, VOTED_RESOURCE: 1})],
        )
        no_meeting_timer_filter = isNot(
            GameValueFilter(
                target=HandlerTarget.TARGET,
                value=num(
                    typeTag("agent"),
                    [targetHas({ALIVE_RESOURCE: 1, MEETING_ACTIVE_RESOURCE: 1, MEETING_TIMER_RESOURCE: 1})],
                ),
                min=1,
            )
        )
        alive_meeting_filter = GameValueFilter(
            target=HandlerTarget.TARGET,
            value=num(typeTag("agent"), [targetHas({ALIVE_RESOURCE: 1, MEETING_ACTIVE_RESOURCE: 1})]),
            min=1,
        )
        clear_vote_target_resources = {resource_name: -1 for resource_name in vote_target_resources}
        meeting_cleanup = [
            queryDelta(
                all_agents_query,
                {
                    MEETING_ACTIVE_RESOURCE: -1,
                    MEETING_DISCUSSION_RESOURCE: -1,
                    MEETING_BALLOT_RESOURCE: -1,
                    MEETING_REPORTED_BODY_RESOURCE: -1,
                    MEETING_DISCUSSION_TIMER_RESOURCE: -MEETING_DISCUSSION_TURNS,
                    MEETING_TIMER_RESOURCE: -duration_steps,
                    VOTED_RESOURCE: -1,
                    VOTE_IMPOSTOR_RESOURCE: -1,
                    VOTE_SKIP_RESOURCE: -1,
                    **clear_vote_target_resources,
                },
            ),
            logStatToGame("meeting_resolved"),
        ]

        env.game.events["crew_report_corpse"] = EventConfig(
            name="crew_report_corpse",
            target_query=query(typeTag("agent")),
            timesteps=periodic(start=1, period=1, end=max_steps),
            filters=[
                targetHas({ALIVE_RESOURCE: 1}),
                isNot(targetHas({MEETING_ACTIVE_RESOURCE: 1})),
                targetVibe(VIBE_REPORT),
                isNear(query(typeTag("agent"), [targetHas({CORPSE_RESOURCE: 1})]), radius=2),
            ],
            mutations=[
                queryDelta(
                    all_agents_query,
                    {
                        MEETING_DISCUSSION_RESOURCE: -1,
                        MEETING_BALLOT_RESOURCE: -1,
                        MEETING_REPORTED_BODY_RESOURCE: -1,
                        MEETING_DISCUSSION_TIMER_RESOURCE: -MEETING_DISCUSSION_TURNS,
                        VOTED_RESOURCE: -1,
                        VOTE_IMPOSTOR_RESOURCE: -1,
                        VOTE_SKIP_RESOURCE: -1,
                        **clear_vote_target_resources,
                    },
                ),
                queryDelta(
                    alive_agents_query,
                    {
                        MEETING_ACTIVE_RESOURCE: 1,
                        MEETING_DISCUSSION_RESOURCE: 1,
                        MEETING_REPORTED_BODY_RESOURCE: 1,
                        MEETING_DISCUSSION_TIMER_RESOURCE: MEETING_DISCUSSION_TURNS,
                        MEETING_TIMER_RESOURCE: duration_steps,
                    },
                ),
                queryDelta(corpse_query, {CORPSE_RESOURCE: -1}),
                logActorAgentStat("reports"),
                logStatToGame("reports"),
                logStatToGame("meeting_reports"),
                logStatToGame("meeting_called"),
            ],
            max_targets=1,
        )
        env.game.events["call_emergency_meeting"] = EventConfig(
            name="call_emergency_meeting",
            target_query=query(typeTag("agent")),
            timesteps=periodic(start=1, period=1, end=max_steps),
            filters=[
                targetHas({ALIVE_RESOURCE: 1, MEETING_TOKEN_RESOURCE: 1}),
                isNot(targetHas({MEETING_ACTIVE_RESOURCE: 1})),
                targetVibe(VIBE_CALL_MEETING),
                isNear(query(MEETING_STATION_TAG), radius=1),
                isNot(
                    GameValueFilter(
                        target=HandlerTarget.TARGET,
                        value=num(CRITICAL_STATION_TAG, [hasTag(STATION_SABOTAGED_TAG)]),
                        min=1,
                    )
                ),
            ],
            mutations=[
                updateTarget({MEETING_TOKEN_RESOURCE: -1}),
                queryDelta(
                    all_agents_query,
                    {
                        MEETING_DISCUSSION_RESOURCE: -1,
                        MEETING_BALLOT_RESOURCE: -1,
                        MEETING_REPORTED_BODY_RESOURCE: -1,
                        MEETING_DISCUSSION_TIMER_RESOURCE: -MEETING_DISCUSSION_TURNS,
                        VOTED_RESOURCE: -1,
                        VOTE_IMPOSTOR_RESOURCE: -1,
                        VOTE_SKIP_RESOURCE: -1,
                        **clear_vote_target_resources,
                    },
                ),
                queryDelta(
                    alive_agents_query,
                    {
                        MEETING_ACTIVE_RESOURCE: 1,
                        MEETING_DISCUSSION_RESOURCE: 1,
                        MEETING_DISCUSSION_TIMER_RESOURCE: MEETING_DISCUSSION_TURNS,
                        MEETING_TIMER_RESOURCE: duration_steps,
                    },
                ),
                logActorAgentStat("meetings_called"),
                logStatToGame("meeting_called"),
                logStatToGame("emergency_meeting_calls"),
            ],
            max_targets=1,
        )
        for agent_id, resource_name in enumerate(vote_target_resources):
            env.game.events[f"meeting_vote_target_{agent_id}_intent"] = EventConfig(
                name=f"meeting_vote_target_{agent_id}_intent",
                target_query=query(typeTag("agent")),
                timesteps=periodic(start=1, period=1, end=max_steps),
                filters=[
                    targetHas({ALIVE_RESOURCE: 1, MEETING_ACTIVE_RESOURCE: 1, MEETING_BALLOT_RESOURCE: 1}),
                    isNot(targetHas({VOTED_RESOURCE: 1})),
                    targetVibe(vote_target_vibe(agent_id)),
                ],
                mutations=[
                    updateTarget({VOTED_RESOURCE: 1, VOTE_IMPOSTOR_RESOURCE: 1, resource_name: 1}),
                    logActorAgentStat("votes_impostor"),
                    logActorAgentStat(f"votes_target_{agent_id}"),
                    logStatToGame("votes_impostor"),
                    logStatToGame(f"votes_target_{agent_id}"),
                ],
            )
        env.game.events["meeting_vote_skip_intent"] = EventConfig(
            name="meeting_vote_skip_intent",
            target_query=query(typeTag("agent")),
            timesteps=periodic(start=1, period=1, end=max_steps),
            filters=[
                targetHas({ALIVE_RESOURCE: 1, MEETING_ACTIVE_RESOURCE: 1, MEETING_BALLOT_RESOURCE: 1}),
                isNot(targetHas({VOTED_RESOURCE: 1})),
                targetVibe(VIBE_VOTE_SKIP),
            ],
            mutations=[
                updateTarget({VOTED_RESOURCE: 1, VOTE_SKIP_RESOURCE: 1}),
                logActorAgentStat("votes_skip"),
                logStatToGame("votes_skip"),
            ],
        )
        env.game.events["meeting_timer_tick"] = EventConfig(
            name="meeting_timer_tick",
            target_query=query(typeTag("agent")),
            timesteps=periodic(start=1, period=1, end=max_steps),
            filters=[targetHas({ALIVE_RESOURCE: 1, MEETING_ACTIVE_RESOURCE: 1, MEETING_TIMER_RESOURCE: 1})],
            mutations=[updateTarget({MEETING_TIMER_RESOURCE: -1})],
        )
        env.game.events["meeting_discussion_tick"] = EventConfig(
            name="meeting_discussion_tick",
            target_query=query(typeTag("agent")),
            timesteps=periodic(start=1, period=1, end=max_steps),
            filters=[
                targetHas(
                    {
                        ALIVE_RESOURCE: 1,
                        MEETING_ACTIVE_RESOURCE: 1,
                        MEETING_DISCUSSION_RESOURCE: 1,
                        MEETING_DISCUSSION_TIMER_RESOURCE: 1,
                    }
                )
            ],
            mutations=[updateTarget({MEETING_DISCUSSION_TIMER_RESOURCE: -1})],
        )
        env.game.events["meeting_teleport_agents"] = EventConfig(
            name="meeting_teleport_agents",
            target_query=query(typeTag("agent")),
            timesteps=periodic(start=1, period=1, end=max_steps),
            filters=[targetHas({ALIVE_RESOURCE: 1, MEETING_ACTIVE_RESOURCE: 1})],
            mutations=[queryPlaceAdjacent(query(MEETING_STATION_TAG), target=EntityTarget.TARGET)],
        )
        env.game.events["meeting_open_ballot"] = EventConfig(
            name="meeting_open_ballot",
            target_query=query(typeTag("agent")),
            timesteps=periodic(start=1, period=1, end=max_steps),
            filters=[
                targetHas({ALIVE_RESOURCE: 1, MEETING_ACTIVE_RESOURCE: 1, MEETING_DISCUSSION_RESOURCE: 1}),
                isNot(targetHas({MEETING_DISCUSSION_TIMER_RESOURCE: 1})),
            ],
            mutations=[
                updateTarget({MEETING_DISCUSSION_RESOURCE: -1, MEETING_BALLOT_RESOURCE: 1}),
                logStatToGame("meeting_ballots"),
            ],
        )
        for agent_id, vote_count in enumerate(vote_target_counts):
            target_query = Query(
                source=typeTag("agent"),
                filters=[targetHas({ALIVE_RESOURCE: 1, MEETING_ACTIVE_RESOURCE: 1, agent_id_resource(agent_id): 1})],
                max_items=1,
            )
            target_vote_filters = [
                no_meeting_timer_filter,
                GameValueFilter(
                    target=HandlerTarget.TARGET,
                    value=vote_count,
                    min=1,
                ),
                GameValueFilter(
                    target=HandlerTarget.TARGET,
                    value=weighted_sum([(1.0, vote_count), (-1.0, vote_skip_count)]),
                    min=1,
                ),
            ]
            for other_agent_id, other_vote_count in enumerate(vote_target_counts):
                if other_agent_id != agent_id:
                    target_vote_filters.append(
                        GameValueFilter(
                            target=HandlerTarget.TARGET,
                            value=weighted_sum([(1.0, vote_count), (-1.0, other_vote_count)]),
                            min=1,
                        )
                    )
            fallback = (
                f"meeting_vote_target_{agent_id + 1}"
                if agent_id + 1 < len(vote_target_counts)
                else "meeting_vote_skip_majority"
            )
            env.game.events[f"meeting_vote_target_{agent_id}"] = EventConfig(
                name=f"meeting_vote_target_{agent_id}",
                target_query=target_query,
                timesteps=periodic(start=1, period=1, end=max_steps) if agent_id == 0 else [],
                filters=target_vote_filters,
                mutations=[
                    updateTarget({ALIVE_RESOURCE: -1, EJECTED_RESOURCE: 1}),
                    *meeting_cleanup,
                    logActorAgentStat("ejected"),
                    logStatToGame("meeting_votes"),
                    logStatToGame("ejections"),
                ],
                max_targets=1,
                fallback=fallback,
            )
        env.game.events["meeting_vote_skip_majority"] = EventConfig(
            name="meeting_vote_skip_majority",
            target_query=query(typeTag("agent")),
            timesteps=[],
            filters=[
                alive_meeting_filter,
                no_meeting_timer_filter,
                GameValueFilter(
                    target=HandlerTarget.TARGET,
                    value=vote_skip_count,
                    min=1,
                ),
                *[
                    GameValueFilter(
                        target=HandlerTarget.TARGET,
                        value=weighted_sum([(1.0, vote_skip_count), (-1.0, vote_count)]),
                        min=1,
                    )
                    for vote_count in vote_target_counts
                ],
            ],
            mutations=[
                *meeting_cleanup,
                logStatToGame("meeting_votes"),
                logStatToGame("meeting_skips"),
            ],
            max_targets=1,
            fallback="meeting_vote_tie",
        )
        env.game.events["meeting_vote_tie"] = EventConfig(
            name="meeting_vote_tie",
            target_query=query(typeTag("agent")),
            timesteps=[],
            filters=[
                alive_meeting_filter,
                no_meeting_timer_filter,
                GameValueFilter(
                    target=HandlerTarget.TARGET,
                    value=votes_cast_count,
                    min=1,
                ),
            ],
            mutations=[
                *meeting_cleanup,
                logStatToGame("meeting_votes"),
                logStatToGame("meeting_ties"),
            ],
            max_targets=1,
            fallback="meeting_vote_crew",
        )
        env.game.events["meeting_vote_crew"] = EventConfig(
            name="meeting_vote_crew",
            target_query=query(typeTag("agent")),
            timesteps=[],
            filters=[
                alive_meeting_filter,
                no_meeting_timer_filter,
            ],
            mutations=[
                *meeting_cleanup,
                logStatToGame("meeting_skips"),
                logStatToGame("meeting_no_votes"),
            ],
            max_targets=1,
        )
