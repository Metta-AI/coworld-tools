"""Game registration + discovery.

Mirrors ``cogames.game`` without depending on the shared cogames framework.
Lets code retrieve the registered game by name (useful for tests and
multi-game harnesses).
"""

from __future__ import annotations

from collections.abc import Sequence

from cogame.framework.core import CoGameMission, CoGameMissionVariant
from cogame.framework.variants import VariantRegistry


class CoGame:
    """Base class for games. Holds missions and a variant registry."""

    name: str
    missions: list[CoGameMission]
    variant_registry: VariantRegistry
    eval_missions: list[CoGameMission]

    def __init__(
        self,
        name: str,
        missions: Sequence[CoGameMission],
        variants: Sequence[CoGameMissionVariant],
        eval_missions: Sequence[CoGameMission] | None = None,
    ) -> None:
        self.name = name
        self.missions = list(missions)
        self.variant_registry = VariantRegistry(list(variants))
        self.eval_missions = list(eval_missions) if eval_missions else []


_GAMES: dict[str, CoGame] = {}


def get_game(name: str) -> CoGame:
    """Get a registered game by name."""
    assert name in _GAMES, f"Unknown game '{name}'. Registered: {sorted(_GAMES)}"
    return _GAMES[name]


def register_game(game: CoGame) -> None:
    """Register a game for retrieval by name."""
    _GAMES[game.name] = game
