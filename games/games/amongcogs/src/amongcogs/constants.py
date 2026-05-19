"""Shared Among Us gameplay constants and station object configs."""

from __future__ import annotations

from mettagrid.config.filter import actorHasAnyOf, hasTag, isNot, maxDistance
from mettagrid.config.handler_config import (
    Handler,
    actorHas,
    addTag,
    firstMatch,
    removeTag,
    targetHas,
    updateActor,
    updateTarget,
    withdraw,
)
from mettagrid.config.mettagrid_config import GridObjectConfig, InventoryConfig
from mettagrid.config.mutation import queryPlaceAdjacent
from mettagrid.config.mutation.stats_mutation import logActorAgentStat, logStatToGame
from mettagrid.config.query import query

ROLE_CREW = "crew"
ROLE_IMPOSTOR = "impostor"
TASK_RESOURCE = "task"
TASK_PROGRESS_RESOURCE = "task_progress"
ALIVE_RESOURCE = "alive"
CORPSE_RESOURCE = "corpse"
MEETING_ACTIVE_RESOURCE = "meeting_active"
MEETING_DISCUSSION_RESOURCE = "meeting_discussion"
MEETING_BALLOT_RESOURCE = "meeting_ballot"
MEETING_REPORTED_BODY_RESOURCE = "meeting_reported_body"
MEETING_DISCUSSION_TIMER_RESOURCE = "meeting_discussion_timer"
MEETING_TOKEN_RESOURCE = "meeting_token"
MEETING_TIMER_RESOURCE = "meeting_timer"
VOTED_RESOURCE = "voted"
VOTE_IMPOSTOR_RESOURCE = "vote_impostor"
VOTE_SKIP_RESOURCE = "vote_skip"
AGENT_ID_RESOURCE_PREFIX = "agent_id_"
VOTE_TARGET_RESOURCE_PREFIX = "vote_target_"
KILL_COOLDOWN_RESOURCE = "kill_cooldown"
SABOTAGE_COOLDOWN_RESOURCE = "sabotage_cooldown"
VENT_COOLDOWN_RESOURCE = "vent_cooldown"
EJECTED_RESOURCE = "ejected"
WIN_REWARD_RESOURCE = "win_reward"
CRITICAL_TIMER_RESOURCE = "critical_timer"
LIGHTS_ALERT_RESOURCE = "lights_alert"
OXYGEN_ALERT_RESOURCE = "oxygen_alert"
REACTOR_ALERT_RESOURCE = "reactor_alert"
COMMS_ALERT_RESOURCE = "comms_alert"
TASK_STATION_TAG = "station:task"
CRITICAL_STATION_TAG = "station:critical"
INFO_STATION_TAG = "station:info"
MEETING_STATION_TAG = "station:meeting"
VENT_STATION_TAG = "station:vent"
STATION_ONLINE_TAG = "station:online"
STATION_SABOTAGED_TAG = "station:sabotaged"
TASK_ONLINE_TAG = STATION_ONLINE_TAG
TASK_SABOTAGED_TAG = STATION_SABOTAGED_TAG
SYSTEM_REACTOR_TAG = "system:reactor"
SYSTEM_OXYGEN_TAG = "system:oxygen"
SYSTEM_LIGHTS_TAG = "system:lights"
SYSTEM_COMMS_TAG = "system:comms"
TASK_REFILL_PERIOD = 28
REACTOR_SABOTAGE_TIMER_STEPS = 12
OXYGEN_SABOTAGE_TIMER_STEPS = 12
LIGHTS_SABOTAGE_TIMER_STEPS = 20
COMMS_SABOTAGE_TIMER_STEPS = 8
KILL_COOLDOWN_STEPS = 5
VENT_COOLDOWN_STEPS = 8
INITIAL_KILL_COOLDOWN_STEPS = 12
INITIAL_SABOTAGE_COOLDOWN_STEPS = 10
SABOTAGE_COOLDOWN_STEPS = 18
MEETING_DURATION_STEPS = 8
MEETING_DISCUSSION_TURNS = 2
MEETING_TOKEN_COUNT = 1
TASK_PROGRESS_STEPS = 2
NORMAL_VISION_RADIUS = 6
LIGHTS_CREW_VISION_RADIUS = 3
MAX_NAMED_VOTE_TARGETS = 32
VIBE_REPORT = "pin"
VIBE_CALL_MEETING = "compass"
VIBE_KILL = "target"
VIBE_VOTE_IMPOSTOR = "target"
VIBE_VOTE_SKIP = "asterisk"
VIBE_VOTE_AGENT_PREFIX = "vote_agent_"
VIBE_SABOTAGE_LIGHTS = "lightning"
VIBE_SABOTAGE_COMMS = "wave"
VIBE_SABOTAGE_OXYGEN = "water"
VIBE_SABOTAGE_REACTOR = "fire"
CREW_TASK_GOAL_MIN = 6
TASKS_PER_CREW_MEMBER = 2
CREW_TASK_GOAL_BUFFER = 3
FORCE_ROLE_ASSIGN_STEP = 1


