"""Daytime accusation and execution mechanics for Werewolf/Mafia."""

from __future__ import annotations

from cogames.core import CoGameMissionVariant, Deps
from werecog.variants.common import (
    ACCUSATION,
    ACCUSE_ACTIONS_STAT,
    ALIVE,
    DAY_EXECUTION_USED_STAT,
    DAY_EXECUTIONS_STAT,
    DAY_PHASE,
    DAY_VOTE_OPEN,
    DAY_VOTES_CAST_STAT,
    NIGHT_PHASE,
    ROLE_VILLAGER,
    ROLE_WEREWOLF,
    VOTE_TOKEN,
    WEREWOLF_EXECUTIONS_STAT,
    actor_has_any_role,
    execution_threshold,
    no_game_winner_filter,
    target_has_any_role,
    target_has_role,
)
from werecog.variants.meetings import MeetingsVariant
from mettagrid.config.filter import (
    GameValueFilter,
    HandlerTarget,
    actorHas,
    isNot,
    targetHas,
)
from mettagrid.config.game_value import stat
from mettagrid.config.handler_config import Handler, firstMatch, updateActor, updateTarget
from mettagrid.config.mettagrid_config import MettaGridConfig, ResourceLimitsConfig
from mettagrid.config.mutation.stats_mutation import logActorAgentStat, logStatToGame


class VotingVariant(CoGameMissionVariant):
    name: str = "voting"
    description: str = "Each day, the village accuses and may execute one player."

    def dependencies(self) -> Deps:
        return Deps(required=[MeetingsVariant])

    def modify_env(self, mission, env: MettaGridConfig) -> None:
        accusation_limit = execution_threshold(mission, len(env.game.agents))
        if ACCUSATION not in env.game.resource_names:
            env.game.resource_names.append(ACCUSATION)

        for agent in env.game.agents:
            inv = agent.inventory
            inv.initial[ACCUSATION] = 0
            inv.limits["accusation"] = ResourceLimitsConfig(
                base=accusation_limit,
                max=accusation_limit,
                resources=[ACCUSATION],
            )

        env.game.events["night_phase_start"].mutations.append(updateTarget({ACCUSATION: -accusation_limit}))
        env.game.events["day_phase_start"].mutations.append(updateTarget({ACCUSATION: -accusation_limit}))

        execution_unused = isNot(
            GameValueFilter(target=HandlerTarget.ACTOR, value=stat(f"game.{DAY_EXECUTION_USED_STAT}"), min=1)
        )
        shared_filters = [
            actor_has_any_role(),
            actorHas({ALIVE: 1, DAY_PHASE: 1, DAY_VOTE_OPEN: 1, VOTE_TOKEN: 1}),
            target_has_any_role(),
            targetHas({ALIVE: 1}),
            execution_unused,
            no_game_winner_filter(),
        ]
        execution_mutations = [
            updateActor({VOTE_TOKEN: -1}),
            updateTarget({ACCUSATION: 1 - accusation_limit, ALIVE: -1, VOTE_TOKEN: -1, DAY_PHASE: -1, NIGHT_PHASE: -1}),
            logActorAgentStat("day_votes_cast"),
            logStatToGame(DAY_EXECUTION_USED_STAT),
            logStatToGame(DAY_EXECUTIONS_STAT),
            logStatToGame(DAY_VOTES_CAST_STAT),
        ]

        for agent in env.game.agents:
            agent.on_use_handler = firstMatch(
                [
                    agent.on_use_handler,
                    Handler(
                        name="execute_werewolf",
                        filters=[
                            *shared_filters,
                            target_has_role(ROLE_WEREWOLF),
                            targetHas({ACCUSATION: accusation_limit - 1}),
                        ],
                        mutations=[
                            *execution_mutations,
                            logActorAgentStat("werewolf_votes"),
                            logStatToGame(WEREWOLF_EXECUTIONS_STAT),
                        ],
                    ),
                ]
            )
            agent.on_use_handler = firstMatch(
                [
                    agent.on_use_handler,
                    Handler(
                        name="execute_villager",
                        filters=[
                            *shared_filters,
                            target_has_role(ROLE_VILLAGER),
                            targetHas({ACCUSATION: accusation_limit - 1}),
                        ],
                        mutations=execution_mutations,
                    ),
                ]
            )
            agent.on_use_handler = firstMatch(
                [
                    agent.on_use_handler,
                    Handler(
                        name="accuse_player",
                        filters=shared_filters,
                        mutations=[
                            updateActor({VOTE_TOKEN: -1}),
                            updateTarget({ACCUSATION: 1}),
                            logActorAgentStat("day_votes_cast"),
                            logStatToGame(DAY_VOTES_CAST_STAT),
                            logStatToGame(ACCUSE_ACTIONS_STAT),
                        ],
                    ),
                ]
            )
