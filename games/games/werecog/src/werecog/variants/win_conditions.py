"""Village/werewolf win conditions."""

from __future__ import annotations

from cogames.core import CoGameMissionVariant, Deps
from werecog.variants.common import (
    VILLAGERS_WIN_STAT,
    WEREWOLVES_WIN_STAT,
    WINNER_DECLARED_STAT,
    living_parity_margin,
    living_werewolf_count,
    set_game_stat,
)
from werecog.variants.roles import RolesVariant
from mettagrid.config.event_config import EventConfig, periodic
from mettagrid.config.filter import GameValueFilter, HandlerTarget, isNot, query, typeTag
from mettagrid.config.game_value import stat
from mettagrid.config.mettagrid_config import MettaGridConfig


class WinConditionsVariant(CoGameMissionVariant):
    name: str = "win_conditions"
    description: str = "Villagers win by eliminating all werewolves; werewolves win on parity."

    def dependencies(self) -> Deps:
        return Deps(required=[RolesVariant])

    def modify_env(self, mission, env: MettaGridConfig) -> None:
        winner_not_declared = isNot(
            GameValueFilter(target=HandlerTarget.TARGET, value=stat(f"game.{WINNER_DECLARED_STAT}"), min=1)
        )
        werewolves_remaining = GameValueFilter(
            target=HandlerTarget.TARGET,
            value=living_werewolf_count(),
            min=1,
        )
        werewolf_parity = GameValueFilter(
            target=HandlerTarget.TARGET,
            value=living_parity_margin(),
            min=0,
        )

        env.game.events["villagers_win_check"] = EventConfig(
            name="villagers_win_check",
            target_query=query(typeTag("agent")),
            timesteps=periodic(start=0, period=1, end=env.game.max_steps),
            max_targets=1,
            filters=[winner_not_declared, isNot(werewolves_remaining)],
            mutations=[
                set_game_stat(VILLAGERS_WIN_STAT),
                set_game_stat(WINNER_DECLARED_STAT),
            ],
        )
        env.game.events["werewolves_win_check"] = EventConfig(
            name="werewolves_win_check",
            target_query=query(typeTag("agent")),
            timesteps=periodic(start=0, period=1, end=env.game.max_steps),
            max_targets=1,
            filters=[winner_not_declared, werewolves_remaining, werewolf_parity],
            mutations=[
                set_game_stat(WEREWOLVES_WIN_STAT),
                set_game_stat(WINNER_DECLARED_STAT),
            ],
        )
