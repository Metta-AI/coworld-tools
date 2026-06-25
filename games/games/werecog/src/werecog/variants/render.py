"""Render assets/HUD variant for Werewolf/Mafia."""

from __future__ import annotations

from mettagrid.cogame.core import CoGameMissionVariant, Deps
from werecog.variants.common import (
    ACCUSATION,
    ALIVE,
    DAY_PHASE,
    DAY_VOTE_OPEN,
    NIGHT_PHASE,
    NIGHT_HUNT_OPEN,
    SUSPICION,
    VOTE_TOKEN,
    execution_threshold,
)
from werecog.variants.suspicion import SuspicionVariant
from werecog.variants.voting import VotingVariant
from mettagrid.config.mettagrid_config import MettaGridConfig
from mettagrid.config.render_config import RenderAsset, RenderHudConfig, RenderStatusBarConfig


class RenderVariant(CoGameMissionVariant):
    name: str = "render"
    description: str = "Enable Werewolf/Mafia game-specific render assets and HUD."

    def dependencies(self) -> Deps:
        return Deps(required=[SuspicionVariant, VotingVariant])

    def modify_env(self, mission, env: MettaGridConfig) -> None:
        # Alive agents share one public-facing avatar so normal play does not leak hidden roles.
        env.game.render.assets["agent"] = [
            RenderAsset(asset="werewolf_mafia_villager", resources={ALIVE: 1}),
            RenderAsset(asset="werewolf_mafia_dead"),
        ]
        env.game.render.assets["meeting_bell"] = [RenderAsset(asset="werewolf_mafia_meeting_bell")]

        accusation_limit = execution_threshold(mission, len(env.game.agents))
        status = env.game.render.object_status["agent"]
        env.game.render.agent_huds["alive"] = RenderHudConfig(resource=ALIVE, max=1, rank=0)
        status["alive"] = RenderStatusBarConfig(resource=ALIVE, short_name="L", max=1, rank=0)
        env.game.render.agent_huds["vote_token"] = RenderHudConfig(resource=VOTE_TOKEN, max=1, rank=1)
        status["vote_token"] = RenderStatusBarConfig(resource=VOTE_TOKEN, short_name="V", max=1, rank=1)
        env.game.render.agent_huds["suspicion"] = RenderHudConfig(resource=SUSPICION, max=50, rank=2)
        status["suspicion"] = RenderStatusBarConfig(resource=SUSPICION, short_name="S", max=50, rank=2)
        env.game.render.agent_huds["day_phase"] = RenderHudConfig(resource=DAY_PHASE, max=1, rank=3, short_name="DAY")
        env.game.render.agent_huds["night_phase"] = RenderHudConfig(resource=NIGHT_PHASE, max=1, rank=4, short_name="NIGHT")
        env.game.render.agent_huds["day_vote_open"] = RenderHudConfig(resource=DAY_VOTE_OPEN, max=1, rank=5, short_name="VOTE")
        env.game.render.agent_huds["night_hunt_open"] = RenderHudConfig(resource=NIGHT_HUNT_OPEN, max=1, rank=6, short_name="HUNT")
        status["accusation"] = RenderStatusBarConfig(resource=ACCUSATION, short_name="ACCUSE", max=accusation_limit, rank=3)
        status["day_phase"] = RenderStatusBarConfig(resource=DAY_PHASE, short_name="DAY", max=1, divisions=1, rank=4)
        status["night_phase"] = RenderStatusBarConfig(resource=NIGHT_PHASE, short_name="NIGHT", max=1, divisions=1, rank=5)
        status["day_vote_open"] = RenderStatusBarConfig(resource=DAY_VOTE_OPEN, short_name="VOTE", max=1, divisions=1, rank=6)
        status["night_hunt_open"] = RenderStatusBarConfig(resource=NIGHT_HUNT_OPEN, short_name="HUNT", max=1, divisions=1, rank=7)
