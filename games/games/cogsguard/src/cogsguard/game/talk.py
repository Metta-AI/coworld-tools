from __future__ import annotations

from typing import TYPE_CHECKING
from typing_extensions import override

from cogames.core import CoGameMissionVariant, Deps
from cogsguard.game.vibes import VibesVariant
from mettagrid.config.mettagrid_config import MettaGridConfig, TalkConfig

if TYPE_CHECKING:
    from cogsguard.missions.mission import CvCMission


class TalkVariant(CoGameMissionVariant):
    """Enable speech-bubble talk as the talk flavor of vibes."""

    name: str = "talk"
    description: str = "Agents can send short speech-bubble messages instead of change_vibe actions."

    @override
    def dependencies(self) -> Deps:
        return Deps(required=[VibesVariant])

    @override
    def modify_env(self, mission: CvCMission, env: MettaGridConfig) -> None:
        env.game.actions.change_vibe.enabled = False
        env.game.talk = TalkConfig(enabled=True, max_length=140, cooldown_steps=50)