def agent_id_resource(agent_id: int) -> str:
    return f"{AGENT_ID_RESOURCE_PREFIX}{agent_id}"


def vote_target_resource(agent_id: int) -> str:
    return f"{VOTE_TARGET_RESOURCE_PREFIX}{agent_id}"


def vote_target_vibe(agent_id: int) -> str:
    return f"{VIBE_VOTE_AGENT_PREFIX}{agent_id}"


def named_vote_target_count(num_agents: int) -> int:
    return min(num_agents, MAX_NAMED_VOTE_TARGETS)

TASK_STATION_NAMES = (
    "wiring_station",
    "navigation_station",
    "admin_station",
    "medbay_station",
    "weapons_station",
    "shields_station",
    "comms_station",
)
CRITICAL_STATION_NAMES = (
    "reactor_station",
    "oxygen_station",
    "lights_station",
)
INFO_STATION_NAMES = (
    "security_station",
    "emergency_button",
)
VENT_STATION_NAMES = (
    "cafeteria_vent",
    "admin_vent",
    "weapons_vent",
    "reactor_vent",
    "security_vent",
    "upper_engine_vent",
    "medbay_vent",
    "electrical_vent",
    "lower_engine_vent",
    "navigation_vent",
    "oxygen_vent",
    "shields_vent",
)
VENT_NETWORK_BY_NAME = {
    "cafeteria_vent": "vent:network:cafeteria_admin_weapons",
    "admin_vent": "vent:network:cafeteria_admin_weapons",
    "weapons_vent": "vent:network:cafeteria_admin_weapons",
    "reactor_vent": "vent:network:reactor_security_upper_engine",
    "security_vent": "vent:network:reactor_security_upper_engine",
    "upper_engine_vent": "vent:network:reactor_security_upper_engine",
    "medbay_vent": "vent:network:medbay_electrical_lower_engine",
    "electrical_vent": "vent:network:medbay_electrical_lower_engine",
    "lower_engine_vent": "vent:network:medbay_electrical_lower_engine",
    "navigation_vent": "vent:network:navigation_oxygen_shields",
    "oxygen_vent": "vent:network:navigation_oxygen_shields",
    "shields_vent": "vent:network:navigation_oxygen_shields",
}
INTERACTIVE_STATION_NAMES = tuple(
    dict.fromkeys((*TASK_STATION_NAMES, *CRITICAL_STATION_NAMES, *INFO_STATION_NAMES, *VENT_STATION_NAMES))
)


def impostor_count_for_lobby(num_agents: int) -> int:
    if num_agents >= 12:
        return 3
    if num_agents >= 8:
        return 2
    return 1


def crew_task_goal_for_lobby(num_agents: int) -> int:
    crew_count = num_agents - impostor_count_for_lobby(num_agents)
    if num_agents <= 5:
        return max(CREW_TASK_GOAL_MIN, crew_count * 4)
    if num_agents <= 8:
        return max(CREW_TASK_GOAL_MIN, crew_count * 3 - 1)
    return max(
        CREW_TASK_GOAL_MIN,
        crew_count * TASKS_PER_CREW_MEMBER - CREW_TASK_GOAL_BUFFER,
    )


def _complete_task_mutations(*extra_stats: str):
    mutations = [
        withdraw({TASK_RESOURCE: 1}),
        updateActor({TASK_PROGRESS_RESOURCE: -(TASK_PROGRESS_STEPS - 1)}),
        logActorAgentStat("tasks_completed"),
        logStatToGame("crew_tasks_completed"),
    ]
    for extra_stat in extra_stats:
        mutations.append(logActorAgentStat(extra_stat))
        mutations.append(logStatToGame(extra_stat))
    return mutations


def _task_handlers(*, online_required: bool = False, extra_stats: tuple[str, ...] = ()) -> list[Handler]:
    filters = [
        actorHas({ALIVE_RESOURCE: 1}),
        isNot(actorHas({MEETING_ACTIVE_RESOURCE: 1})),
        actorHas({ROLE_CREW: 1}),
        targetHas({TASK_RESOURCE: 1}),
    ]
    if online_required:
        filters.append(hasTag(STATION_ONLINE_TAG))
    return [
        Handler(
            name="complete_task",
            filters=[
                *filters,
                actorHas({TASK_PROGRESS_RESOURCE: TASK_PROGRESS_STEPS - 1}),
            ],
            mutations=_complete_task_mutations(*extra_stats),
        ),
        Handler(
            name="progress_task",
            filters=filters,
            mutations=[
                updateActor({TASK_PROGRESS_RESOURCE: 1}),
                logActorAgentStat("task_progress"),
                logStatToGame("crew_task_progress"),
            ],
        ),
    ]


