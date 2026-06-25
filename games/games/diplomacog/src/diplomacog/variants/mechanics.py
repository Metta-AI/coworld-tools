"""Core mechanic variants for diplomacy."""

from mettagrid.cogame.core import CoGameMissionVariant, Deps
from mettagrid.config.game_value import QueryInventoryValue, stat
from mettagrid.config.handler_config import allOf
from mettagrid.config.mettagrid_config import MettaGridConfig, ResourceLimitsConfig
from mettagrid.config.query import query
from mettagrid.config.render_config import RenderAsset, RenderHudConfig, RenderStatusBarConfig
from mettagrid.config.reward_config import reward

from diplomacog.game import (
    CAMPAIGN_RESOURCES,
    CORE_RESOURCES,
    COUNTRIES,
    COUNTRY_HUBS,
    COUNTRY_PROFILES,
    COUNTRY_STATIONS,
    INCIDENT_RESOURCES,
    QUEUE_RESOURCES,
    build_country_events,
    comms_station_config,
    country_hub_config,
    country_station_config,
    diplomacy_global_obs,
    diplomacy_queue_value,
    diplomacy_station_config,
    diplomacy_stats_handler,
    reactor_station_config,
    sabotage_station_config,
    supply_center_config,
)


def _extend_unique(target: list[str], values: list[str]) -> None:
    for value in values:
        if value not in target:
            target.append(value)


class StationsVariant(CoGameMissionVariant):
    name: str = "stations"
    description: str = "Core station loop: reactor, comms, diplomacy, sabotage, and country assignment stations."

    def modify_env(self, mission, env: MettaGridConfig) -> None:
        _extend_unique(env.game.resource_names, [*CORE_RESOURCES, *COUNTRIES, *QUEUE_RESOURCES, *INCIDENT_RESOURCES])

        map_instance = getattr(env.game.map_builder, "instance", None)
        if map_instance is not None:
            if hasattr(map_instance, "include_core_stations"):
                map_instance.include_core_stations = True
            if hasattr(map_instance, "include_country_stations"):
                map_instance.include_country_stations = True
            if hasattr(map_instance, "include_country_hubs"):
                # Stations-only tasks should not place hubs that are not configured.
                map_instance.include_country_hubs = False
            if hasattr(map_instance, "include_supply_centers"):
                map_instance.include_supply_centers = False
            if hasattr(map_instance, "include_sabotage_station"):
                map_instance.include_sabotage_station = True

        for agent in env.game.agents:
            agent.inventory.limits["cargo"] = ResourceLimitsConfig(base=40, max=40, resources=list(CORE_RESOURCES))
            agent.inventory.limits["country"] = ResourceLimitsConfig(base=1, max=1, resources=list(COUNTRIES))

        env.game.objects["reactor_station"] = reactor_station_config()
        env.game.objects["comms_station"] = comms_station_config()
        env.game.objects["diplomacy_station"] = diplomacy_station_config()
        env.game.objects["sabotage_station"] = sabotage_station_config()
        for station, country in zip(COUNTRY_STATIONS, COUNTRIES, strict=True):
            env.game.objects[station] = country_station_config(country)

        env.game.render.assets.update(
            {
                "reactor_station": [RenderAsset(asset="diplomacy/stamp.reactor")],
                "comms_station": [RenderAsset(asset="diplomacy/stamp.comms")],
                "diplomacy_station": [RenderAsset(asset="diplomacy/stamp.diplomacy")],
                "sabotage_station": [RenderAsset(asset="diplomacy/stamp.sabotage")],
                "country_a_station": [RenderAsset(asset="diplomacy/stamp.country_a")],
                "country_b_station": [RenderAsset(asset="diplomacy/stamp.country_b")],
                "country_c_station": [RenderAsset(asset="diplomacy/stamp.country_c")],
            }
        )
        env.game.render.agent_huds.update(
            {
                "power_cell": RenderHudConfig(resource="power_cell", max=20, rank=0),
                "intel": RenderHudConfig(resource="intel", max=20, rank=1),
                "influence": RenderHudConfig(resource="influence", max=60, rank=2),
                "sabotage_kit": RenderHudConfig(resource="sabotage_kit", max=20, rank=3),
                "country_a": RenderHudConfig(resource="country_a", max=1, rank=4),
                "country_b": RenderHudConfig(resource="country_b", max=1, rank=5),
                "country_c": RenderHudConfig(resource="country_c", max=1, rank=6),
            }
        )
        env.game.render.object_status.setdefault("agent", {})
        env.game.render.object_status["agent"].update(
            {
                "power_cell": RenderStatusBarConfig(resource="power_cell", short_name="P", max=20, rank=0),
                "intel": RenderStatusBarConfig(resource="intel", short_name="I", max=20, rank=1),
                "influence": RenderStatusBarConfig(resource="influence", short_name="INF", max=60, rank=2),
                "sabotage_kit": RenderStatusBarConfig(resource="sabotage_kit", short_name="SK", max=20, rank=3),
            }
        )


