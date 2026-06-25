"""Werewolf night-kill mechanics."""

from __future__ import annotations

from mettagrid.cogame.core import CoGameMissionVariant, Deps
from mettagrid.cogame.variants import ResolvedDeps
from werecog.variants.common import (
    ALIVE,
    DAY_PHASE,
    NIGHT_KILL_USED_STAT,
    NIGHT_KILLS_STAT,
    NIGHT_HUNT_OPEN,
    NIGHT_PHASE,
    ROLE_VILLAGER,
    ROLE_WEREWOLF,
    SUSPICION,
    VOTE_TOKEN,
    actor_has_role,
    night_kills_per_phase,
    no_game_winner_filter,
    target_has_role,
)
from werecog.variants.meetings import MeetingsVariant
from werecog.variants.suspicion import SuspicionVariant
from mettagrid.config.filter import GameValueFilter, HandlerTarget, actorHas, isNot, targetHas
from mettagrid.config.game_value import stat
from mettagrid.config.handler_config import Handler, firstMatch, updateActor, updateTarget
from mettagrid.config.mettagrid_config import MettaGridConfig
from mettagrid.config.mutation.stats_mutation import logActorAgentStat, logStatToGame


class HuntVariant(CoGameMissionVariant):
    name: str = "hunt"
    description: str = "Werewolves choose one or more living villagers to kill each night."

    def dependencies(self) -> Deps:
        return Deps(required=[MeetingsVariant], optional=[SuspicionVariant])

    def configure(self, deps: ResolvedDeps) -> None:
        self._tracks_suspicion = deps.optional(SuspicionVariant) is not None

    def modify_env(self, mission, env: MettaGridConfig) -> None:
        night_kill_unused = isNot(
            GameValueFilter(
                target=HandlerTarget.ACTOR,
                value=stat(f"game.{NIGHT_KILL_USED_STAT}"),
                min=night_kills_per_phase(mission),
            )
        )
        for agent in env.game.agents:
            mutations = [
                updateTarget({ALIVE: -1, VOTE_TOKEN: -1, DAY_PHASE: -1, NIGHT_PHASE: -1}),
                logActorAgentStat("villager_eliminations"),
                logStatToGame(NIGHT_KILL_USED_STAT),
                logStatToGame(NIGHT_KILLS_STAT),
            ]
            if self._tracks_suspicion:
                # Night killers need to leave a strong enough public clue for daytime accusation play
                # to reliably surface werewolves in a speechless embodied setting.
                mutations.append(updateActor({SUSPICION: 6}))

            agent.on_use_handler = firstMatch(
                [
                    agent.on_use_handler,
                    Handler(
                        name="werewolf_eliminate",
                        filters=[
                            actorHas({ALIVE: 1, NIGHT_PHASE: 1, NIGHT_HUNT_OPEN: 1}),
                            actor_has_role(ROLE_WEREWOLF),
                            targetHas({ALIVE: 1}),
                            target_has_role(ROLE_VILLAGER),
                            night_kill_unused,
                            no_game_winner_filter(),
                        ],
                        mutations=mutations,
                    ),
                ]
            )
