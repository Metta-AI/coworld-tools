"""Meta-variant that activates full Werewolf/Mafia mechanics."""

from __future__ import annotations

from mettagrid.cogame.core import CoGameMissionVariant, Deps
from werecog.variants.hunt import HuntVariant
from werecog.variants.render import RenderVariant
from werecog.variants.role_action_rewards import RoleActionRewardsVariant
from werecog.variants.survival_rewards import SurvivalRewardsVariant
from werecog.variants.voting import VotingVariant
from werecog.variants.win_conditions import WinConditionsVariant


class FullVariant(CoGameMissionVariant):
    name: str = "full"
    description: str = "Enable the full Werewolf/Mafia mechanics set."

    def dependencies(self) -> Deps:
        return Deps(
            required=[
                HuntVariant,
                VotingVariant,
                WinConditionsVariant,
                SurvivalRewardsVariant,
                RoleActionRewardsVariant,
                RenderVariant,
            ]
        )
