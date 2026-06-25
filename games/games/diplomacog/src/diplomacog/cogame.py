"""CoGames registration for Diplomacog."""

from __future__ import annotations

from mettagrid.cogame.game import CoGame, register_game

from diplomacog.game import make_diplomacog_mission
from diplomacog.variants import VARIANTS


class DiplomacogGame(CoGame):
    def __init__(self) -> None:
        super().__init__(
            name="diplomacog",
            missions=[make_diplomacog_mission()],
            variants=VARIANTS,
        )


DIPLOMACOG_GAME = DiplomacogGame()
register_game(DIPLOMACOG_GAME)
