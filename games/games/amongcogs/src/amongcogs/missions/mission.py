"""Among Us mission configuration and base environment wiring."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import cast

from pydantic import Field
from typing_extensions import Self

from cogames.core import CoGameMission, CoGameMissionVariant
from amongcogs.constants import (
    ALIVE_RESOURCE,
    COMMS_ALERT_RESOURCE,
    CORPSE_RESOURCE,
    CRITICAL_STATION_NAMES,
    CRITICAL_TIMER_RESOURCE,
    EJECTED_RESOURCE,
    KILL_COOLDOWN_RESOURCE,
    LIGHTS_ALERT_RESOURCE,
    LIGHTS_CREW_VISION_RADIUS,
    MEETING_ACTIVE_RESOURCE,
    MEETING_BALLOT_RESOURCE,
    MEETING_DISCUSSION_RESOURCE,
    MEETING_DISCUSSION_TIMER_RESOURCE,
    MEETING_DISCUSSION_TURNS,
    MEETING_REPORTED_BODY_RESOURCE,
    MEETING_TIMER_RESOURCE,
    MEETING_TOKEN_COUNT,
    MEETING_TOKEN_RESOURCE,
    OXYGEN_ALERT_RESOURCE,
    REACTOR_ALERT_RESOURCE,
    ROLE_CREW,
    NORMAL_VISION_RADIUS,
    ROLE_IMPOSTOR,
    SABOTAGE_COOLDOWN_RESOURCE,
    STATION_ONLINE_TAG,
    STATION_SABOTAGED_TAG,
    SYSTEM_COMMS_TAG,
    SYSTEM_LIGHTS_TAG,
    SYSTEM_OXYGEN_TAG,
    SYSTEM_REACTOR_TAG,
    TASK_ONLINE_TAG,
    TASK_PROGRESS_STEPS,
    TASK_PROGRESS_RESOURCE,
    TASK_RESOURCE,
    TASK_SABOTAGED_TAG,
    TASK_STATION_NAMES,
    TASK_STATION_TAG,
    VENT_COOLDOWN_RESOURCE,
    VENT_STATION_NAMES,
    VENT_STATION_TAG,
    VIBE_VOTE_AGENT_PREFIX,
    VIBE_CALL_MEETING,
    VIBE_KILL,
    VIBE_REPORT,
    VIBE_SABOTAGE_COMMS,
    VIBE_SABOTAGE_LIGHTS,
    VIBE_SABOTAGE_OXYGEN,
    VIBE_SABOTAGE_REACTOR,
    VIBE_VOTE_IMPOSTOR,
    VIBE_VOTE_SKIP,
    VOTE_IMPOSTOR_RESOURCE,
    VOTE_SKIP_RESOURCE,
    VOTE_TARGET_RESOURCE_PREFIX,
    VOTED_RESOURCE,
    WIN_REWARD_RESOURCE,
    agent_id_resource,
    crew_station_config,
    emergency_button_config,
    impostor_station_config,
    named_vote_target_count,
    security_station_config,
    task_station_config,
    vote_target_resource,
    vote_target_vibe,
)
from amongcogs.defaults import (
    DEFAULT_COMMS_SABOTAGE_TIMER_STEPS,
    DEFAULT_INITIAL_KILL_COOLDOWN_STEPS,
    DEFAULT_INITIAL_SABOTAGE_COOLDOWN_STEPS,
    DEFAULT_KILL_COOLDOWN_STEPS,
    DEFAULT_LIGHTS_SABOTAGE_TIMER_STEPS,
    DEFAULT_MEETING_DURATION_STEPS,
    DEFAULT_OXYGEN_SABOTAGE_TIMER_STEPS,
    DEFAULT_REACTOR_SABOTAGE_TIMER_STEPS,
    DEFAULT_SABOTAGE_COOLDOWN_STEPS,
    DEFAULT_VENT_COOLDOWN_STEPS,
)
from amongcogs.game import build_variant_registry, create_variant, requires_explicit_mechanics_surface
from amongcogs.map_scene import AmongUsShipScene
from mettagrid.config.action_config import ActionsConfig, ChangeVibeActionConfig, MoveActionConfig, NoopActionConfig
from mettagrid.config.game_value import inv, stat, val, weighted_sum
from mettagrid.config.mettagrid_config import (
    AgentConfig,
    GameConfig,
    GridObjectConfig,
    InventoryConfig,
    MettaGridConfig,
    ResourceLimitsConfig,
    TalkConfig,
    WallConfig,
)
from mettagrid.config.obs_config import GlobalObsConfig, ObsConfig
from mettagrid.config.render_config import RenderAsset, RenderConfig, RenderHudConfig, RenderStatusBarConfig
from mettagrid.config.reward_config import inventoryReward, reward
from mettagrid.config.vibes import VIBES, Vibe
from mettagrid.mapgen.mapgen import MapGen

__all__ = [
    "ALIVE_RESOURCE",
    "CORPSE_RESOURCE",
    "EJECTED_RESOURCE",
    "KILL_COOLDOWN_RESOURCE",
    "LIGHTS_ALERT_RESOURCE",
    "MEETING_ACTIVE_RESOURCE",
    "MEETING_BALLOT_RESOURCE",
    "MEETING_DISCUSSION_RESOURCE",
    "MEETING_DISCUSSION_TIMER_RESOURCE",
    "MEETING_REPORTED_BODY_RESOURCE",
    "MEETING_TOKEN_RESOURCE",
    "MEETING_TIMER_RESOURCE",
    "ROLE_CREW",
    "ROLE_IMPOSTOR",
    "STATION_ONLINE_TAG",
    "STATION_SABOTAGED_TAG",
    "TASK_ONLINE_TAG",
    "TASK_PROGRESS_STEPS",
    "TASK_PROGRESS_RESOURCE",
    "TASK_RESOURCE",
    "TASK_SABOTAGED_TAG",
    "TASK_STATION_NAMES",
    "VENT_COOLDOWN_RESOURCE",
    "VENT_STATION_NAMES",
    "VENT_STATION_TAG",
    "VIBE_VOTE_AGENT_PREFIX",
    "VIBE_CALL_MEETING",
    "VIBE_KILL",
    "VIBE_REPORT",
    "VIBE_SABOTAGE_COMMS",
    "VIBE_SABOTAGE_LIGHTS",
    "VIBE_SABOTAGE_OXYGEN",
    "VIBE_SABOTAGE_REACTOR",
    "VIBE_VOTE_IMPOSTOR",
    "VIBE_VOTE_SKIP",
    "VOTE_IMPOSTOR_RESOURCE",
    "VOTE_SKIP_RESOURCE",
    "VOTE_TARGET_RESOURCE_PREFIX",
    "VOTED_RESOURCE",
    "WIN_REWARD_RESOURCE",
    "agent_id_resource",
    "crew_station_config",
    "impostor_station_config",
    "named_vote_target_count",
    "task_station_config",
    "vote_target_resource",
    "vote_target_vibe",
    "AmongUsGame",
]


def _placeholder_station_config(name: str) -> GridObjectConfig:
    """Base object used until a variant enables concrete station mechanics."""
    return GridObjectConfig(name=name)


def _station_placeholders(names: list[str]) -> dict[str, GridObjectConfig]:
    return {name: _placeholder_station_config(name) for name in names}


@dataclass(slots=True)
class AmongUsSettings:
    num_cogs: int
    max_steps: int
    initial_kill_cooldown_steps: int
    kill_cooldown_steps: int
    initial_sabotage_cooldown_steps: int
    sabotage_cooldown_steps: int
    vent_cooldown_steps: int
    meeting_duration_steps: int
    talk_max_length: int
    talk_cooldown_steps: int
    reactor_sabotage_timer_steps: int
    oxygen_sabotage_timer_steps: int
    lights_sabotage_timer_steps: int
    comms_sabotage_timer_steps: int

    @classmethod
    def from_mission(cls, mission: "AmongUsGame") -> "AmongUsSettings":
        return cls(
            num_cogs=cast(int, mission.num_cogs),
            max_steps=mission.max_steps,
            initial_kill_cooldown_steps=mission.initial_kill_cooldown_steps,
            kill_cooldown_steps=mission.kill_cooldown_steps,
            initial_sabotage_cooldown_steps=mission.initial_sabotage_cooldown_steps,
            sabotage_cooldown_steps=mission.sabotage_cooldown_steps,
            vent_cooldown_steps=mission.vent_cooldown_steps,
            meeting_duration_steps=mission.meeting_duration_steps,
            talk_max_length=mission.talk_max_length,
            talk_cooldown_steps=mission.talk_cooldown_steps,
            reactor_sabotage_timer_steps=mission.reactor_sabotage_timer_steps,
            oxygen_sabotage_timer_steps=mission.oxygen_sabotage_timer_steps,
            lights_sabotage_timer_steps=mission.lights_sabotage_timer_steps,
            comms_sabotage_timer_steps=mission.comms_sabotage_timer_steps,
        )


def _agent_config(settings: AmongUsSettings, agent_id: int) -> AgentConfig:
    target_count = named_vote_target_count(settings.num_cogs)
    agent_id_resources = [agent_id_resource(index) for index in range(target_count)]
    vote_target_resources = [vote_target_resource(index) for index in range(target_count)]
    initial = {
        ALIVE_RESOURCE: 1,
        MEETING_TOKEN_RESOURCE: MEETING_TOKEN_COUNT,
        MEETING_TIMER_RESOURCE: settings.meeting_duration_steps,
        KILL_COOLDOWN_RESOURCE: settings.initial_kill_cooldown_steps,
    }
    if agent_id < target_count:
        initial[agent_id_resource(agent_id)] = 1
    return AgentConfig(
        inventory=InventoryConfig(
            initial=initial,
            limits={
                "role": ResourceLimitsConfig(
                    base=1,
                    max=1,
                    resources=[ROLE_CREW, ROLE_IMPOSTOR],
                ),
                "task": ResourceLimitsConfig(base=100, resources=[TASK_RESOURCE]),
                "task_progress": ResourceLimitsConfig(
                    base=TASK_PROGRESS_STEPS,
                    max=TASK_PROGRESS_STEPS,
                    resources=[TASK_PROGRESS_RESOURCE],
                ),
                "alive_status": ResourceLimitsConfig(
                    base=1,
                    max=1,
                    resources=[ALIVE_RESOURCE],
                ),
                "agent_identity": ResourceLimitsConfig(
                    base=1,
                    max=1,
                    resources=agent_id_resources,
                ),
                "corpse_status": ResourceLimitsConfig(
                    base=1,
                    max=1,
                    resources=[CORPSE_RESOURCE],
                ),
                "meeting_status": ResourceLimitsConfig(
                    base=1,
                    max=1,
                    resources=[MEETING_ACTIVE_RESOURCE],
                ),
                "meeting_phase_status": ResourceLimitsConfig(
                    base=1,
                    max=1,
                    resources=[MEETING_DISCUSSION_RESOURCE, MEETING_BALLOT_RESOURCE],
                ),
                "meeting_report_context": ResourceLimitsConfig(
                    base=1,
                    max=1,
                    resources=[MEETING_REPORTED_BODY_RESOURCE],
                ),
                "meeting_discussion_timer": ResourceLimitsConfig(
                    base=MEETING_DISCUSSION_TURNS,
                    max=MEETING_DISCUSSION_TURNS,
                    resources=[MEETING_DISCUSSION_TIMER_RESOURCE],
                ),
                "meeting_token": ResourceLimitsConfig(
                    base=MEETING_TOKEN_COUNT,
                    max=MEETING_TOKEN_COUNT,
                    resources=[MEETING_TOKEN_RESOURCE],
                ),
                "meeting_timer": ResourceLimitsConfig(
                    base=settings.meeting_duration_steps,
                    max=settings.meeting_duration_steps,
                    resources=[MEETING_TIMER_RESOURCE],
                ),
                "voted_status": ResourceLimitsConfig(
                    base=1,
                    max=1,
                    resources=[VOTED_RESOURCE],
                ),
                "vote_choice_status": ResourceLimitsConfig(
                    base=1,
                    max=1,
                    resources=[VOTE_IMPOSTOR_RESOURCE, VOTE_SKIP_RESOURCE],
                ),
                "vote_target_status": ResourceLimitsConfig(
                    base=1,
                    max=1,
                    resources=vote_target_resources,
                ),
                "ejected_status": ResourceLimitsConfig(
                    base=1,
                    max=1,
                    resources=[EJECTED_RESOURCE],
                ),
                "win_reward_status": ResourceLimitsConfig(
                    base=1,
                    max=1,
                    resources=[WIN_REWARD_RESOURCE],
                ),
                "kill_cooldown": ResourceLimitsConfig(
                    base=settings.initial_kill_cooldown_steps,
                    max=max(settings.initial_kill_cooldown_steps, settings.kill_cooldown_steps),
                    resources=[KILL_COOLDOWN_RESOURCE],
                ),
                "sabotage_cooldown": ResourceLimitsConfig(
                    base=settings.initial_sabotage_cooldown_steps,
                    max=max(settings.initial_sabotage_cooldown_steps, settings.sabotage_cooldown_steps),
                    resources=[SABOTAGE_COOLDOWN_RESOURCE],
                ),
                "vent_cooldown": ResourceLimitsConfig(
                    base=settings.vent_cooldown_steps,
                    max=settings.vent_cooldown_steps,
                    resources=[VENT_COOLDOWN_RESOURCE],
                ),
                "critical_alerts": ResourceLimitsConfig(
                    base=1,
                    max=1,
                    resources=[
                        LIGHTS_ALERT_RESOURCE,
                        OXYGEN_ALERT_RESOURCE,
                        REACTOR_ALERT_RESOURCE,
                        COMMS_ALERT_RESOURCE,
                    ],
                ),
            },
        ),
        rewards={
            "tasks": reward(stat("tasks_completed"), weight=1.0),
            "sabotage": reward(stat("sabotages"), weight=1.0),
            "repairs": reward(stat("repairs"), weight=1.0),
            "kills": reward(stat("kills"), weight=10.0),
            "reports": reward(stat("reports"), weight=0.5),
            "wins": inventoryReward(WIN_REWARD_RESOURCE, weight=100.0),
        },
    )


def _render_status(resource_name: str, short_name: str, max_value: int, *, rank: int = 0) -> RenderStatusBarConfig:
    return RenderStatusBarConfig(resource=resource_name, short_name=short_name, max=max_value, rank=rank)


def _render_hud(resource_name: str, short_name: str, max_value: int, rank: int) -> RenderHudConfig:
    return RenderHudConfig(resource=resource_name, short_name=short_name, max=max_value, rank=rank)


def _vote_target_vibes(settings: AmongUsSettings) -> list[Vibe]:
    return [
        Vibe(str(agent_id), vote_target_vibe(agent_id), category="amongcogs_vote")
        for agent_id in range(named_vote_target_count(settings.num_cogs))
    ]


def _render_assets() -> dict[str, list[RenderAsset]]:
    assets = {
        "crew_station": "crew_station",
        "impostor_station": "impostor_station",
        "wiring_station": "wiring_station",
        "reactor_station": "reactor_station",
        "navigation_station": "navigation_station",
        "oxygen_station": "oxygen_station",
        "admin_station": "admin_station",
        "medbay_station": "medbay_station",
        "weapons_station": "weapons_station",
        "shields_station": "shields_station",
        "comms_station": "comms_station",
        "lights_station": "lights_station",
        "security_station": "security_station",
        "emergency_button": "emergency_button",
    }
    role_state_assets = [
        ("ejected", EJECTED_RESOURCE),
        ("body", CORPSE_RESOURCE),
        ("vote_impostor", VOTE_IMPOSTOR_RESOURCE),
        ("vote_skip", VOTE_SKIP_RESOURCE),
        ("ballot", MEETING_BALLOT_RESOURCE),
        ("discussion", MEETING_DISCUSSION_RESOURCE),
    ]
    agent_assets = [
        RenderAsset(
            asset=f"{asset_name}_{role_asset}",
            resources={resource_name: 1, role_resource: 1},
        )
        for role_asset, role_resource in (("impostor", ROLE_IMPOSTOR), ("crewmate", ROLE_CREW))
        for asset_name, resource_name in role_state_assets
    ]
    agent_assets.extend(
        [
            RenderAsset(asset="impostor", resources={ROLE_IMPOSTOR: 1}),
            RenderAsset(asset="crewmate", resources={ROLE_CREW: 1}),
            RenderAsset(asset="agent"),
        ]
    )
    return {
        "agent": agent_assets,
        **{name: [RenderAsset(asset=asset_name)] for name, asset_name in assets.items()},
        **{name: [RenderAsset(asset="vent")] for name in VENT_STATION_NAMES},
    }


def _object_status(settings: AmongUsSettings) -> dict[str, dict[str, RenderStatusBarConfig]]:
    task_status = {TASK_RESOURCE: _render_status(TASK_RESOURCE, "TSK", 3)}
    return {
        "agent": {
            TASK_RESOURCE: _render_status(TASK_RESOURCE, "TSK", 10, rank=0),
            TASK_PROGRESS_RESOURCE: _render_status(TASK_PROGRESS_RESOURCE, "PROG", TASK_PROGRESS_STEPS, rank=1),
            MEETING_ACTIVE_RESOURCE: _render_status(MEETING_ACTIVE_RESOURCE, "MTG", 1, rank=2),
            MEETING_DISCUSSION_RESOURCE: _render_status(MEETING_DISCUSSION_RESOURCE, "TALK", 1, rank=3),
            MEETING_BALLOT_RESOURCE: _render_status(MEETING_BALLOT_RESOURCE, "BAL", 1, rank=4),
            MEETING_REPORTED_BODY_RESOURCE: _render_status(MEETING_REPORTED_BODY_RESOURCE, "BODY", 1, rank=5),
            MEETING_TIMER_RESOURCE: _render_status(
                MEETING_TIMER_RESOURCE,
                "TIME",
                settings.meeting_duration_steps,
                rank=6,
            ),
            VOTED_RESOURCE: _render_status(VOTED_RESOURCE, "VTD", 1, rank=7),
            VOTE_IMPOSTOR_RESOURCE: _render_status(VOTE_IMPOSTOR_RESOURCE, "ACC", 1, rank=8),
            VOTE_SKIP_RESOURCE: _render_status(VOTE_SKIP_RESOURCE, "SKIP", 1, rank=9),
            EJECTED_RESOURCE: _render_status(EJECTED_RESOURCE, "OUT", 1, rank=10),
            WIN_REWARD_RESOURCE: _render_status(WIN_REWARD_RESOURCE, "WIN", 1, rank=11),
            MEETING_TOKEN_RESOURCE: _render_status(
                MEETING_TOKEN_RESOURCE,
                "BTN",
                MEETING_TOKEN_COUNT,
                rank=12,
            ),
            KILL_COOLDOWN_RESOURCE: _render_status(
                KILL_COOLDOWN_RESOURCE,
                "KILL",
                settings.initial_kill_cooldown_steps,
                rank=13,
            ),
            SABOTAGE_COOLDOWN_RESOURCE: _render_status(
                SABOTAGE_COOLDOWN_RESOURCE,
                "SAB",
                settings.initial_sabotage_cooldown_steps,
                rank=14,
            ),
            VENT_COOLDOWN_RESOURCE: _render_status(
                VENT_COOLDOWN_RESOURCE,
                "VENT",
                settings.vent_cooldown_steps,
                rank=15,
            ),
            REACTOR_ALERT_RESOURCE: _render_status(REACTOR_ALERT_RESOURCE, "REA", 1, rank=16),
            OXYGEN_ALERT_RESOURCE: _render_status(OXYGEN_ALERT_RESOURCE, "O2", 1, rank=17),
            LIGHTS_ALERT_RESOURCE: _render_status(LIGHTS_ALERT_RESOURCE, "LGT", 1, rank=18),
            COMMS_ALERT_RESOURCE: _render_status(COMMS_ALERT_RESOURCE, "COM", 1, rank=19),
        },
        "wiring_station": dict(task_status),
        "navigation_station": dict(task_status),
        "admin_station": dict(task_status),
        "medbay_station": dict(task_status),
        "weapons_station": dict(task_status),
        "shields_station": dict(task_status),
        "comms_station": {
            **task_status,
            CRITICAL_TIMER_RESOURCE: _render_status(
                CRITICAL_TIMER_RESOURCE,
                "COM",
                settings.comms_sabotage_timer_steps,
            ),
        },
        "reactor_station": {
            CRITICAL_TIMER_RESOURCE: _render_status(
                CRITICAL_TIMER_RESOURCE,
                "CRT",
                settings.reactor_sabotage_timer_steps,
            ),
        },
        "oxygen_station": {
            CRITICAL_TIMER_RESOURCE: _render_status(
                CRITICAL_TIMER_RESOURCE,
                "O2",
                settings.oxygen_sabotage_timer_steps,
            ),
        },
        "lights_station": {
            CRITICAL_TIMER_RESOURCE: _render_status(
                CRITICAL_TIMER_RESOURCE,
                "LGT",
                settings.lights_sabotage_timer_steps,
            ),
        },
    }


def _agent_huds(settings: AmongUsSettings) -> dict[str, RenderHudConfig]:
    return {
        MEETING_TIMER_RESOURCE: _render_hud(MEETING_TIMER_RESOURCE, "MTG", settings.meeting_duration_steps, rank=0),
        KILL_COOLDOWN_RESOURCE: _render_hud(
            KILL_COOLDOWN_RESOURCE,
            "KILL",
            settings.initial_kill_cooldown_steps,
            rank=1,
        ),
        SABOTAGE_COOLDOWN_RESOURCE: _render_hud(
            SABOTAGE_COOLDOWN_RESOURCE,
            "SAB",
            settings.initial_sabotage_cooldown_steps,
            rank=2,
        ),
        VENT_COOLDOWN_RESOURCE: _render_hud(VENT_COOLDOWN_RESOURCE, "VENT", settings.vent_cooldown_steps, rank=3),
        REACTOR_ALERT_RESOURCE: _render_hud(REACTOR_ALERT_RESOURCE, "REA", 1, rank=4),
        OXYGEN_ALERT_RESOURCE: _render_hud(OXYGEN_ALERT_RESOURCE, "O2", 1, rank=5),
        LIGHTS_ALERT_RESOURCE: _render_hud(LIGHTS_ALERT_RESOURCE, "LGT", 1, rank=6),
        COMMS_ALERT_RESOURCE: _render_hud(COMMS_ALERT_RESOURCE, "COM", 1, rank=7),
    }


def _stamp_assets() -> dict[str, str]:
    assets = {
        "crew_station": "amongus/terrain/stamp.among_us_crew",
        "impostor_station": "amongus/terrain/stamp.among_us_impostor",
        "wiring_station": "amongus/terrain/stamp.among_us_wiring",
        "reactor_station": "amongus/terrain/stamp.among_us_reactor",
        "navigation_station": "amongus/terrain/stamp.among_us_navigation",
        "oxygen_station": "amongus/terrain/stamp.among_us_oxygen",
        "admin_station": "amongus/terrain/stamp.among_us_admin",
        "medbay_station": "amongus/terrain/stamp.among_us_medbay",
        "weapons_station": "amongus/terrain/stamp.among_us_weapons",
        "shields_station": "amongus/terrain/stamp.among_us_shields",
        "comms_station": "amongus/terrain/stamp.among_us_comms",
        "lights_station": "amongus/terrain/stamp.among_us_lights",
        "security_station": "amongus/terrain/stamp.among_us_security",
        "emergency_button": "amongus/terrain/stamp.among_us_emergency",
    }
    return {
        **assets,
        **{name: "amongus/terrain/stamp.among_us_vent" for name in VENT_STATION_NAMES},
    }


class AmongUsGame(CoGameMission):
    map_builder: MapGen.Config
    default_variant: str | None = "full"
    min_cogs: int = Field(default=1, ge=1)
    max_cogs: int = Field(default=1000, ge=1)
    max_steps: int = Field(default=400)
    initial_kill_cooldown_steps: int = Field(default=DEFAULT_INITIAL_KILL_COOLDOWN_STEPS, ge=0)
    kill_cooldown_steps: int = Field(default=DEFAULT_KILL_COOLDOWN_STEPS, ge=1)
    meeting_duration_steps: int = Field(default=DEFAULT_MEETING_DURATION_STEPS, ge=1)
    initial_sabotage_cooldown_steps: int = Field(default=DEFAULT_INITIAL_SABOTAGE_COOLDOWN_STEPS, ge=0)
    sabotage_cooldown_steps: int = Field(default=DEFAULT_SABOTAGE_COOLDOWN_STEPS, ge=1)
    vent_cooldown_steps: int = Field(default=DEFAULT_VENT_COOLDOWN_STEPS, ge=1)
    talk_max_length: int = Field(default=64, ge=1)
    talk_cooldown_steps: int = Field(default=1, ge=0)
    reactor_sabotage_timer_steps: int = Field(default=DEFAULT_REACTOR_SABOTAGE_TIMER_STEPS, ge=1)
    oxygen_sabotage_timer_steps: int = Field(default=DEFAULT_OXYGEN_SABOTAGE_TIMER_STEPS, ge=1)
    lights_sabotage_timer_steps: int = Field(default=DEFAULT_LIGHTS_SABOTAGE_TIMER_STEPS, ge=1)
    comms_sabotage_timer_steps: int = Field(default=DEFAULT_COMMS_SABOTAGE_TIMER_STEPS, ge=1)

    @classmethod
    def create(cls, num_agents: int, max_steps: int) -> "AmongUsGame":
        return cls(
            name="basic",
            description="Among Us style station-task map with crew and impostor roles.",
            map_builder=cls._map_builder(num_agents),
            num_cogs=num_agents,
            min_cogs=1,
            max_cogs=num_agents,
            max_steps=max_steps,
        )

    def with_variants(self, variants: Sequence[str | CoGameMissionVariant]) -> Self:
        copy = self.model_copy(deep=True)
        requested_names: list[str] = []
        seen: set[str] = set()
        for value in variants:
            if isinstance(value, CoGameMissionVariant):
                copy._base_variants[value.name] = value
                name = value.name
            else:
                name = str(value).strip()
                copy._base_variants[name] = create_variant(name)
            if name and name not in seen:
                seen.add(name)
                requested_names.append(name)
        if requires_explicit_mechanics_surface(requested_names):
            copy.default_variant = None
        return copy

    def _active_variant_names(self) -> list[str]:
        names: list[str] = []
        if self.default_variant:
            names.append(self.default_variant)
        names.extend(self._base_variants)
        return list(dict.fromkeys(name for name in names if name))

    def _configure_variant_registry(self) -> None:
        self._variant_registry = build_variant_registry(self._active_variant_names())

    def _resolved_settings(self) -> AmongUsSettings:
        self._configure_variant_registry()
        settings = AmongUsSettings.from_mission(self)
        for variant in self._variant_registry.configured():
            if hasattr(variant, "modify_mission"):
                variant.modify_mission(settings)
        return settings

    def _build_base_env(self, settings: AmongUsSettings) -> MettaGridConfig:
        map_builder = self.map_builder.model_copy(deep=True)
        map_instance = getattr(map_builder, "instance", None)
        if map_instance is not None and hasattr(map_instance, "spawn_count"):
            map_instance.spawn_count = settings.num_cogs
        target_count = named_vote_target_count(settings.num_cogs)

        game = GameConfig(
            map_builder=map_builder,
            max_steps=settings.max_steps,
            num_agents=settings.num_cogs,
            resource_names=[
                ROLE_CREW,
                ROLE_IMPOSTOR,
                *[agent_id_resource(agent_id) for agent_id in range(target_count)],
                TASK_RESOURCE,
                TASK_PROGRESS_RESOURCE,
                ALIVE_RESOURCE,
                CORPSE_RESOURCE,
                MEETING_ACTIVE_RESOURCE,
                MEETING_DISCUSSION_RESOURCE,
                MEETING_BALLOT_RESOURCE,
                MEETING_REPORTED_BODY_RESOURCE,
                MEETING_DISCUSSION_TIMER_RESOURCE,
                MEETING_TOKEN_RESOURCE,
                MEETING_TIMER_RESOURCE,
                VOTED_RESOURCE,
                VOTE_IMPOSTOR_RESOURCE,
                VOTE_SKIP_RESOURCE,
                *[vote_target_resource(agent_id) for agent_id in range(target_count)],
                KILL_COOLDOWN_RESOURCE,
                SABOTAGE_COOLDOWN_RESOURCE,
                VENT_COOLDOWN_RESOURCE,
                EJECTED_RESOURCE,
                CRITICAL_TIMER_RESOURCE,
                LIGHTS_ALERT_RESOURCE,
                OXYGEN_ALERT_RESOURCE,
                REACTOR_ALERT_RESOURCE,
                COMMS_ALERT_RESOURCE,
                WIN_REWARD_RESOURCE,
            ],
            obs=ObsConfig(
                global_obs=GlobalObsConfig(
                    local_position=True,
                    last_action_move=True,
                ),
                observation_radius_value=weighted_sum(
                    [
                        (1.0, val(NORMAL_VISION_RADIUS)),
                        (LIGHTS_CREW_VISION_RADIUS - NORMAL_VISION_RADIUS, inv(LIGHTS_ALERT_RESOURCE)),
                    ],
                    min=LIGHTS_CREW_VISION_RADIUS,
                    max=NORMAL_VISION_RADIUS,
                ),
            ),
            talk=TalkConfig(
                enabled=True,
                max_length=settings.talk_max_length,
                cooldown_steps=settings.talk_cooldown_steps,
                broadcast_resource=MEETING_ACTIVE_RESOURCE,
            ),
            protocol_details_obs=False,
            actions=ActionsConfig(
                move=MoveActionConfig(),
                noop=NoopActionConfig(),
                change_vibe=ChangeVibeActionConfig(vibes=[*VIBES, *_vote_target_vibes(settings)]),
            ),
            agents=[_agent_config(settings, agent_id) for agent_id in range(settings.num_cogs)],
            objects={
                "wall": WallConfig(name="wall"),
                "crew_station": _placeholder_station_config("crew_station"),
                "impostor_station": _placeholder_station_config("impostor_station"),
                **_station_placeholders(TASK_STATION_NAMES),
                **_station_placeholders(CRITICAL_STATION_NAMES),
                **_station_placeholders(VENT_STATION_NAMES),
                "security_station": security_station_config(),
                "emergency_button": emergency_button_config(),
            },
            events={},
            end_episode_on_game_stats={},
            render=RenderConfig(
                assets=_render_assets(),
                agent_huds=_agent_huds(settings),
                object_status=_object_status(settings),
                terrain_tile="amongus/terrain/repeating.among_us.png",
                stamp_assets=_stamp_assets(),
            ),
            tags=[
                TASK_STATION_TAG,
                STATION_ONLINE_TAG,
                STATION_SABOTAGED_TAG,
                "station:critical",
                "station:info",
                "station:meeting",
                VENT_STATION_TAG,
                SYSTEM_REACTOR_TAG,
                SYSTEM_OXYGEN_TAG,
                SYSTEM_LIGHTS_TAG,
                SYSTEM_COMMS_TAG,
            ],
        )
        return MettaGridConfig(game=game)

    def make_base_env(self) -> MettaGridConfig:
        return self._build_base_env(AmongUsSettings.from_mission(self))

    def make_env(self) -> MettaGridConfig:
        settings = self._resolved_settings()
        env = self._build_base_env(settings)
        self._variant_registry.apply_to_env(settings, env)
        env.label = self.full_name()
        return env

    def full_name(self) -> str:
        return f"amongcogs_ship.{self.name}"

    @staticmethod
    def _map_builder(num_agents: int) -> MapGen.Config:
        return MapGen.Config(
            width=48,
            height=32,
            border_width=3,
            instance=AmongUsShipScene.Config(
                spawn_count=num_agents,
            ),
        )
