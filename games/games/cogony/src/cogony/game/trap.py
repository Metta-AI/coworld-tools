"""Trap and Jump abilities: vibe-triggered move handlers."""

from __future__ import annotations

from typing import TYPE_CHECKING, override

from mettagrid.cogame.core import CoGameMissionVariant, Deps
from cogony.game.vibes import VibesVariant
from mettagrid.config.event_config import EventConfig, periodic
from mettagrid.config.filter import TargetLocEmptyFilter, targetHas, isNot
from mettagrid.config.filter.vibe_filter import VibeFilter
from mettagrid.config.filter.filter import HandlerTarget
from mettagrid.config.handler_config import Handler
from mettagrid.config.mettagrid_config import GridObjectConfig, InventoryConfig, MettaGridConfig, ResourceLimitsConfig
from mettagrid.config.mutation import (
    CogonyJumpMutation,
    CogonyTrapDropMutation,
    CogonyTrapTriggerMutation,
    updateTarget,
)
from mettagrid.config.render_config import RenderAsset
from mettagrid.config.query import query

if TYPE_CHECKING:
    from cogony.mission import CogonyMission

TRAP_DAMAGE = 5
TRAP_SCRAMBLE = 10
TRAP_TTL = 5


class TrapVariant(CoGameMissionVariant):
    """Trap + Jump vibes as move handlers."""

    name: str = "trap"
    description: str = "Trap drops behind agent on move; Jump moves 2 cells."

    @override
    def dependencies(self) -> Deps:
        return Deps(required=[VibesVariant])

    @override
    def modify_env(self, mission: CogonyMission, env: MettaGridConfig) -> None:
        trap_handler = Handler(
            name="trap_move",
            filters=[
                VibeFilter(target=HandlerTarget.ACTOR, vibe="trap"),
                TargetLocEmptyFilter(),
            ],
            mutations=[
                CogonyTrapDropMutation(
                    object_type="trap",
                    initial_resources={"coherence": TRAP_TTL, "core_a": TRAP_DAMAGE},
                ),
            ],
        )

        jump_empty = Handler(
            name="jump_move_empty",
            filters=[
                VibeFilter(target=HandlerTarget.ACTOR, vibe="jump"),
                TargetLocEmptyFilter(),
            ],
            mutations=[CogonyJumpMutation()],
        )
        jump_occupied = Handler(
            name="jump_move_occupied",
            filters=[
                VibeFilter(target=HandlerTarget.ACTOR, vibe="jump"),
            ],
            mutations=[CogonyJumpMutation()],
        )

        env.game.actions.move.handlers.insert(0, jump_occupied)
        env.game.actions.move.handlers.insert(0, jump_empty)
        env.game.actions.move.handlers.insert(0, trap_handler)

        env.game.objects.setdefault("trap", GridObjectConfig(
            name="trap",
            map_name="trap",
            tags=["trap"],
            inventory=InventoryConfig(
                limits={
                    "coherence": ResourceLimitsConfig(base=TRAP_TTL, max=TRAP_TTL, resources=["coherence"]),
                },
                initial={"coherence": TRAP_TTL, "core_a": TRAP_DAMAGE},
            ),
            on_use_handler=Handler(
                name="trigger_trap",
                filters=[targetHas({"coherence": 1})],
                mutations=[
                    CogonyTrapTriggerMutation(
                        damage=TRAP_DAMAGE,
                        scramble_ticks=TRAP_SCRAMBLE,
                    ),
                ],
            ),
        ))
        env.game.render.symbols["trap"] = "🪤"
        env.game.render.assets["trap"] = [RenderAsset(asset="trap")]

        if "trap" not in env.game.tags:
            env.game.tags.append("trap")

        max_steps = mission.max_steps or 100000
        every_tick = periodic(1, 1, end=max_steps)
        env.game.events["trap_tick"] = EventConfig(
            name="trap_tick",
            target_query=query("trap"),
            timesteps=every_tick,
            max_targets=None,
            mutations=[
                CogonyTrapTriggerMutation(damage=0, scramble_ticks=0),
            ],
            filters=[isNot(targetHas({"coherence": 1}))],
        )
        env.game.events["trap_decay"] = EventConfig(
            name="trap_decay",
            target_query=query("trap", [targetHas({"coherence": 1})]),
            timesteps=every_tick,
            max_targets=None,
            mutations=[updateTarget({"coherence": -1})],
        )
