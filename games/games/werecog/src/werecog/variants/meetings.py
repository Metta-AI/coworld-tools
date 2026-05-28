"""Phase and meeting mechanics for Werewolf/Mafia."""

from __future__ import annotations

from cogames.core import CoGameMissionVariant, Deps
from werecog.variants.common import (
    DAY_EXECUTION_USED_STAT,
    DAY_PHASE,
    DAY_VOTE_OPEN,
    NIGHT_KILL_USED_STAT,
    NIGHT_HUNT_OPEN,
    NIGHT_PHASE,
    VOTE_TOKEN,
    append_unique,
    day_vote_open_step,
    meeting_bell,
    night_hunt_open_step,
    night_steps,
    phase_period,
    reset_game_stat,
)
from werecog.variants.roles import RolesVariant
from mettagrid.config.event_config import EventConfig, periodic
from mettagrid.config.handler_config import updateTarget
from mettagrid.config.mettagrid_config import MettaGridConfig, ResourceLimitsConfig
from mettagrid.config.query import query
from mettagrid.config.tag import typeTag


class MeetingsVariant(CoGameMissionVariant):
    name: str = "meetings"
    description: str = "Alternate between night kills and day voting."

    def dependencies(self) -> Deps:
        return Deps(required=[RolesVariant])

    def modify_env(self, mission, env: MettaGridConfig) -> None:
        append_unique(env.game.resource_names, VOTE_TOKEN)
        append_unique(env.game.resource_names, DAY_PHASE)
        append_unique(env.game.resource_names, NIGHT_PHASE)
        append_unique(env.game.resource_names, DAY_VOTE_OPEN)
        append_unique(env.game.resource_names, NIGHT_HUNT_OPEN)

        for agent in env.game.agents:
            inv = agent.inventory
            inv.initial[VOTE_TOKEN] = 0
            inv.initial[DAY_PHASE] = 0
            inv.initial[NIGHT_PHASE] = 1
            inv.initial[DAY_VOTE_OPEN] = 0
            inv.initial[NIGHT_HUNT_OPEN] = 0
            inv.limits["vote_token"] = ResourceLimitsConfig(base=1, max=1, resources=[VOTE_TOKEN])
            inv.limits["day_phase"] = ResourceLimitsConfig(base=1, max=1, resources=[DAY_PHASE])
            inv.limits["night_phase"] = ResourceLimitsConfig(base=1, max=1, resources=[NIGHT_PHASE])
            inv.limits["day_vote_open"] = ResourceLimitsConfig(base=1, max=1, resources=[DAY_VOTE_OPEN])
            inv.limits["night_hunt_open"] = ResourceLimitsConfig(base=1, max=1, resources=[NIGHT_HUNT_OPEN])

        env.game.objects["meeting_bell"] = meeting_bell()

        env.game.events["night_phase_start"] = EventConfig(
            name="night_phase_start",
            target_query=query(typeTag("agent")),
            timesteps=periodic(start=0, period=phase_period(mission), end=env.game.max_steps),
            mutations=[
                updateTarget({NIGHT_PHASE: 1, DAY_PHASE: -1, VOTE_TOKEN: -1, DAY_VOTE_OPEN: -1, NIGHT_HUNT_OPEN: -1}),
                reset_game_stat(NIGHT_KILL_USED_STAT),
            ],
        )
        env.game.events["day_vote_open"] = EventConfig(
            name="day_vote_open",
            target_query=query(typeTag("agent")),
            timesteps=periodic(
                start=night_steps(mission) + day_vote_open_step(mission),
                period=phase_period(mission),
                end=env.game.max_steps,
            ),
            mutations=[updateTarget({DAY_VOTE_OPEN: 1})],
        )
        env.game.events["night_hunt_open"] = EventConfig(
            name="night_hunt_open",
            target_query=query(typeTag("agent")),
            timesteps=periodic(start=night_hunt_open_step(mission), period=phase_period(mission), end=env.game.max_steps),
            mutations=[updateTarget({NIGHT_HUNT_OPEN: 1})],
        )
        env.game.events["day_phase_start"] = EventConfig(
            name="day_phase_start",
            target_query=query(typeTag("agent")),
            timesteps=periodic(start=night_steps(mission), period=phase_period(mission), end=env.game.max_steps),
            mutations=[
                updateTarget({DAY_PHASE: 1, NIGHT_PHASE: -1, VOTE_TOKEN: 1, DAY_VOTE_OPEN: -1, NIGHT_HUNT_OPEN: -1}),
                reset_game_stat(DAY_EXECUTION_USED_STAT),
            ],
        )
