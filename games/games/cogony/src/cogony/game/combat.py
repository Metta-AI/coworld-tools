"""Combat resolution and bump dispatch (RULES.md sections 1 and 2).

Uses custom C++ mutations for all combat, healing, and looting.

Bump dispatch (default vibe):
    Extractor  coh>0  -> attack
    Extractor  coh=0  -> loot (creds + elements)
    Junction   coh>0  -> attack
    Junction   coh=0  -> align to bumper's team
    Cog same-team coh>0 -> heal
    Cog other/teamless coh>0 -> attack
    Cog any coh=0     -> loot (elements + gear)

Vibe overrides:
    vibe_attack -> all bumps resolve as attack
    vibe_patch  -> heal target for 10 coherence, costs 10 energy
"""

from __future__ import annotations

import random
from typing import TYPE_CHECKING, override

from mettagrid.cogame.core import CoGameMissionVariant, Deps
from cogony.game.channels import CHANNEL_GEAR, CHANNEL_STATS, DMG_STATS, SYS_DAMAGE_STATS, ChannelsVariant
from cogony.game.coherence import CoherenceVariant
from cogony.game.elements import ElementsVariant
from cogony.game.datacenter import DatacenterVariant
from cogony.game.extractors import ExtractorsVariant
from cogony.game.junction import JunctionVariant
from cogony.game.observatory import ObservatoryVariant
from cogony.game.teams.team import TeamVariant
from cogony.game.vibes import VibesVariant
from mettagrid.config.filter import actorHas, isNear, isNot, targetHas
from mettagrid.config.filter.filter import HandlerTarget
from mettagrid.config.filter.shared_tag_prefix_filter import SharedTagPrefixFilter
from mettagrid.config.filter.vibe_filter import VibeFilter
from mettagrid.config.handler_config import (
    Handler,
    actorHasTag,
    addTag,
    firstMatch,
    removeTagPrefix,
    updateActor,
)
from mettagrid.config.mutation import recomputeMaterializedQuery
from mettagrid.config.mettagrid_config import MettaGridConfig, ResourceLimitsConfig
from mettagrid.config.mutation import (
    CogonyAttackMutation,
    CogonyLootMutation,
    EntityTarget,
    ResourceTransferMutation,
    SwapMutation,
    updateTarget,
)
from mettagrid.config.mutation.game_value_mutation import SetGameValueMutation
from mettagrid.config.game_value import InventoryValue, Scope, SumGameValue

if TYPE_CHECKING:
    from cogony.mission import CogonyMission


# ---------------------------------------------------------------------------
# Filters
# ---------------------------------------------------------------------------

_target_alive = targetHas({"coherence": 1})
_target_dead = isNot(_target_alive)
_vibe_attack = VibeFilter(target=HandlerTarget.ACTOR, vibe="attack")
_vibe_patch = VibeFilter(target=HandlerTarget.ACTOR, vibe="patch")
_vibe_cred = VibeFilter(target=HandlerTarget.ACTOR, vibe="cred")
_vibe_heart = VibeFilter(target=HandlerTarget.ACTOR, vibe="heart")
_vibe_swap = VibeFilter(target=HandlerTarget.ACTOR, vibe="swap")
_has_energy = actorHas({"energy": 10})

# ---------------------------------------------------------------------------
# Mutations (one instance each, shared across all handlers)
# ---------------------------------------------------------------------------

ATTACK = CogonyAttackMutation(
    channels=list(CHANNEL_GEAR),
    health="coherence",
    damage_tracking=list(SYS_DAMAGE_STATS),
    strike_back=True,
)

HEAL = [updateTarget({"coherence": 10})]

_HEAL_AMOUNT = SumGameValue(
    values=[InventoryValue(item="core_a", scope=Scope.AGENT)],
    weights=[10.0],
)
HEAL_VIBE_BUMP = [
    SetGameValueMutation(
        value=InventoryValue(item="coherence", scope=Scope.AGENT),
        target=EntityTarget.TARGET,
        source=_HEAL_AMOUNT,
    ),
    updateActor({"energy": -10}),
]

