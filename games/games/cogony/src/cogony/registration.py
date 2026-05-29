"""Register `cogony` with the cogames CLI."""

from __future__ import annotations

from mettagrid.cogame.game import CoGame, register_game

from cogony.game import _get_all_variants
from cogony.mission import CogonyMission
from cogony.mission import CogonyMission


class CogonyGame(CoGame):
    def __init__(self) -> None:
        super().__init__(
            name="cogony",
            missions=[CogonyMission()],
            variants=_get_all_variants(),
            eval_missions=[],
        )


_GAME: CogonyGame | None = None


def get_game() -> CogonyGame:
    global _GAME
    if _GAME is None:
        _GAME = CogonyGame()
    return _GAME


register_game(get_game())