def crew_station_config() -> GridObjectConfig:
    """Role station: first interaction sets crew role; role switches are blocked."""
    return GridObjectConfig(
        name="crew_station",
        on_use_handler=firstMatch(
            [
                Handler(
                    name="has_role",
                    filters=[actorHas({ALIVE_RESOURCE: 1}), actorHasAnyOf([ROLE_CREW, ROLE_IMPOSTOR])],
                    mutations=[],
                ),
                Handler(
                    name="become_crew",
                    filters=[actorHas({ALIVE_RESOURCE: 1})],
                    mutations=[updateActor({ROLE_CREW: 1})],
                ),
            ]
        ),
    )


def impostor_station_config() -> GridObjectConfig:
    """Role station: first interaction sets impostor role; role switches are blocked."""
    return GridObjectConfig(
        name="impostor_station",
        on_use_handler=firstMatch(
            [
                Handler(
                    name="has_role",
                    filters=[actorHas({ALIVE_RESOURCE: 1}), actorHasAnyOf([ROLE_CREW, ROLE_IMPOSTOR])],
                    mutations=[],
                ),
                Handler(
                    name="become_impostor",
                    filters=[actorHas({ALIVE_RESOURCE: 1})],
                    mutations=[updateActor({ROLE_IMPOSTOR: 1})],
                ),
            ]
        ),
    )


def task_station_config(station_name: str) -> GridObjectConfig:
    """Regular crew task station in a Skeld room."""
    return GridObjectConfig(
        name=station_name,
        tags=[TASK_STATION_TAG, STATION_ONLINE_TAG],
        inventory=InventoryConfig(initial={TASK_RESOURCE: 3}, default_limit=3),
        on_use_handler=firstMatch(_task_handlers()),
    )


def admin_station_config() -> GridObjectConfig:
    return GridObjectConfig(
        name="admin_station",
        tags=[TASK_STATION_TAG, INFO_STATION_TAG, STATION_ONLINE_TAG],
        inventory=InventoryConfig(initial={TASK_RESOURCE: 3}, default_limit=3),
        on_use_handler=firstMatch(
            [
                *_task_handlers(online_required=True, extra_stats=("admin_checks",)),
                Handler(
                    name="check_admin_table",
                    filters=[
                        actorHas({ALIVE_RESOURCE: 1}),
                        isNot(actorHas({MEETING_ACTIVE_RESOURCE: 1})),
                        actorHas({ROLE_CREW: 1}),
                        hasTag(STATION_ONLINE_TAG),
                    ],
                    mutations=[
                        logActorAgentStat("admin_checks"),
                        logStatToGame("admin_checks"),
                    ],
                ),
            ]
        ),
    )


def comms_station_config() -> GridObjectConfig:
    return GridObjectConfig(
        name="comms_station",
        tags=[TASK_STATION_TAG, INFO_STATION_TAG, SYSTEM_COMMS_TAG, STATION_ONLINE_TAG],
        inventory=InventoryConfig(
            initial={TASK_RESOURCE: 3, CRITICAL_TIMER_RESOURCE: 0},
            default_limit=max(TASK_REFILL_PERIOD, COMMS_SABOTAGE_TIMER_STEPS),
        ),
        on_use_handler=firstMatch(
            [
                Handler(
                    name="repair_comms",
                    filters=[
                        actorHas({ALIVE_RESOURCE: 1}),
                        isNot(actorHas({MEETING_ACTIVE_RESOURCE: 1})),
                        actorHas({ROLE_CREW: 1}),
                        hasTag(STATION_SABOTAGED_TAG),
                    ],
                    mutations=[
                        removeTag(STATION_SABOTAGED_TAG),
                        addTag(STATION_ONLINE_TAG),
                        updateTarget({CRITICAL_TIMER_RESOURCE: -COMMS_SABOTAGE_TIMER_STEPS}),
                        logActorAgentStat("repairs"),
                        logStatToGame("crew_repairs"),
                        logActorAgentStat("comms_checks"),
                        logStatToGame("comms_checks"),
                        logStatToGame("comms_repairs"),
                    ],
                ),
                *_task_handlers(online_required=True, extra_stats=("comms_checks",)),
                Handler(
                    name="check_comms_console",
                    filters=[
                        actorHas({ALIVE_RESOURCE: 1}),
                        isNot(actorHas({MEETING_ACTIVE_RESOURCE: 1})),
                        actorHas({ROLE_CREW: 1}),
                        hasTag(STATION_ONLINE_TAG),
                    ],
                    mutations=[
                        logActorAgentStat("comms_checks"),
                        logStatToGame("comms_checks"),
                    ],
                ),
            ]
        ),
    )


