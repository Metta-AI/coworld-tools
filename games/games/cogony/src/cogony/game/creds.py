"""Creds variant: adds a creds resource with effectively unlimited capacity."""

from __future__ import annotations

from typing import TYPE_CHECKING, override

from cogames.core import CoGameMissionVariant
from mettagrid.config.mettagrid_config import MettaGridConfig, ResourceLimitsConfig

if TYPE_CHECKING:
    from cogony.mission import CogonyMission

# uint16 max — the engine's hard ceiling; functionally "unlimited" for gameplay.
UNLIMITED = 65535


class CredsVariant(CoGameMissionVariant):
    """Add creds resource. Agents start with 0 and can accumulate without cap."""

    name: str = "creds"
    description: str = "Unlimited creds resource; agents start with 0."

    initial: int = 100

    @override
    def modify_env(self, mission: CogonyMission, env: MettaGridConfig) -> None:
        env.game.add_resource("creds")
        for agent in env.game.agents:
            agent.inventory.limits.setdefault(
                "creds",
                ResourceLimitsConfig(base=UNLIMITED, max=UNLIMITED, resources=["creds"]),
            )
            agent.inventory.initial.setdefault("creds", self.initial)
