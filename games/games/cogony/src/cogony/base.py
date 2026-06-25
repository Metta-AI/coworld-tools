"""base mission definitions.

Composes minimal variant tree for the rules rewrite skeleton.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar, override

from mettagrid.cogame.core import CoGameMissionVariant, Deps
from mettagrid.cogame.variants import ResolvedDeps
from mettagrid.config.filter import actorHas, isNot
from mettagrid.config.handler_config import Handler, allOf
from mettagrid.config.mettagrid_config import MettaGridConfig
from mettagrid.config.mutation import ClearInventoryMutation, EntityTarget
from mettagrid.config.mutation.tag_mutation import removeTagPrefix
from mettagrid.config.render_config import RenderHudConfig, RenderStatusBarConfig
from mettagrid.config.reward_config import inventoryReward
from mettagrid.mapgen.mapgen import MapGen, MapGenConfig
from mettagrid.mapgen.scenes.building_distributions import DistributionConfig, DistributionType

from cogony.game.cargo import CargoLimitVariant
from cogony.game.channels import ChannelsVariant
from cogony.game.coherence import CoherenceVariant
from cogony.game.combat import CombatVariant
from cogony.game.creds import CredsVariant
from cogony.game.elements import ElementsVariant
from cogony.game.extractors import ExtractorsVariant
from cogony.game.heart import HeartVariant
from cogony.game.junction import JunctionVariant
from cogony.game.teams.gear_stations import GEAR_NAMES, TeamGearStationsVariant
from cogony.game.teams.heart_station import TeamHeartStationVariant
from cogony.game.teams.junction import TeamJunctionVariant
from cogony.game.teams.market_stations import TeamMarketStationsVariant
from cogony.game.teams.team import TeamVariant
from cogony.game.territory.heal_team import HealTeamVariant
from cogony.game.territory.territory import TerritoryVariant
from cogony.game.trap import TrapVariant
from cogony.game.vibes import VibesVariant
from cogony.terrain import ArenaConfig, SequentialArena

if TYPE_CHECKING:
    from cogony.mission import CogonyMission

MACHINA_1_MAP_BUILDER = MapGen.Config(
    width=88,
    height=88,
    instance=SequentialArena.Config(
        spawn_count=20,
        map_corner_offset=1,
    ),
)


def _build_base_map_builder(spawn_count: int) -> MapGenConfig:
    map_builder = MACHINA_1_MAP_BUILDER.model_copy(deep=True)
    instance = map_builder.instance
    assert isinstance(instance, ArenaConfig)
    return map_builder.model_copy(
        update={
            "instance": instance.model_copy(
                update={
                    "spawn_count": spawn_count,
                    "building_distributions": {
                        **(instance.building_distributions or {}),
                        "junction": DistributionConfig(type=DistributionType.POISSON),
                    },
                }
            ),
        }
    )


class BaseVariant(CoGameMissionVariant):
    """Minimal base variant: wires heart rewards and a simple death handler."""

    name: str = "base"
    description: str = "Minimal skeleton for rules rewrite."

    @override
    def dependencies(self) -> Deps:
        return Deps(
            required=[
                VibesVariant,
                TeamVariant,
                TerritoryVariant,
                ElementsVariant,
                HeartVariant,
                CargoLimitVariant,
                ChannelsVariant,
                CoherenceVariant,
                CombatVariant,
                CredsVariant,
                ExtractorsVariant,
                JunctionVariant,
                TeamGearStationsVariant,
                TeamHeartStationVariant,
                TeamMarketStationsVariant,
                TeamJunctionVariant,
                HealTeamVariant,
                TrapVariant,
            ]
        )

    @override
    def configure(self, deps: ResolvedDeps) -> None:
        pass

    # Desired display order for inventory resources in mettascope.
    RESOURCE_ORDER: ClassVar[list[str]] = [
        "level",
        "core_a", "core_d",
        "os_a", "os_d",
        "gen_a", "gen_d",
        "storage_a", "storage_d",
        "scrambled", "energy",
        "coherence", "reboot",
        "heart", "creds",
        "carbon", "oxygen", "germanium", "silicon", "cargo",
    ]

    @override
    def modify_env(self, mission: CogonyMission, env: MettaGridConfig) -> None:
        # Sort resource_names so mettascope displays them in the desired order.
        order_map = {name: i for i, name in enumerate(self.RESOURCE_ORDER)}
        env.game.resource_names.sort(
            key=lambda n: order_map.get(n, len(self.RESOURCE_ORDER))
        )

        # Override default hp/energy HUD bars with coherence.
        env.game.render.hud1 = RenderHudConfig(
            resource="coherence", short_name="COH", max=100,
        )
        env.game.render.hud2 = RenderHudConfig(
            resource="energy", short_name="E", max=100,
        )

        # Agent status uses coherence plus the compact subsystem/cargo bars.
        # rank 0: coherence, rank 1: energy, rank 2+: subsystems, then cargo
        rank = 2
        subsystem_bars = {}
        for label, atk, def_ in [("C", "core_a", "core_d"), ("O", "os_a", "os_d"),
                                   ("G", "gen_a", "gen_d"), ("S", "storage_a", "storage_d")]:
            subsystem_bars[atk] = RenderStatusBarConfig(
                resource=atk, short_name=label, max=10,
                bar_type="small", divisions=10, rank=rank, color="red",
            )
            rank += 1
            subsystem_bars[def_] = RenderStatusBarConfig(
                resource=def_, short_name="", max=10,
                bar_type="small", divisions=10, rank=rank, color="blue",
            )
            rank += 1

        stake_rank = rank
        stake_bars = {}
        for color in ["red", "blue", "green", "yellow"]:
            stake_bars[f"{color}_stake"] = RenderStatusBarConfig(
                resource=f"{color}_stake", short_name="", max=10,
                bar_type="stake", rank=stake_rank,
            )
            stake_rank += 1

        cargo_rank = stake_rank
        cargo_bars = {}
        for element in ["carbon", "oxygen", "germanium", "silicon"]:
            cargo_bars[element] = RenderStatusBarConfig(
                resource=element, short_name="", max=100,
                max_resource="max_cargo",
                bar_type="cargo", rank=cargo_rank,
            )
            cargo_rank += 1

        agent_status = {
            "coherence": RenderStatusBarConfig(
                resource="coherence", short_name="", max=100,
                max_resource="max_coherence",
                divisions=20, rank=0, color="green",
                alt_resource="reboot", alt_color="blue",
                icon_label="vibe/green-cpu",
            ),
            "energy": RenderStatusBarConfig(
                resource="energy", short_name="", max=100,
                max_resource="max_energy",
                divisions=20, rank=1, color="blue",
                icon_label="resources/energy",
            ),
            **subsystem_bars,
            **stake_bars,
            **cargo_bars,
        }
        env.game.render.object_status["agent"] = agent_status

        node_status = {
            "coherence": RenderStatusBarConfig(
                resource="coherence", short_name="COH", max=20,
                divisions=10, rank=0, color="green",
                alt_resource="reboot", alt_color="blue",
            ),
        }
        for obj_name in env.game.objects:
            if "extractor" in obj_name or obj_name in (
                "junction", "observatory", "datacenter",
            ):
                env.game.render.object_status[obj_name] = node_status

        for agent in env.game.agents:
            # Reward each agent for each heart they gain over the episode,
            # normalized by episode length.
            agent.rewards["heart"] = inventoryReward(
                "heart",
                weight=1.0 / mission.max_steps,
            )

            # On disabled (coherence < 1): clear cargo (elements) and strip
            # team tag. Do NOT restore coherence — the reboot system in
            # CoherenceVariant handles recovery. Creds, hearts, and gear
            # persist through death (RULES.md sections 3, 6, 7). Gear is
            # lootable by others (§3), but if nobody loots it, it returns
            # with the cog on reboot.
            _death_keep = {
                "heart", "creds", "coherence", "reboot", "scrambled",
                *(g for g in GEAR_NAMES if g != "cargo"),
            }
            limits_to_clear = [
                name
                for name in agent.inventory.limits
                if name not in _death_keep
            ]
            if limits_to_clear:
                death_reset = Handler(
                    name="death_reset",
                    filters=[isNot(actorHas({"coherence": 1}))],
                    mutations=[
                        *[
                            ClearInventoryMutation(target=EntityTarget.ACTOR, limit_name=lim)
                            for lim in limits_to_clear
                        ],
                        removeTagPrefix("team:", target=EntityTarget.ACTOR),
                    ],
                )
                agent.on_tick = allOf([agent.on_tick, death_reset])
