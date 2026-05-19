"""Team junction variant: minimal placeholder for rules rewrite.

All old heal/damage/unalign/claim handlers have been stripped.
Will be rewritten to match new RULES.md combat/alignment mechanics.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, override

from cogames.core import CoGameMissionVariant, Deps
from cogony.game.junction import JunctionVariant
from cogony.game.teams.hub import TeamHubVariant
from cogony.game.teams.team import TeamVariant
from mettagrid.config.mettagrid_config import MettaGridConfig
from mettagrid.config.render_config import RenderAsset

if TYPE_CHECKING:
    from cogony.mission import CogonyMission


class TeamJunctionVariant(CoGameMissionVariant):
    """Minimal junction team integration. See module docstring."""

    name: str = "team_junction"
    description: str = "Junction team integration (minimal skeleton)."

    @override
    def dependencies(self) -> Deps:
        return Deps(required=[JunctionVariant, TeamHubVariant])

    @override
    def modify_env(self, mission: CogonyMission, env: MettaGridConfig) -> None:
        team_v = mission.required_variant(TeamVariant)
        all_teams = list(team_v.teams.values())

        env.game.render.assets["junction"] = [
            *[RenderAsset(asset="junction.working", tags=[t.team_tag()]) for t in all_teams],
            RenderAsset(asset="junction"),
        ]
