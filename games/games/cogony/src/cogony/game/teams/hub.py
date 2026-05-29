"""Team hub variant: stake-based team economics.

Hub bump behavior:
    Default vibe: CLAIM (settle dividends, reset basis)
    Buy (+) vibe: MINT (settle + buy one stake)
    Sell (-) vibe: BURN (settle + sell one stake)

Territory income flows into hub DPS; stake-holders extract via dividends.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, override

from mettagrid.cogame.core import CoGameMissionVariant, Deps
from mettagrid.config.event_config import EventConfig, periodic
from mettagrid.config.filter import hasTag
from mettagrid.config.handler_config import Handler
from mettagrid.config.mettagrid_config import (
    GridObjectConfig,
    InventoryConfig,
    MettaGridConfig,
    ResourceLimitsConfig,
)
from mettagrid.config.mutation import CogonyHubIncomeMutation, CogonyStakeMutation, updateActor
from mettagrid.config.mutation.mutation import EntityTarget
from mettagrid.config.mutation.tag_mutation import addTag, removeTagPrefix
from mettagrid.config.query import query
from mettagrid.config.render_config import RenderAsset
from mettagrid.config.tag import typeTag

from cogony.game.creds import UNLIMITED
from cogony.game.teams.team import TeamConfig, TeamVariant
from cogony.terrain import find_arena

if TYPE_CHECKING:
    from cogony.mission import CogonyMission

HUB_PAYOUT_PERIOD = 100
CREDS_PER_JUNCTION = 10
CREDS_PER_OBSERVATORY = 50
CREDS_PER_DATACENTER = 100
STAKE_K = 10
CHAMPION_PCT = 30

TEAM_COLORS = ["red", "blue", "green", "yellow"]


def _stake_display_resources(color: str) -> list[str]:
    return [
        f"{color}_stake_buy_price",
        f"{color}_stake_sell_price",
        f"{color}_total_stakes",
    ]


def _stake_mutation(team: TeamConfig, mode: str, hub_tag: str = "") -> CogonyStakeMutation:
    color = team.name.replace("cogs_", "")
    return CogonyStakeMutation(
        stake=f"{color}_stake",
        invested=f"{color}_invested",
        dividends=f"{color}_dividends",
        creds="creds",
        total_stake=f"{color}_total_stakes",
        stake_buy_price=f"{color}_stake_buy_price",
        stake_sell_price=f"{color}_stake_sell_price",
        hub_tag=hub_tag,
        k=STAKE_K,
        mode=mode,
    )


def _display_limits(*resources: str) -> dict[str, ResourceLimitsConfig]:
    return {
        resource: ResourceLimitsConfig(base=UNLIMITED, max=UNLIMITED, resources=[resource])
        for resource in resources
    }


def _hub_bump_handler(team: TeamConfig) -> Handler:
    """Hub bump: claim dividends, join team, restore health."""
    color = team.name.replace("cogs_", "")
    return Handler(
        name=f"claim_{color}",
        mutations=[
            _stake_mutation(team, "claim", hub_tag=team.team_tag()),
            removeTagPrefix("team:", target=EntityTarget.ACTOR),
            addTag(team.team_tag(), target=EntityTarget.ACTOR),
            updateActor({"coherence": 65535, "energy": 65535}),
        ],
    )


def _stake_buy_station(team: TeamConfig) -> GridObjectConfig:
    """Station that mints one stake. Finds hub by tag."""
    color = team.name.replace("cogs_", "")
    key = f"{team.short_name}:stake_buy_st"
    return GridObjectConfig(
        name="stake_buy_station",
        map_name=key,
        tags=[team.team_tag()],
        inventory=InventoryConfig(
            limits=_display_limits(f"{color}_stake_buy_price"),
            initial={
                f"{color}_stake_buy_price": STAKE_K,
            },
        ),
        on_use_handler=Handler(
            name=f"mint_{color}",
            mutations=[_stake_mutation(team, "mint", hub_tag=team.team_tag())],
        ),
    )


def _stake_sell_station(team: TeamConfig) -> GridObjectConfig:
    """Station that burns one stake. Finds hub by tag."""
    color = team.name.replace("cogs_", "")
    key = f"{team.short_name}:stake_sell_st"
    return GridObjectConfig(
        name="stake_sell_station",
        map_name=key,
        tags=[team.team_tag()],
        inventory=InventoryConfig(
            limits=_display_limits(f"{color}_stake_sell_price"),
            initial={
                f"{color}_stake_sell_price": 0,
            },
        ),
        on_use_handler=Handler(
            name=f"burn_{color}",
            mutations=[_stake_mutation(team, "burn", hub_tag=team.team_tag())],
        ),
    )


def _hub_income_event(team: TeamConfig) -> EventConfig:
    """Periodic: compute junction income, pay champion 30%, distribute rest to stakers."""
    color = team.name.replace("cogs_", "")
    return EventConfig(
        name=f"hub_income_{team.name}",
        target_query=query(typeTag("hub"), hasTag(team.team_tag())),
        timesteps=periodic(start=HUB_PAYOUT_PERIOD, period=HUB_PAYOUT_PERIOD),
        mutations=[
            CogonyHubIncomeMutation(
                total_stake=f"{color}_total_stakes",
                stake=f"{color}_stake",
                dividends=f"{color}_dividends",
                stake_buy_price=f"{color}_stake_buy_price",
                stake_sell_price=f"{color}_stake_sell_price",
                team_tag=team.team_tag(),
                k=STAKE_K,
                creds_per_junction=CREDS_PER_JUNCTION,
                creds_per_observatory=CREDS_PER_OBSERVATORY,
                creds_per_datacenter=CREDS_PER_DATACENTER,
                champion_pct=CHAMPION_PCT,
            ),
        ],
    )


class TeamHubVariant(CoGameMissionVariant):
    """Stake-based hub for each team. Bumping = claim/mint/burn."""

    name: str = "team_hub"
    description: str = "Stake-based team hubs with bonding curve economics."

    @override
    def dependencies(self) -> Deps:
        return Deps(required=[TeamVariant])

    @override
    def modify_env(self, mission: CogonyMission, env: MettaGridConfig) -> None:
        team_v = mission.required_variant(TeamVariant)

        for color in TEAM_COLORS:
            env.game.add_resource(f"{color}_stake")
            env.game.add_resource(f"{color}_invested")
            env.game.add_resource(f"{color}_dividends")
            for resource in _stake_display_resources(color):
                env.game.add_resource(resource)

        for agent in env.game.agents:
            for color in TEAM_COLORS:
                stake_res = f"{color}_stake"
                agent.inventory.limits.setdefault(
                    stake_res,
                    ResourceLimitsConfig(base=65535, max=65535, resources=[stake_res]),
                )
                agent.inventory.initial.setdefault(stake_res, 0)
                for suffix in ["invested", "dividends"]:
                    res = f"{color}_{suffix}"
                    agent.inventory.limits.setdefault(
                        res,
                        ResourceLimitsConfig(base=UNLIMITED, max=UNLIMITED, resources=[res]),
                    )
                    agent.inventory.initial.setdefault(res, 0)

        arena = find_arena(env.game.map_builder)
        if arena is not None:
            first_team = next(iter(team_v.teams.values()))
            arena.hub = arena.hub.model_copy(update={"hub_object": f"{first_team.short_name}:hub"})

        station_keys: list[str] = []
        for team in team_v.teams.values():
            color = team.name.replace("cogs_", "")
            map_name = f"{team.short_name}:hub"
            display_resources = _stake_display_resources(color)
            cfg = GridObjectConfig(
                name="hub",
                map_name=map_name,
                tags=[team.team_tag()],
                inventory=InventoryConfig(
                    limits={
                        **_display_limits(*display_resources),
                    },
                    initial={
                        f"{color}_stake_buy_price": STAKE_K,
                        f"{color}_stake_sell_price": 0,
                        f"{color}_total_stakes": 0,
                    },
                ),
                on_use_handler=_hub_bump_handler(team),
            )
            env.game.objects.setdefault(map_name, cfg)

            buy_cfg = _stake_buy_station(team)
            env.game.objects.setdefault(buy_cfg.map_name, buy_cfg)
            env.game.render.symbols[buy_cfg.map_name] = "➕"
            env.game.render.assets[buy_cfg.map_name] = [RenderAsset(asset="stake_buy_station")]
            station_keys.append(buy_cfg.map_name)
            sell_cfg = _stake_sell_station(team)
            env.game.objects.setdefault(sell_cfg.map_name, sell_cfg)
            env.game.render.symbols[sell_cfg.map_name] = "➖"
            env.game.render.assets[sell_cfg.map_name] = [RenderAsset(asset="stake_sell_station")]
            station_keys.append(sell_cfg.map_name)

            env.game.events.setdefault(
                f"hub_income_{team.name}", _hub_income_event(team))

        if arena is not None:
            existing = set(arena.hub.stations)
            arena.hub.stations.extend(k for k in station_keys if k not in existing)
