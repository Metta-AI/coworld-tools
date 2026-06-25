"""Game configuration for the Werecog social-deduction game."""

from __future__ import annotations

import math
from collections.abc import Sequence
from typing import cast

from pydantic import Field
from typing_extensions import Self

from mettagrid.cogame.core import CoGameMission, CoGameMissionVariant
from mettagrid.config.action_config import ActionsConfig, ChangeVibeActionConfig, MoveActionConfig, NoopActionConfig
from mettagrid.config.mettagrid_config import (
    AgentConfig,
    GameConfig,
    GridObjectConfig,
    InventoryConfig,
    MettaGridConfig,
    TalkConfig,
    WallConfig,
)
from mettagrid.config.obs_config import GlobalObsConfig, ObsConfig
from mettagrid.config.render_config import RenderAsset, RenderConfig
from mettagrid.map_builder.ascii import AsciiMapBuilder
from mettagrid.mapgen.utils.ascii_grid import DEFAULT_CHAR_TO_NAME
from werecog.defaults import (
    DEFAULT_BLIND_VISION_RADIUS,
    DEFAULT_DAY_STEPS,
    DEFAULT_EXECUTION_THRESHOLD,
    DEFAULT_FULL_VISION_RADIUS,
    DEFAULT_MAX_STEPS,
    DEFAULT_NIGHT_KILLS_PER_PHASE,
    DEFAULT_NIGHT_STEPS,
    DEFAULT_TALK_COOLDOWN_STEPS,
    DEFAULT_TALK_MAX_LENGTH,
)
from werecog.variants import HIDDEN_VARIANT_NAMES, normalize_variant_names, resolve_variant_selection


def _base_agent_config() -> AgentConfig:
    return AgentConfig(
        inventory=InventoryConfig(initial={}, limits={}),
        rewards={},
    )


def _village_line_positions(center: int, count: int) -> list[int]:
    start = center - (count - 1)
    return [start + index * 2 for index in range(count)]


def _village_ascii_map(capacity_agents: int) -> list[str]:
    per_side = max(3, math.ceil(capacity_agents / 4))
    size = max(21, 2 * per_side + 9)
    center = size // 2
    top_spawn_row = 3
    bottom_spawn_row = size - 4
    left_spawn_col = 3
    right_spawn_col = size - 4
    grid = [["." for _ in range(size)] for _ in range(size)]

    def stamp(row: int, col: int, value: str) -> None:
        grid[row][col] = value

    for index in range(size):
        stamp(0, index, "t")
        stamp(size - 1, index, "t")
        stamp(index, 0, "t")
        stamp(index, size - 1, "t")

    for index in range(1, size - 1):
        if index < center - 4 or index > center + 4:
            stamp(1, index, "t")
            stamp(size - 2, index, "t")
            stamp(index, 1, "t")
            stamp(index, size - 2, "t")

    for row, col in (
        (center - 4, center - 4),
        (center - 4, center + 4),
        (center + 4, center - 4),
        (center + 4, center + 4),
    ):
        stamp(row, col, "c")

    for row, col in (
        (center - 6, center - 6),
        (center - 6, center + 6),
        (center + 6, center - 6),
        (center + 6, center + 6),
        (center - 6, center),
        (center + 6, center),
        (center, center - 6),
        (center, center + 6),
    ):
        stamp(row, col, "t")

    for row, col in (
        (center - 2, center - 2),
        (center - 2, center + 2),
        (center + 2, center - 2),
        (center + 2, center + 2),
    ):
        stamp(row, col, "l")

    stamp(center - 5, center, "w")
    stamp(center + 5, center, "v")
    stamp(center, center, "b")

    spawn_line = _village_line_positions(center, per_side)
    spawn_positions: list[tuple[int, int]] = []
    for col in spawn_line:
        spawn_positions.append((top_spawn_row, col))
    for row in spawn_line:
        spawn_positions.append((row, right_spawn_col))
    for col in reversed(spawn_line):
        spawn_positions.append((bottom_spawn_row, col))
    for row in reversed(spawn_line):
        spawn_positions.append((row, left_spawn_col))

    for row, col in spawn_positions[:capacity_agents]:
        stamp(row, col, "@")

    return ["".join(row) for row in grid]


def _village_map_builder(capacity_agents: int) -> AsciiMapBuilder.Config:
    mapping = dict(DEFAULT_CHAR_TO_NAME)
    mapping.update(
        {
            "t": "village_tree",
            "c": "cottage",
            "l": "lantern_post",
            "v": "villager_station",
            "w": "werewolf_station",
            "b": "meeting_bell",
        }
    )
    return AsciiMapBuilder.Config(
        map_data=_village_ascii_map(capacity_agents),
        char_to_map_name=mapping,
    )


