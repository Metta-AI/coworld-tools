"""Core game definition for the cogame template.

This module defines:

* ``MyMission`` — a :class:`cogame.framework.CoGameMission` subclass whose
  ``make_base_env`` builds a tiny but valid :class:`MettaGridConfig`. Variants
  (see ``cogame.variants``) can stack on top via the standard lifecycle.
* ``MyCoGame`` — a :class:`cogame.framework.CoGame` subclass that advertises
  the mission set and variant registry.
* ``register_game(MyCoGame())`` at module bottom, so ``import cogame`` is
  enough to register the game with :func:`cogame.framework.get_game`.

TODO(cogame): Replace ``MyMission`` / ``MyCoGame`` with names specific to your
game, and rewrite ``_default_map`` + ``make_base_env`` for your mechanics.
"""

from __future__ import annotations

from typing import cast

from mettagrid.config.action_config import ActionsConfig, MoveActionConfig, NoopActionConfig
from mettagrid.config.handler_config import Handler
from mettagrid.config.mettagrid_config import (
    AgentConfig,
    GameConfig,
    GridObjectConfig,
    InventoryConfig,
    MettaGridConfig,
    ResourceLimitsConfig,
    WallConfig,
)
from mettagrid.config.mutation import withdraw
from mettagrid.config.reward_config import inventoryReward
from mettagrid.map_builder.ascii import AsciiMapBuilder

from cogame.defaults import (
    DEFAULT_HP,
    DEFAULT_MAX_STEPS,
    DEFAULT_MINE_AMOUNT,
    DEFAULT_NUM_AGENTS,
    DEFAULT_ORE_CAP,
    DEFAULT_VEIN_ORE,
)
from cogame.framework import CoGame, CoGameMission, register_game
from cogame.variants import ALL_VARIANT_TYPES

# ===== Resources =====
# TODO(cogame): rename / extend with the resources your game actually needs.

RESOURCE_NAMES: list[str] = [
    "ore",
    "hp",
]


# ===== Default map =====
# TODO(cogame): replace with your own ASCII map, or swap in a procedural
# generator from ``mettagrid.mapgen``. Keep at least 2 agent spawns (`@`) and
# at least one interactable object so the default mission stays playable.
DEFAULT_MAP: list[str] = [
    "#########",
    "#@......#",
    "#..###..#",
    "#..#V#..#",
    "#..###..#",
    "#.......#",
    "#......@#",
    "#########",
    "#########",
]

_CHAR_TO_MAP_NAME: dict[str, str] = {
    "#": "wall",
    ".": "empty",
    "@": "agent.agent",
    "V": "ore_vein",
}


def _default_map_builder() -> AsciiMapBuilder.Config:
    return AsciiMapBuilder.Config(
        map_data=[list(row) for row in DEFAULT_MAP],
        char_to_map_name=_CHAR_TO_MAP_NAME,
    )


# ===== Mission =====


class MyMission(CoGameMission):
    """Placeholder mission. Agents walk to an ore_vein and mine ore for reward.

    TODO(cogame): rename this class to match your game. Add fields for any
    per-mission parameters your variants need to read.
    """

    @classmethod
    def create(
        cls,
        *,
        num_agents: int = DEFAULT_NUM_AGENTS,
        max_steps: int = DEFAULT_MAX_STEPS,
    ) -> MyMission:
        return cls(
            name="default",
            description="Placeholder 2-agent mining mission. Replace me!",
            map_builder=_default_map_builder(),
            num_cogs=num_agents,
            min_cogs=1,
            max_cogs=8,
            max_steps=max_steps,
        )

    def make_base_env(self) -> MettaGridConfig:
        num_cogs = cast(int, self.num_cogs)

        # TODO(cogame): shape the agent's inventory, limits and rewards for your game.
        agent = AgentConfig(
            inventory=InventoryConfig(
                initial={"ore": 0, "hp": DEFAULT_HP},
                limits={
                    "ore": ResourceLimitsConfig(
                        base=DEFAULT_ORE_CAP, max=DEFAULT_ORE_CAP, resources=["ore"]
                    ),
                    "hp": ResourceLimitsConfig(
                        base=DEFAULT_HP, max=DEFAULT_HP, resources=["hp"]
                    ),
                },
            ),
            rewards={"ore": inventoryReward("ore", weight=1.0, per_tick=True)},
        )

        # TODO(cogame): add more objects — crafting stations, goals, terrain.
        ore_vein = GridObjectConfig(
            name="ore_vein",
            inventory=InventoryConfig(
                initial={"ore": DEFAULT_VEIN_ORE},
                limits={
                    "ore": ResourceLimitsConfig(
                        base=DEFAULT_VEIN_ORE,
                        max=DEFAULT_VEIN_ORE,
                        resources=["ore"],
                    ),
                },
            ),
            on_use_handler=Handler(
                name="mine",
                mutations=[withdraw({"ore": DEFAULT_MINE_AMOUNT})],
            ),
        )

        game = GameConfig(
            map_builder=self.map_builder,
            max_steps=self.max_steps,
            num_agents=num_cogs,
            resource_names=list(RESOURCE_NAMES),
            actions=ActionsConfig(
                noop=NoopActionConfig(),
                move=MoveActionConfig(),
            ),
            agents=[agent.model_copy(deep=True) for _ in range(num_cogs)],
            objects={
                "wall": WallConfig(name="wall"),
                "ore_vein": ore_vein,
            },
        )
        return MettaGridConfig(game=game)


# ===== CoGame registration =====


class MyCoGame(CoGame):
    """Framework-facing handle for this template game.

    TODO(cogame): rename to match your game (e.g. ``MyMiningCoGame``) and
    add eval missions under ``eval_missions`` when you have them.
    """

    def __init__(self) -> None:
        super().__init__(
            name="coghouse",
            missions=[MyMission.create()],
            variants=[cls() for cls in ALL_VARIANT_TYPES],
        )


register_game(MyCoGame())
