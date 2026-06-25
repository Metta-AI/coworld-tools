"""Difficulty variants for the cogame template.

These are simple scalar tweaks that demonstrate mutating the generated
``MettaGridConfig`` in place. Variants may also mutate mission-level state
through overrides like ``configure`` / ``modify_env``.

TODO(cogame): rename/expand these for your game's actual difficulty knobs.
"""

from __future__ import annotations

from cogames.core import CoGameMissionVariant
from mettagrid.config.mettagrid_config import MettaGridConfig, ResourceLimitsConfig


class EasyVariant(CoGameMissionVariant):
    """Give agents a larger starting ore/HP buffer so the default loop is easier."""

    name: str = "easy"
    description: str = "More starting HP, higher resource cap."

    def modify_env(self, mission, env: MettaGridConfig) -> None:
        for agent in env.game.agents:
            agent.inventory.initial["hp"] = 5
            agent.inventory.limits["hp"] = ResourceLimitsConfig(
                base=5, max=5, resources=["hp"]
            )
            agent.inventory.limits["ore"] = ResourceLimitsConfig(
                base=20, max=20, resources=["ore"]
            )


class HardVariant(CoGameMissionVariant):
    """Shorter episode, tighter ore cap. Demonstrates scalar tightening."""

    name: str = "hard"
    description: str = "Shorter episode + smaller ore cap."

    def modify_env(self, mission, env: MettaGridConfig) -> None:
        env.game.max_steps = max(1, env.game.max_steps // 2)
        for agent in env.game.agents:
            agent.inventory.limits["ore"] = ResourceLimitsConfig(
                base=5, max=5, resources=["ore"]
            )
