"""Multi-year variants: extend episode length for more seasonal cycles."""

from __future__ import annotations

from cogames.core import CoGameMissionVariant, Deps
from hungercog.variants.seasons import YEAR_LENGTH, SeasonsVariant
from mettagrid.config.mettagrid_config import MettaGridConfig


class MultiYear5Variant(CoGameMissionVariant):
    """5 years (5000 steps)."""

    name: str = "multi_year_5"
    description: str = "5 years (5000 steps)."

    def dependencies(self) -> Deps:
        return Deps(required=[SeasonsVariant])

    def modify_env(self, mission, env: MettaGridConfig) -> None:
        env.game.max_steps = 5 * YEAR_LENGTH


class MultiYear10Variant(CoGameMissionVariant):
    """10 years (10000 steps)."""

    name: str = "multi_year_10"
    description: str = "10 years (10000 steps)."

    def dependencies(self) -> Deps:
        return Deps(required=[SeasonsVariant])

    def modify_env(self, mission, env: MettaGridConfig) -> None:
        env.game.max_steps = 10 * YEAR_LENGTH
