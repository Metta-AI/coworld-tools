"""Heart variant: adds heart resource and inventory limit to agents."""

from __future__ import annotations

from typing import TYPE_CHECKING, override

from mettagrid.cogame.core import CoGameMissionVariant
from mettagrid.config.mettagrid_config import MettaGridConfig, ResourceLimitsConfig
from pydantic import Field

from cogony.game.creds import UNLIMITED

if TYPE_CHECKING:
    from cogony.mission import CogonyMission


class HeartVariant(CoGameMissionVariant):
    """Add heart resource and inventory limit to agents.

    Hearts persist through death — they are never cleared from inventory.
    """

    name: str = "heart"
    description: str = "Agents can carry hearts for role abilities."
    cost: dict[str, int] = Field(default_factory=dict, description="Element costs to craft a heart, set by mission.")
    limit: int = Field(default=UNLIMITED)

    @override
    def modify_env(self, mission: CogonyMission, env: MettaGridConfig) -> None:
        env.game.add_resource("heart")

        for agent in env.game.agents:
            agent.inventory.limits.setdefault(
                "heart",
                ResourceLimitsConfig(base=self.limit, max=self.limit, resources=["heart"]),
            )
            agent.inventory.initial.setdefault("heart", 1)
