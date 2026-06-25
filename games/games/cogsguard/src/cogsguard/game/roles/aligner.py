"""Aligner role: converts neutral junctions to team-owned."""

from __future__ import annotations

from typing_extensions import override

from cogsguard.core import Deps
from cogsguard.game.roles.role import RoleVariant
from cogsguard.game.teams.junction import TeamJunctionVariant
from cogsguard.variants import ResolvedDeps


class AlignerVariant(RoleVariant):
    """Enable the aligner role: converts neutral junctions to team-owned."""

    name: str = "aligner_role"
    description: str = "Aligner role: converts neutral junctions to team-owned."

    @override
    def dependencies(self) -> Deps:
        parent = super().dependencies()
        return Deps(required=parent.required, optional=[TeamJunctionVariant])

    @override
    def configure(self, deps: ResolvedDeps) -> None:
        super().configure(deps)

        tj = deps.optional(TeamJunctionVariant)
        if tj is not None:
            tj.align_required_resources["aligner"] = 1