def critical_station_config(
    station_name: str,
    *,
    system_tag: str,
    timer_steps: int,
    sabotage_cooldown_steps: int = SABOTAGE_COOLDOWN_STEPS,
    sabotage_stat: str,
    repair_stat: str,
) -> GridObjectConfig:
    """Critical sabotage station used for reactor, oxygen, and lights."""
    return GridObjectConfig(
        name=station_name,
        tags=[CRITICAL_STATION_TAG, system_tag, STATION_ONLINE_TAG],
        inventory=InventoryConfig(initial={CRITICAL_TIMER_RESOURCE: 0}, default_limit=timer_steps),
        on_use_handler=firstMatch(
            [
                Handler(
                    name="repair_critical_system",
                    filters=[
                        actorHas({ALIVE_RESOURCE: 1}),
                        isNot(actorHas({MEETING_ACTIVE_RESOURCE: 1})),
                        actorHas({ROLE_CREW: 1}),
                        hasTag(STATION_SABOTAGED_TAG),
                    ],
                    mutations=[
                        removeTag(STATION_SABOTAGED_TAG),
                        addTag(STATION_ONLINE_TAG),
                        updateTarget({CRITICAL_TIMER_RESOURCE: -timer_steps}),
                        logActorAgentStat("repairs"),
                        logStatToGame("crew_repairs"),
                        logStatToGame(repair_stat),
                    ],
                ),
                Handler(
                    name="trigger_critical_sabotage",
                    filters=[
                        actorHas({ALIVE_RESOURCE: 1}),
                        isNot(actorHas({MEETING_ACTIVE_RESOURCE: 1})),
                        actorHas({ROLE_IMPOSTOR: 1}),
                        isNot(actorHas({SABOTAGE_COOLDOWN_RESOURCE: 1})),
                        hasTag(STATION_ONLINE_TAG),
                    ],
                    mutations=[
                        updateTarget({CRITICAL_TIMER_RESOURCE: timer_steps}),
                        updateActor({SABOTAGE_COOLDOWN_RESOURCE: sabotage_cooldown_steps}),
                        removeTag(STATION_ONLINE_TAG),
                        addTag(STATION_SABOTAGED_TAG),
                        logActorAgentStat("sabotages"),
                        logStatToGame("impostor_sabotages"),
                        logStatToGame(sabotage_stat),
                    ],
                ),
            ]
        ),
    )


def security_station_config() -> GridObjectConfig:
    """Security room camera console."""
    return GridObjectConfig(
        name="security_station",
        tags=[INFO_STATION_TAG, STATION_ONLINE_TAG],
        on_use_handler=Handler(
            name="check_cameras",
            filters=[
                actorHas({ALIVE_RESOURCE: 1}),
                isNot(actorHas({MEETING_ACTIVE_RESOURCE: 1})),
                actorHas({ROLE_CREW: 1}),
                hasTag(STATION_ONLINE_TAG),
            ],
            mutations=[
                logActorAgentStat("camera_checks"),
                logStatToGame("camera_checks"),
            ],
        ),
    )


def emergency_button_config() -> GridObjectConfig:
    return GridObjectConfig(
        name="emergency_button",
        tags=[MEETING_STATION_TAG, STATION_ONLINE_TAG],
    )


def vent_station_config(
    station_name: str,
    *,
    network_tag: str,
    cooldown_steps: int = VENT_COOLDOWN_STEPS,
) -> GridObjectConfig:
    return GridObjectConfig(
        name=station_name,
        tags=[VENT_STATION_TAG, network_tag],
        on_use_handler=Handler(
            name="vent_travel",
            filters=[
                actorHas({ALIVE_RESOURCE: 1}),
                isNot(actorHas({MEETING_ACTIVE_RESOURCE: 1})),
                actorHas({ROLE_IMPOSTOR: 1}),
                isNot(actorHas({VENT_COOLDOWN_RESOURCE: 1})),
            ],
            mutations=[
                queryPlaceAdjacent(query(network_tag, isNot(maxDistance(1)))),
                updateActor({VENT_COOLDOWN_RESOURCE: cooldown_steps}),
                logActorAgentStat("vents"),
                logStatToGame("vents_used"),
            ],
        ),
    )