class HubsVariant(CoGameMissionVariant):
    name: str = "hubs"
    description: str = "Country hub interactions for queues, incidents, treaties, and sabotage."

    def dependencies(self) -> Deps:
        return Deps(required=[StationsVariant])

    def modify_env(self, mission, env: MettaGridConfig) -> None:
        _extend_unique(env.game.resource_names, ["stability", "crisis", *CAMPAIGN_RESOURCES])

        map_instance = getattr(env.game.map_builder, "instance", None)
        if map_instance is not None:
            if hasattr(map_instance, "include_country_hubs"):
                map_instance.include_country_hubs = True
            if hasattr(map_instance, "include_supply_centers"):
                map_instance.include_supply_centers = True

        for hub, country in zip(COUNTRY_HUBS, COUNTRIES, strict=True):
            env.game.objects[hub] = country_hub_config(
                country,
                COUNTRY_PROFILES[country],
                campaign_anchor=(hub == COUNTRY_HUBS[0]),
            )
        env.game.objects["supply_center"] = supply_center_config()

        env.game.render.assets.update(
            {
                "country_a_hub": [RenderAsset(asset="diplomacy/stamp.country_a_hub")],
                "country_b_hub": [RenderAsset(asset="diplomacy/stamp.country_b_hub")],
                "country_c_hub": [RenderAsset(asset="diplomacy/stamp.country_c_hub")],
                "supply_center": [
                    RenderAsset(asset="diplomacy/stamp.country_a", resources={"country_a": 1}),
                    RenderAsset(asset="diplomacy/stamp.country_b", resources={"country_b": 1}),
                    RenderAsset(asset="diplomacy/stamp.country_c", resources={"country_c": 1}),
                    RenderAsset(asset="diplomacy/stamp.supply_center"),
                ],
            }
        )
        env.game.render.object_status["supply_center"] = {
            "country_a": RenderStatusBarConfig(resource="country_a", short_name="A", bar_type="large", max=1, rank=0),
            "country_b": RenderStatusBarConfig(resource="country_b", short_name="B", bar_type="large", max=1, rank=1),
            "country_c": RenderStatusBarConfig(resource="country_c", short_name="C", bar_type="large", max=1, rank=2),
            "capture_window": RenderStatusBarConfig(
                resource="capture_window",
                short_name="FALL",
                bar_type="medium",
                max=1,
                rank=3,
            ),
        }
        env.game.render.object_status.update(
            {
                hub: {
                    "stability": RenderStatusBarConfig(resource="stability", short_name="S", max=60, rank=0),
                    "crisis": RenderStatusBarConfig(resource="crisis", short_name="C", max=30, rank=1),
                    "queue_diplomacy": RenderStatusBarConfig(
                        resource="queue_diplomacy",
                        short_name="DQ",
                        max=20,
                        rank=2,
                    ),
                    "queue_trade": RenderStatusBarConfig(resource="queue_trade", short_name="TQ", max=20, rank=3),
                    "incident_pending": RenderStatusBarConfig(
                        resource="incident_pending",
                        short_name="IP",
                        max=12,
                        rank=4,
                    ),
                    "incident_window": RenderStatusBarConfig(
                        resource="incident_window",
                        short_name="IW",
                        max=12,
                        rank=5,
                    ),
                }
                for hub in COUNTRY_HUBS
            }
        )


