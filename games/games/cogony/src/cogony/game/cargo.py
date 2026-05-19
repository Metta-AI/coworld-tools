"""Cargo variant: gives agents inventory space for carrying elements."""

from __future__ import annotations

from typing import TYPE_CHECKING, override

from pydantic import Field

from cogames.core import CoGameMissionVariant, Deps
from cogony.game.elements import ElementsVariant
from cogames.variants import ResolvedDeps
from mettagrid.config.game_value import ConstValue, InventoryValue, Scope, SumGameValue
from mettagrid.config.handler_config import Handler
from mettagrid.config.mettagrid_config import MettaGridConfig, ResourceLimitsConfig
from mettagrid.config.mutation import ClearInventoryMutation, EntityTarget
from mettagrid.config.mutation.game_value_mutation import SetGameValueMutation

if TYPE_CHECKING:
    from cogony.mission import CogonyMission


class CargoLimitVariant(CoGameMissionVariant):
    """Add a cargo inventory limit to all agents so they can carry elements."""

    name: str = "cargo_limit"
    description: str = "Agents can carry elements (oxygen, carbon, germanium, silicon)."

    limit: int = Field(default=100)
    modifiers: dict[str, int] = Field(default_factory=dict)

    @override
    def dependencies(self) -> Deps:
        return Deps(required=[ElementsVariant])

    @override
    def configure(self, deps: ResolvedDeps) -> None:
        deps.required(ElementsVariant)

    @override
    def modify_env(self, mission: CogonyMission, env: MettaGridConfig) -> None:
        elements = mission.required_variant(ElementsVariant).elements
        env.game.add_resource("cargo")
        env.game.add_resource("max_cargo")
        for agent in env.game.agents:
            agent.inventory.limits.setdefault(
                "cargo",
                ResourceLimitsConfig(
                    base=self.limit,
                    resources=elements,
                    modifiers={"storage_d": 25, **self.modifiers},
                ),
            )
            agent.inventory.initial.setdefault("cargo", 0)

            agent.inventory.limits.setdefault(
                "max_cargo",
                ResourceLimitsConfig(base=65535, max=65535, resources=["max_cargo"]),
            )
            agent.inventory.initial.setdefault("max_cargo", 0)

            _max_cargo_value = SumGameValue(
                values=[
                    ConstValue(value=float(self.limit)),
                    InventoryValue(item="storage_d", scope=Scope.AGENT),
                ],
                weights=[1.0, 25.0],
            )
            sync_max_cargo = Handler(
                name="sync_max_cargo",
                mutations=[
                    ClearInventoryMutation(target=EntityTarget.ACTOR, limit_name="max_cargo"),
                    SetGameValueMutation(
                        value=InventoryValue(item="max_cargo", scope=Scope.AGENT),
                        target=EntityTarget.ACTOR,
                        source=_max_cargo_value,
                    ),
                ],
            )
            from mettagrid.config.handler_config import allOf
            agent.on_tick = allOf([agent.on_tick, sync_max_cargo])