def _base_objects() -> dict[str, GridObjectConfig | WallConfig]:
    return {
        "wall": WallConfig(name="wall"),
        "village_tree": WallConfig(name="village_tree"),
        "cottage": WallConfig(name="cottage"),
        "lantern_post": WallConfig(name="lantern_post"),
        "villager_station": WallConfig(name="villager_station"),
        "werewolf_station": WallConfig(name="werewolf_station"),
        "meeting_bell": GridObjectConfig(name="meeting_bell"),
    }


class WerecogMission(CoGameMission):
    """Base Werecog mission."""

    default_variant: str | None = "full"
    max_steps: int = Field(default=DEFAULT_MAX_STEPS)
    night_steps: int = Field(default=DEFAULT_NIGHT_STEPS, ge=1)
    day_steps: int = Field(default=DEFAULT_DAY_STEPS, ge=1)
    full_vision_radius: int = Field(default=DEFAULT_FULL_VISION_RADIUS, ge=0)
    blind_vision_radius: int = Field(default=DEFAULT_BLIND_VISION_RADIUS, ge=0)
    execution_threshold_votes: int = Field(default=DEFAULT_EXECUTION_THRESHOLD, ge=1)
    night_kills_per_phase: int = Field(default=DEFAULT_NIGHT_KILLS_PER_PHASE, ge=1)

    @classmethod
    def create(cls, num_agents: int, max_steps: int) -> "WerecogMission":
        return cls(
            name="werecog",
            description="Werecog social-deduction skirmish",
            map_builder=_village_map_builder(num_agents),
            num_cogs=num_agents,
            min_cogs=1,
            max_cogs=num_agents,
            max_steps=max_steps,
            night_kills_per_phase=max(DEFAULT_NIGHT_KILLS_PER_PHASE, num_agents // 12),
        )

    @classmethod
    def variant_module_prefixes(cls) -> tuple[str, ...]:
        return ("werecog.variants.",)

    def with_variants(self, variants: Sequence[str | CoGameMissionVariant]) -> Self:
        requested_names = normalize_variant_names(
            [variant.name if isinstance(variant, CoGameMissionVariant) else variant for variant in variants]
        )
        copy = super().with_variants(requested_names)
        if any(name in HIDDEN_VARIANT_NAMES for name in requested_names):
            copy.default_variant = None
        return copy

    def _active_variant_names(self) -> list[str]:
        names: list[str] = []
        if self.default_variant:
            names.append(self.default_variant)
        names.extend(self._base_variants)
        return normalize_variant_names(names)

    def _resolved_mission(self) -> Self:
        resolved = self.model_copy(deep=True)
        resolved._variant_registry = resolve_variant_selection(self._active_variant_names())
        for variant in resolved._variant_registry.configured():
            modify_mission = getattr(variant, "modify_mission", None)
            if callable(modify_mission):
                modify_mission(resolved)
        return resolved

    def make_base_env(self) -> MettaGridConfig:
        num_cogs = cast(int, self.num_cogs)
        return MettaGridConfig(
            game=GameConfig(
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
                    change_vibe=ChangeVibeActionConfig(enabled=False),
                ),
                talk=TalkConfig(
                    enabled=True,
                    max_length=DEFAULT_TALK_MAX_LENGTH,
                    cooldown_steps=DEFAULT_TALK_COOLDOWN_STEPS,
                ),
                agents=[_base_agent_config() for _ in range(num_cogs)],
                objects=_base_objects(),
                render=RenderConfig(
                    assets={
                        "agent": [],
                        "village_tree": [RenderAsset(asset="werewolf_mafia_tree")],
                        "cottage": [RenderAsset(asset="werewolf_mafia_cottage")],
                        "lantern_post": [RenderAsset(asset="werewolf_mafia_lantern")],
                        "villager_station": [RenderAsset(asset="werewolf_mafia_villager_station")],
                        "werewolf_station": [RenderAsset(asset="werewolf_mafia_werewolf_station")],
                        "meeting_bell": [RenderAsset(asset="werewolf_mafia_meeting_bell")],
                    },
                    object_status={"agent": {}},
                    symbols={
                        "village_tree": "🌲",
                        "cottage": "🏠",
                        "lantern_post": "🏮",
                        "villager_station": "🏘",
                        "werewolf_station": "🐺",
                        "meeting_bell": "🔔",
                    },
                ),
            )
        )

    def make_env(self) -> MettaGridConfig:
        mission = self._resolved_mission()
        env = mission.make_base_env()
        mission._variant_registry.apply_to_env(mission, env)
        env.label = mission.full_name()
        return env
