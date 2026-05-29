"""Vibes variants for enabling or disabling explicit vibe actions."""

from __future__ import annotations

from typing import TYPE_CHECKING, override

from pydantic import Field

from mettagrid.cogame.core import CoGameMissionVariant, Deps
from mettagrid.config.action_config import ChangeVibeActionConfig
from mettagrid.config.mettagrid_config import MettaGridConfig
from mettagrid.config.vibes import Vibe

if TYPE_CHECKING:
    from cogony.mission import CogonyMission

GOD_MODE_RESOURCE_VIBES = [
    Vibe("🪙", "cred"),
    Vibe("❤️", "heart"),
]


class VibesVariant(CoGameMissionVariant):
    """Add vibes and the change_vibe action."""

    name: str = "vibes"
    description: str = "Agents can express vibes via the change_vibe action."
    vibes: list[Vibe] = Field(
        default_factory=lambda: [
            Vibe("😐", "default"),
            Vibe("⚔️", "attack"),
            Vibe("🩹", "patch"),
            Vibe("🪤", "trap"),
            Vibe("🦘", "jump"),
            Vibe("🔄", "swap"),
        ]
    )

    @override
    def modify_env(self, mission: CogonyMission, env: MettaGridConfig) -> None:
        vibes = list(self.vibes)
        if mission.god_mode:
            vibes = [*vibes[:3], *GOD_MODE_RESOURCE_VIBES, *vibes[3:]]
        env.game.vibe_names = [v.name for v in vibes]
        env.game.actions.change_vibe = ChangeVibeActionConfig(vibes=vibes)


class NoVibesVariant(CoGameMissionVariant):
    """Disable explicit vibe-changing while preserving existing vibe semantics."""

    name: str = "no_vibes"
    description: str = "Remove change_vibe actions from the action space."

    @override
    def dependencies(self) -> Deps:
        return Deps(optional=[VibesVariant])

    @override
    def modify_env(self, mission: CogonyMission, env: MettaGridConfig) -> None:
        env.game.actions.change_vibe.enabled = False
