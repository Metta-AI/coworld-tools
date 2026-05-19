from __future__ import annotations

from pydantic import Field
from typing_extensions import Self

from cogames.core import CoGameMission
from cogony.terrain import find_arena
from mettagrid.config.action_config import ActionsConfig, MoveActionConfig, NoopActionConfig
from mettagrid.config.mettagrid_config import AgentConfig, GameConfig, MettaGridConfig, WallConfig
from mettagrid.config.obs_config import GlobalObsConfig, ObsConfig
from mettagrid.config.render_config import RenderConfig
from mettagrid.mapgen.mapgen import MapGenConfig

from cogony.base import _build_base_map_builder
from cogony.game.teams.cogony import CogonyVariant


class CogonyMission(CoGameMission):
    """cogony mission: base gameplay + 4-team corner compounds."""

    name: str = "cogony"
    description: str = "Multi-team corner bases competing for junction control."
    map_builder: MapGenConfig = Field(default_factory=lambda: _build_base_map_builder(16))
    num_cogs: int = 16
    min_cogs: int = 4
    max_cogs: int = 80
    max_steps: int = 10000
    default_variant: str = "base"
    num_agents: int = 16
    god_mode: bool = False

    @classmethod
    def variant_module_prefixes(cls) -> tuple[str, ...]:
        return ("cogony.",)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._base_variants["cogony"] = CogonyVariant()

    def with_cogs(self, cogs: int) -> Self:
        return self.model_copy(deep=True, update={"num_cogs": cogs, "num_agents": cogs})

    def with_god_mode(self) -> Self:
        return self.model_copy(deep=True, update={"god_mode": True})

    def make_base_env(self) -> MettaGridConfig:
        return MettaGridConfig(
            game=GameConfig(
                map_builder=self.map_builder,
                max_steps=self.max_steps,
                num_agents=self.num_agents,
                resource_names=[],
                obs=ObsConfig(
                    global_obs=GlobalObsConfig(
                        local_position=True,
                        last_action_move=True,
                    ),
                    aoe_mask=True,
                ),
                actions=ActionsConfig(
                    move=MoveActionConfig(required_resources={"mobile": 1}),
                    noop=NoopActionConfig(),
                ),
                agents=[AgentConfig() for _ in range(self.num_agents)],
                objects={"wall": WallConfig(name="wall")},
                render=RenderConfig(symbols={"wall": "⬛"}),
                events={},
            )
        )