class EventSystemVariant(CoGameMissionVariant):
    name: str = "event_system"
    description: str = "Country crisis waves, queue processors, incidents, and mission outcome checks."

    def dependencies(self) -> Deps:
        return Deps(required=[HubsVariant])

    def modify_env(self, mission, env: MettaGridConfig) -> None:
        env.game.events.update(build_country_events(env.game.max_steps))


class ObservabilityVariant(CoGameMissionVariant):
    name: str = "observability"
    description: str = "Global observations and stat writers for mission auditing and diagnostics."

    def dependencies(self) -> Deps:
        return Deps(required=[HubsVariant])

    def modify_env(self, mission, env: MettaGridConfig) -> None:
        env.game.on_tick = allOf([env.game.on_tick, diplomacy_stats_handler()])
        env.game.obs.global_obs.obs.update(diplomacy_global_obs())


class RewardModelVariant(CoGameMissionVariant):
    name: str = "reward_model"
    description: str = "Shaped reward model for diplomacy loops, incidents, sabotage, and mission outcomes."

    def dependencies(self) -> Deps:
        return Deps(required=[EventSystemVariant])

    def modify_env(self, mission, env: MettaGridConfig) -> None:
        score_weight = 1.5 / env.game.max_steps
        queue_weight = 0.5 / env.game.max_steps
        sabotage_weight = 0.25 / env.game.max_steps
        cross_treaty_weight = 0.35 / env.game.max_steps
        incident_weight = 0.45 / env.game.max_steps
        counter_ops_weight = 0.3 / env.game.max_steps
        center_capture_weight = 0.75 / env.game.max_steps
        outcome_weight = 2.0
        stability_tick_weight = 1.0 / (env.game.max_steps * 100.0)
        crisis_tick_weight = -1.0 / (env.game.max_steps * 60.0)
        queue_tick_weight = -1.0 / (env.game.max_steps * 80.0)

        stability_value = QueryInventoryValue(query=query("country_hub"), item="stability")
        crisis_value = QueryInventoryValue(query=query("country_hub"), item="crisis")
        queue_value = diplomacy_queue_value()

        for agent in env.game.agents:
            agent.rewards.update(
                {
                    "diplomacy": reward(stat("treaties_signed"), weight=score_weight),
                    "queue_work": reward(stat("queue_submitted"), weight=queue_weight),
                    "sabotage": reward(stat("sabotage_executed"), weight=sabotage_weight),
                    "cross_treaties": reward(stat("cross_treaties"), weight=cross_treaty_weight),
                    "incident_response": reward(stat("incidents_resolved"), weight=incident_weight),
                    "counter_ops": reward(stat("counter_ops"), weight=counter_ops_weight),
                    "center_capture": reward(stat("centers_captured"), weight=center_capture_weight),
                    "mission_victory": reward(stat("game.mission_victory"), weight=outcome_weight),
                    "mission_defeat": reward(stat("game.mission_defeat"), weight=-outcome_weight),
                    "global_stability": reward(stability_value, weight=stability_tick_weight, per_tick=True),
                    "global_crisis": reward(crisis_value, weight=crisis_tick_weight, per_tick=True),
                    "global_queue_pressure": reward(queue_value, weight=queue_tick_weight, per_tick=True),
                }
            )


class CoreVariant(CoGameMissionVariant):
    name: str = "core"
    description: str = "Composed full diplomacy baseline from stations, hubs, events, observability, and rewards."

    def dependencies(self) -> Deps:
        return Deps(
            required=[StationsVariant, HubsVariant, EventSystemVariant, ObservabilityVariant, RewardModelVariant]
        )
