"""Scout role: increased HP and energy for exploration and reconnaissance."""

from __future__ import annotations

from typing_extensions import override

from cogsguard.core import Deps
from cogsguard.game.damage import DamageVariant
from cogsguard.game.energy import EnergyVariant
from cogsguard.game.roles.role import RoleVariant
from cogsguard.variants import ResolvedDeps


class ScoutVariant(RoleVariant):
    """Enable the scout role: increased HP and energy."""

    name: str = "scout_role"
    description: str = "Scout role: increased HP and energy for exploration and reconnaissance."
    hp_modifier: int = 400
    energy_modifier: int = 100

    @override
    def dependencies(self) -> Deps:
        parent = super().dependencies()
        return Deps(required=parent.required, optional=[DamageVariant, EnergyVariant])

    @override
    def configure(self, deps: ResolvedDeps) -> None:
        super().configure(deps)

        d = deps.optional(DamageVariant)
        if d is not None:
            d.modifiers["scout"] = self.hp_modifier

        e = deps.optional(EnergyVariant)
        if e is not None:
            e.modifiers["scout"] = self.energy_modifier
