"""Coherence variant: primary health resource for all entities (RULES.md sections 1, 4, 5).

Coherence is the health pool. At 0, the entity is disabled and reboots.

Agents: on_tick handlers for regen, reboot increment, and reboot restart.
Nodes: periodic events for the same, plus CogonyRebootMutation for
       level-up and stat recomputation.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, override

from cogames.core import CoGameMissionVariant
from cogony.game.channels import DMG_STATS, RES_STATS, SYS_DAMAGE_STATS
from cogony.game.teams.gear_stations import GEAR_NAMES
from mettagrid.config.event_config import EventConfig, periodic
from mettagrid.config.filter import GameValueFilter, PeriodicFilter, actorHas, isNot, targetHas
from mettagrid.config.filter.filter import HandlerTarget
from mettagrid.config.filter.vibe_filter import VibeFilter
from mettagrid.config.game_value import ConstValue, InventoryValue, Scope, SumGameValue
from mettagrid.config.handler_config import Handler, allOf, updateActor
from mettagrid.config.mettagrid_config import MettaGridConfig, ResourceLimitsConfig
from mettagrid.config.mutation import (
    ClearInventoryMutation,
    CogonyCogRebootMutation,
    CogonyExtractorRebootMutation,
    CogonyJunctionRebootMutation,
    EntityTarget,
    updateTarget,
)
from mettagrid.config.mutation.change_vibe_mutation import ChangeVibeMutation
from mettagrid.config.mutation.game_value_mutation import SetGameValueMutation
from mettagrid.config.query import query

if TYPE_CHECKING:
    from cogony.mission import CogonyMission

INITIAL_COHERENCE = 10
REGEN_PERIOD = 10


class CoherenceVariant(CoGameMissionVariant):
    """Add coherence, reboot, and heal resources to all agents and nodes."""

    name: str = "coherence"
    description: str = "Coherence health system with reboot mechanic."

    initial_coherence: int = INITIAL_COHERENCE
    regen_period: int = REGEN_PERIOD

    @override
    def modify_env(self, mission: CogonyMission, env: MettaGridConfig) -> None:
        env.game.add_resource("coherence")
        env.game.add_resource("max_coherence")
        env.game.add_resource("max_energy")
        env.game.add_resource("reboot")
        env.game.add_resource("level")
        env.game.add_resource("scrambled")
        env.game.add_resource("mobile")
        env.game.add_resource("energy")

        if "node" not in env.game.tags:
            env.game.tags.append("node")

        # -- Agent setup --
        for agent in env.game.agents:
            agent.inventory.limits.setdefault(
                "coherence",
                ResourceLimitsConfig(
                    base=20, max=65535,
                    resources=["coherence"],
                    modifiers={"core_d": 5},
                ),
            )
            agent.inventory.initial.setdefault("coherence", self.initial_coherence)

            agent.inventory.limits.setdefault(
                "max_coherence",
                ResourceLimitsConfig(base=65535, max=65535, resources=["max_coherence"]),
            )
            agent.inventory.initial.setdefault("max_coherence", 0)

            agent.inventory.limits.setdefault(
                "reboot",
                ResourceLimitsConfig(base=65535, max=65535, resources=["reboot"]),
            )
            agent.inventory.initial.setdefault("reboot", 0)

            agent.inventory.limits.setdefault(
                "energy",
                ResourceLimitsConfig(
                    base=100, max=65535, resources=["energy"],
                    modifiers={"gen_d": 25},
                ),
            )
            agent.inventory.initial.setdefault("energy", 100)

            agent.inventory.limits.setdefault(
                "max_energy",
                ResourceLimitsConfig(base=65535, max=65535, resources=["max_energy"]),
            )
            agent.inventory.initial.setdefault("max_energy", 0)

            agent.inventory.limits.setdefault(
                "scrambled",
                ResourceLimitsConfig(base=65535, max=65535, resources=["scrambled"]),
            )
            agent.inventory.initial.setdefault("scrambled", 0)

            agent.inventory.limits.setdefault(
                "mobile",
                ResourceLimitsConfig(base=1, max=1, resources=["mobile"]),
            )
            agent.inventory.initial.setdefault("mobile", 1)

            # Coherence regen: 1 + core_a every regen period.
            _coh_regen_amount = SumGameValue(
                values=[
                    ConstValue(value=1.0),
                    InventoryValue(item="core_a", scope=Scope.AGENT),
                ],
            )
            regen = Handler(
                name="coherence_regen",
                filters=[
                    PeriodicFilter(period=self.regen_period),
                    actorHas({"coherence": 1}),
                ],
                mutations=[
                    SetGameValueMutation(
                        value=InventoryValue(item="coherence", scope=Scope.AGENT),
                        target=EntityTarget.ACTOR,
                        source=_coh_regen_amount,
                    ),
                ],
            )
            # Energy regen: 1 + gen_a per regen period.
            _energy_regen_amount = SumGameValue(
                values=[
                    ConstValue(value=1.0),
                    InventoryValue(item="gen_a", scope=Scope.AGENT),
                ],
            )
            energy_regen = Handler(
                name="energy_regen",
                filters=[
                    PeriodicFilter(period=self.regen_period),
                    actorHas({"coherence": 1}),
                ],
                mutations=[
                    SetGameValueMutation(
                        value=InventoryValue(item="energy", scope=Scope.AGENT),
                        target=EntityTarget.ACTOR,
                        source=_energy_regen_amount,
                    ),
                ],
            )
            _max_coh_value = SumGameValue(
                values=[
                    ConstValue(value=10.0),
                    InventoryValue(item="core_d", scope=Scope.AGENT),
                ],
                weights=[1.0, 5.0],
            )
            reboot_decrement = Handler(
                name="reboot_decrement",
                filters=[
                    isNot(actorHas({"coherence": 1})),
                    actorHas({"reboot": 2}),
                ],
                mutations=[updateActor({"reboot": -1})],
            )
            reboot_restart = Handler(
                name="reboot_restart",
                filters=[
                    isNot(actorHas({"coherence": 1})),
                    actorHas({"reboot": 1}),
                    isNot(actorHas({"reboot": 2})),
                ],
                mutations=[
                    CogonyCogRebootMutation(
                        health="coherence",
                        reboot="reboot",
                        gear_stats=list(GEAR_NAMES),
                    ),
                    ClearInventoryMutation(target=EntityTarget.ACTOR, limit_name="scrambled"),
                    updateActor({"mobile": 1}),
                ],
            )
            reboot_init = Handler(
                name="reboot_init",
                filters=[
                    isNot(actorHas({"coherence": 1})),
                    isNot(actorHas({"reboot": 1})),
                ],
                mutations=[
                    SetGameValueMutation(
                        value=InventoryValue(item="reboot", scope=Scope.AGENT),
                        target=EntityTarget.ACTOR,
                        source=_max_coh_value,
                    ),
                ],
            )

            _vibe_patch = VibeFilter(target=HandlerTarget.ACTOR, vibe="patch")
            # Patch vibe: drain 10 energy per tick, heal self 10*core_a coherence.
            _self_heal_amount = SumGameValue(
                values=[InventoryValue(item="core_a", scope=Scope.AGENT)],
                weights=[10.0],
            )
            patch_self = Handler(
                name="patch_vibe_self_heal",
                filters=[_vibe_patch, actorHas({"energy": 10, "coherence": 1})],
                mutations=[
                    SetGameValueMutation(
                        value=InventoryValue(item="coherence", scope=Scope.AGENT),
                        target=EntityTarget.ACTOR,
                        source=_self_heal_amount,
                    ),
                    updateActor({"energy": -10}),
                ],
            )
            # Auto-reset heal vibe when coherence is at max (100 + core_d).
            _coherence_at_max = SumGameValue(
                values=[
                    InventoryValue(item="coherence", scope=Scope.AGENT),
                    ConstValue(value=-100.0),
                    InventoryValue(item="core_d", scope=Scope.AGENT),
                ],
                weights=[1.0, 1.0, -1.0],
            )
            patch_reset_full = Handler(
                name="patch_vibe_reset_full",
                filters=[
                    _vibe_patch,
                    GameValueFilter(value=_coherence_at_max, min=0, target=HandlerTarget.ACTOR),
                ],
                mutations=[ChangeVibeMutation(target=EntityTarget.ACTOR, vibe_name="default")],
            )
            # Auto-reset heal vibe when out of energy.
            patch_reset_no_energy = Handler(
                name="patch_vibe_reset_no_energy",
                filters=[_vibe_patch, isNot(actorHas({"energy": 10}))],
                mutations=[ChangeVibeMutation(target=EntityTarget.ACTOR, vibe_name="default")],
            )

            _max_coh_value = SumGameValue(
                values=[
                    ConstValue(value=10.0),
                    InventoryValue(item="core_d", scope=Scope.AGENT),
                ],
                weights=[1.0, 5.0],
            )
            sync_max_coherence = Handler(
                name="sync_max_coherence",
                mutations=[
                    ClearInventoryMutation(target=EntityTarget.ACTOR, limit_name="max_coherence"),
                    SetGameValueMutation(
                        value=InventoryValue(item="max_coherence", scope=Scope.AGENT),
                        target=EntityTarget.ACTOR,
                        source=_max_coh_value,
                    ),
                ],
            )
            # Sync max_energy = 100 + 25*gen_d each tick.
            _max_energy_value = SumGameValue(
                values=[
                    ConstValue(value=100.0),
                    InventoryValue(item="gen_d", scope=Scope.AGENT),
                ],
                weights=[1.0, 25.0],
            )
            sync_max_energy = Handler(
                name="sync_max_energy",
                mutations=[
                    ClearInventoryMutation(target=EntityTarget.ACTOR, limit_name="max_energy"),
                    SetGameValueMutation(
                        value=InventoryValue(item="max_energy", scope=Scope.AGENT),
                        target=EntityTarget.ACTOR,
                        source=_max_energy_value,
                    ),
                ],
            )

            scrambled_decrement = Handler(
                name="scrambled_decrement",
                filters=[actorHas({"scrambled": 1})],
                mutations=[updateActor({"scrambled": -1})],
            )
            scrambled_clear = Handler(
                name="scrambled_restore_mobile",
                filters=[
                    isNot(actorHas({"scrambled": 1})),
                    isNot(actorHas({"mobile": 1})),
                    actorHas({"coherence": 1}),
                ],
                mutations=[updateActor({"mobile": 1})],
            )
            disable_mobile = Handler(
                name="disable_mobile_on_death",
                filters=[
                    isNot(actorHas({"coherence": 1})),
                    actorHas({"mobile": 1}),
                ],
                mutations=[updateActor({"mobile": -1})],
            )

            agent.on_tick = allOf([
                agent.on_tick, sync_max_coherence, sync_max_energy, regen, energy_regen,
                reboot_restart, reboot_init, reboot_decrement,
                scrambled_decrement, scrambled_clear, disable_mobile,
                patch_self, patch_reset_full, patch_reset_no_energy,
            ])

        # -- Node events --
        max_steps = mission.max_steps or 100000
        every_tick = periodic(1, 1, end=max_steps)
        regen_ticks = periodic(self.regen_period, self.regen_period, end=max_steps)

        # Node reboot: countdown from 10 + 5*core_d, same as agents.
        # Init: set reboot = 10 + 5*core_d when coherence=0 and reboot=0.
        _node_max_coh = SumGameValue(
            values=[
                ConstValue(value=10.0),
                InventoryValue(item="core_d", scope=Scope.TARGET),
            ],
            weights=[1.0, 5.0],
        )
        env.game.events["node_reboot_init"] = EventConfig(
            name="node_reboot_init",
            target_query=query("node", [
                isNot(targetHas({"coherence": 1})),
                isNot(targetHas({"reboot": 1})),
            ]),
            timesteps=every_tick,
            max_targets=None,
            mutations=[
                SetGameValueMutation(
                    value=InventoryValue(item="reboot", scope=Scope.AGENT),
                    target=EntityTarget.TARGET,
                    source=_node_max_coh,
                ),
            ],
        )

        # Decrement: -1 reboot per tick while reboot >= 2.
        env.game.events["node_reboot_decrement"] = EventConfig(
            name="node_reboot_decrement",
            target_query=query("node", [
                isNot(targetHas({"coherence": 1})),
                targetHas({"reboot": 2}),
            ]),
            timesteps=every_tick,
            max_targets=None,
            mutations=[updateTarget({"reboot": -1})],
        )

        # Restart: when reboot = 1 (countdown complete).
        env.game.events["node_reboot_restart"] = EventConfig(
            name="node_reboot_restart",
            target_query=query(
                "node",
                [
                    isNot(targetHas({"coherence": 1})),
                    targetHas({"reboot": 1}),
                    isNot(targetHas({"reboot": 2})),
                ],
            ),
            timesteps=every_tick,
            max_targets=None,
            mutations=[
                CogonyExtractorRebootMutation(
                    health="coherence",
                    reboot="reboot",
                    level="level",
                    resist_stats=list(RES_STATS),
                    dmg_stats=list(DMG_STATS),
                    sys_damage_stats=list(SYS_DAMAGE_STATS),
                    coherence_per_level=20,
                    dmg_level_offset=-3,
                ),
            ],
        )

        # Regen: 1 + core_a coherence per regen_period when alive.
        _node_regen_amount = SumGameValue(
            values=[
                ConstValue(value=1.0),
                InventoryValue(item="core_a", scope=Scope.TARGET),
            ],
        )
        env.game.events["node_regen"] = EventConfig(
            name="node_regen",
            target_query=query("node", [targetHas({"coherence": 1})]),
            timesteps=regen_ticks,
            max_targets=None,
            mutations=[
                SetGameValueMutation(
                    value=InventoryValue(item="coherence", scope=Scope.AGENT),
                    target=EntityTarget.TARGET,
                    source=_node_regen_amount,
                ),
            ],
        )
