from __future__ import annotations

from collections.abc import Sequence

from mettagrid.cogame.game import CoGame, register_game as register_cogame
from mettagrid.config.mettagrid_config import MettaGridConfig

from werecog.defaults import DEFAULT_MAX_STEPS
from werecog.game import WerecogMission
from werecog.variants import VARIANTS

_ALLOWED_NAMES = frozenset({"werecog", "werewolf_mafia", "mafia"})
_REGISTERED_GAME: WerecogGame | None = None


class WerecogGame(CoGame):
    def __init__(self) -> None:
        super().__init__(
            name="werecog",
            missions=[WerecogMission.create(num_agents=8, max_steps=DEFAULT_MAX_STEPS)],
            variants=list(VARIANTS),
        )


def register_game() -> WerecogGame:
    global _REGISTERED_GAME
    if _REGISTERED_GAME is None:
        _REGISTERED_GAME = WerecogGame()
    register_cogame(_REGISTERED_GAME)
    return _REGISTERED_GAME


def make_game(
    name: str = "werecog",
    *,
    num_agents: int,
    max_steps: int,
    variants: Sequence[str] | None = None,
) -> MettaGridConfig:
    if name not in _ALLOWED_NAMES:
        available = ", ".join(sorted(_ALLOWED_NAMES))
        raise ValueError(f"Unknown game {name!r}. Available: {available}")
    mission = WerecogMission.create(num_agents=num_agents, max_steps=max_steps)
    if name != "werecog":
        mission = mission.model_copy(update={"name": name})
    if variants:
        mission = mission.with_variants(list(variants))
    return mission.make_env()


register_game()
