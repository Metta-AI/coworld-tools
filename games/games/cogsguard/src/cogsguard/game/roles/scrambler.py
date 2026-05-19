"""Scrambler role: disrupts enemy junction control."""

from __future__ import annotations

from typing_extensions import override

from cogames.core import Deps
from cogsguard.game.damage import DamageVariant
from cogsguard.game.roles.role import RoleVariant
from cogsguard.game.teams.junction import TeamJunctionVariant
from cogames.variants import ResolvedDeps


class ScramblerVariant(RoleVariant):
    """Enable the scrambler role: disrupts enemy junction control."""

    name: str = "scrambler_role"
    description: str = "Scrambler role: disrupts enemy junction control."
    hp_modifier: int = 200

    @override
    def dependencies(self) -> Deps:
        parent = super().dependencies()
        return Deps(required=parent.required, optional=[TeamJunctionVariant, DamageVariant])

    @override
    def configure(self, deps: ResolvedDeps) -> None:
        super().configure(deps)

        tj = deps.optional(TeamJunctionVariant)
        if tj is not None:
            tj.scramble_required_resources["scrambler"] = 1

        d = deps.optional(DamageVariant)
        if d is not None:
            d.modifiers["scrambler"] = self.hp_modifier
