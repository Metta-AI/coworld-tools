"""Standalone game registration for HungerCog."""

from __future__ import annotations

from collections.abc import Sequence
from typing import cast

from pydantic import Field

from cogames.core import CoGameMission
from cogames.game import CoGame, register_game
from hungercog.variants import VARIANTS
from mettagrid.config.action_config import ActionsConfig, MoveActionConfig, NoopActionConfig
from mettagrid.config.mettagrid_config import (
    AgentConfig,
    GameConfig,
    InventoryConfig,
    MettaGridConfig,
    ResourceLimitsConfig,
    WallConfig,
)
from mettagrid.config.obs_config import GlobalObsConfig, ObsConfig
from mettagrid.config.render_config import RenderConfig
from mettagrid.mapgen.mapgen import MapGen
from mettagrid.mapgen.scenes.biome_arena import BiomeArena
from mettagrid.mapgen.scenes.compound import Compound

DEFAULT_NUM_AGENTS = 40
DEFAULT_MAX_STEPS = 250
DEFAULT_POLICY_URI = "metta://policy/hungercog.agent.hunger_agent.policy.HungerPolicy"
DEFAULT_POLICY_PACKAGES = ["hungercog.agent.hunger_agent"]


class HungerMission(CoGameMission):
    default_variant: str = "full"
    max_steps: int = Field(default=DEFAULT_MAX_STEPS)  # 1 year; use multi_year_5 or multi_year_10 for longer

    @classmethod
    def create(cls, num_agents: int, max_steps: int) -> HungerMission:
        return cls(
            name="hungercog",
            description="HungerCog survival mission",
            map_builder=cls._map_builder(num_agents),
            num_cogs=num_agents,
            min_cogs=1,
            max_cogs=num_agents,
            max_steps=max_steps,
        )

    def make_base_env(self) -> MettaGridConfig:
        num_cogs = cast(int, self.num_cogs)  # always set by create()
        game = GameConfig(
            map_builder=self.map_builder,
            max_steps=self.max_steps,
            num_agents=num_cogs,
            resource_names=[],
            obs=ObsConfig(
                global_obs=GlobalObsConfig(
                    local_position=True,
                    last_action_move=True,
                ),
            ),
            actions=ActionsConfig(
                move=MoveActionConfig(),
                noop=NoopActionConfig(),
            ),
            agents=[
                AgentConfig(
                    inventory=InventoryConfig(
                        limits={
                            "gear": ResourceLimitsConfig(base=1, max=1, resources=[]),
                        },
                    ),
                    rewards={},
                )
                for _ in range(num_cogs)
            ],
            objects={
                "wall": WallConfig(name="wall"),
            },
            render=RenderConfig(
                assets={
                    "agent": [],
                },
                object_status={"agent": {}},
            ),
        )
        return MettaGridConfig(game=game)

    @staticmethod
    def _map_builder(num_agents: int) -> MapGen.Config:
        return MapGen.Config(
            width=88,
            height=88,
            instance=BiomeArena.Config(
                spawn_count=80,
                base_biome="forest",
                base_biome_config={"seed_prob": 0.015},
                building_coverage=0,
                building_names=[],
                building_weights={},
                biome_weights={"forest": 1.0},
                dungeon_weights={"none": 1.0},
                hub=Compound.Config(
                    spawn_count=num_agents,
                    hub_object="empty",
                    corner_bundle="none",
                    cross_bundle="none",
                    cross_distance=7,
                    randomize_spawn_positions=True,
                ),
            ),
        )


class HungerCogGame(CoGame):
    def __init__(self) -> None:
        super().__init__(
            name="hungercog",
            missions=[HungerMission.create(DEFAULT_NUM_AGENTS, DEFAULT_MAX_STEPS)],
            variants=VARIANTS,
        )


def register_with_metta() -> None:
    from metta.games.games import GAMES, register

    if "hungercog" in GAMES:
        return
    register(
        "hungercog",
        HungerMission,
        policy_uri=DEFAULT_POLICY_URI,
        policy_packages=DEFAULT_POLICY_PACKAGES,
    )


def make_game(
    name: str = "hungercog",
    *,
    num_agents: int,
    max_steps: int,
    variants: Sequence[str] | None = None,
) -> MettaGridConfig:
    if name != "hungercog":
        raise ValueError(f"Unknown game {name!r}. Available: hungercog")

    mission = HungerMission.create(num_agents, max_steps)
    if variants is not None:
        mission = mission.with_variants(list(variants))
        mission.default_variant = None
    return mission.make_env()


register_game(HungerCogGame())