GIVE_CREDS = ResourceTransferMutation(
    from_target=EntityTarget.ACTOR,
    to_target=EntityTarget.TARGET,
    resources={"creds": 10},
)

GIVE_HEART = ResourceTransferMutation(
    from_target=EntityTarget.ACTOR,
    to_target=EntityTarget.TARGET,
    resources={"heart": 1},
)

LOOT_EXTRACTOR = CogonyLootMutation(
    resources=["creds", "carbon", "oxygen", "germanium", "silicon"],
)

LOOT_COG = CogonyLootMutation(
    resources=[
        "carbon", "oxygen", "germanium", "silicon",
        *[g for pair in CHANNEL_GEAR for g in pair],
    ],
)


# ---------------------------------------------------------------------------
# CombatVariant
# ---------------------------------------------------------------------------

class CombatVariant(CoGameMissionVariant):
    """Install combat resolution and bump dispatch on extractors, junctions, and agents."""

    name: str = "combat"
    description: str = "Combat resolution and bump dispatch (RULES.md sections 1-2)."

    @override
    def dependencies(self) -> Deps:
        return Deps(
            required=[
                CoherenceVariant,
                ChannelsVariant,
                DatacenterVariant,
                ExtractorsVariant,
                JunctionVariant,
                ObservatoryVariant,
                TeamVariant,
                VibesVariant,
                ElementsVariant,
            ]
        )

    @override
    def modify_env(self, mission: CogonyMission, env: MettaGridConfig) -> None:
        channels_v = mission.required_variant(ChannelsVariant)
        team_v = mission.required_variant(TeamVariant)
        all_teams = list(team_v.teams.values())

        # Ensure all objects have channel stats + sys_damage resources.
        for obj in env.game.objects.values():
            for stat in [*CHANNEL_STATS, *SYS_DAMAGE_STATS]:
                obj.inventory.limits.setdefault(
                    stat,
                    ResourceLimitsConfig(
                        base=channels_v.stat_cap,
                        max=channels_v.stat_cap,
                        resources=[stat],
                    ),
                )
                obj.inventory.initial.setdefault(stat, 0)

        # Give each agent one random attack gear.
        for agent in env.game.agents:
            atk = random.choice(DMG_STATS)
            agent.inventory.initial[atk] = agent.inventory.initial.get(atk, 0) + 1

        # ---------------------------------------------------------------
        # Extractor handlers
        # ---------------------------------------------------------------
        for el in mission.required_variant(ElementsVariant).elements:
            key = f"{el}_extractor"
            obj = env.game.objects.get(key)
            if obj is None:
                continue

            # Per-element attack mutation: drops the extractor's element on kill.
            el_attack = CogonyAttackMutation(
                channels=list(CHANNEL_GEAR),
                health="coherence",
                damage_tracking=list(SYS_DAMAGE_STATS),
                strike_back=True,
                drop_resource=el,
                drop_level="level",
                drop_multiplier=10,
            )

            obj.on_use_handler = firstMatch([
                Handler(name=f"vibe_attack_{key}", filters=[_vibe_attack], mutations=[el_attack]),
                Handler(name=f"vibe_patch_{key}", filters=[_vibe_patch, _has_energy], mutations=HEAL_VIBE_BUMP),
                Handler(name=f"attack_{key}", filters=[_target_alive], mutations=[el_attack]),
                Handler(name=f"collect_{key}", filters=[_target_dead], mutations=[LOOT_EXTRACTOR]),
            ])

        # ---------------------------------------------------------------
        # Junction handlers
        # ---------------------------------------------------------------
        junction_obj = env.game.objects.get("junction")
        if junction_obj is not None:
            align_handlers = [
                Handler(
                    name=f"align_junction_{team.name}",
                    filters=[
                        _target_dead,
                        actorHasTag(team.team_tag()),
                        isNear(team.net_tag(), radius=25),
                    ],
                    mutations=[
                        removeTagPrefix("team:", target=EntityTarget.TARGET),
                        addTag(team.team_tag(), target=EntityTarget.TARGET),
                        recomputeMaterializedQuery(team.net_tag()),
                    ],
                )
                for team in all_teams
            ]

            junction_obj.on_use_handler = firstMatch([
                Handler(name="vibe_attack_junction", filters=[_vibe_attack], mutations=[ATTACK]),
                Handler(name="vibe_patch_junction", filters=[_vibe_patch, _has_energy], mutations=HEAL_VIBE_BUMP),
                Handler(name="attack_junction", filters=[_target_alive], mutations=[ATTACK]),
                *align_handlers,
            ])

        # ---------------------------------------------------------------
        # Observatory handlers (same as junction: hack + align)
        # ---------------------------------------------------------------
        observatory_obj = env.game.objects.get("observatory")
        if observatory_obj is not None:
            align_obs = [
                Handler(
                    name=f"align_observatory_{team.name}",
                    filters=[
                        _target_dead,
                        actorHasTag(team.team_tag()),
                        isNear(team.net_tag(), radius=25),
                    ],
                    mutations=[
                        removeTagPrefix("team:", target=EntityTarget.TARGET),
                        addTag(team.team_tag(), target=EntityTarget.TARGET),
                        recomputeMaterializedQuery(team.net_tag()),
                    ],
                )
                for team in all_teams
            ]
            observatory_obj.on_use_handler = firstMatch([
                Handler(name="vibe_attack_observatory", filters=[_vibe_attack], mutations=[ATTACK]),
                Handler(name="vibe_patch_observatory", filters=[_vibe_patch, _has_energy], mutations=HEAL_VIBE_BUMP),
                Handler(name="attack_observatory", filters=[_target_alive], mutations=[ATTACK]),
                *align_obs,
            ])

        # ---------------------------------------------------------------
        # Datacenter handlers (same as junction: hack + align)
        # ---------------------------------------------------------------
        datacenter_obj = env.game.objects.get("datacenter")
        if datacenter_obj is not None:
            align_dc = [
                Handler(
                    name=f"align_datacenter_{team.name}",
                    filters=[
                        _target_dead,
                        actorHasTag(team.team_tag()),
                        isNear(team.net_tag(), radius=25),
                    ],
                    mutations=[
                        removeTagPrefix("team:", target=EntityTarget.TARGET),
                        addTag(team.team_tag(), target=EntityTarget.TARGET),
                        recomputeMaterializedQuery(team.net_tag()),
                    ],
                )
                for team in all_teams
            ]
            datacenter_obj.on_use_handler = firstMatch([
                Handler(name="vibe_attack_datacenter", filters=[_vibe_attack], mutations=[ATTACK]),
                Handler(name="vibe_patch_datacenter", filters=[_vibe_patch, _has_energy], mutations=HEAL_VIBE_BUMP),
                Handler(name="attack_datacenter", filters=[_target_alive], mutations=[ATTACK]),
                *align_dc,
            ])

        # ---------------------------------------------------------------
        # Agent-vs-agent handlers (PvP / heal / loot)
        # ---------------------------------------------------------------
        for agent in env.game.agents:
            agent_handlers = [
                Handler(name="vibe_attack_cog", filters=[_vibe_attack], mutations=[ATTACK]),
                Handler(name="vibe_patch_cog", filters=[_vibe_patch, _has_energy], mutations=HEAL_VIBE_BUMP),
            ]
            if mission.god_mode:
                agent_handlers.extend([
                    Handler(name="vibe_cred_cog", filters=[_vibe_cred, actorHas({"creds": 10})], mutations=[GIVE_CREDS]),
                    Handler(name="vibe_heart_cog", filters=[_vibe_heart, actorHas({"heart": 1})], mutations=[GIVE_HEART]),
                ])
            agent_handlers.extend([
                Handler(name="vibe_swap_cog", filters=[_vibe_swap, _target_dead], mutations=[SwapMutation()]),
                Handler(name="loot_cog", filters=[_target_dead], mutations=[LOOT_COG]),
            ])
            agent.on_use_handler = firstMatch(agent_handlers)
