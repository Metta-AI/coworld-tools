"""Among Us critical-system synchronization and timer events."""

from __future__ import annotations

from mettagrid.cogame.core import CoGameMissionVariant, Deps
from amongcogs.constants import (
    ALIVE_RESOURCE,
    COMMS_ALERT_RESOURCE,
    CRITICAL_STATION_TAG,
    CRITICAL_TIMER_RESOURCE,
    LIGHTS_ALERT_RESOURCE,
    MEETING_ACTIVE_RESOURCE,
    OXYGEN_ALERT_RESOURCE,
    REACTOR_ALERT_RESOURCE,
    ROLE_CREW,
    ROLE_IMPOSTOR,
    SABOTAGE_COOLDOWN_RESOURCE,
    STATION_ONLINE_TAG,
    STATION_SABOTAGED_TAG,
    SYSTEM_COMMS_TAG,
    SYSTEM_LIGHTS_TAG,
    SYSTEM_OXYGEN_TAG,
    SYSTEM_REACTOR_TAG,
    VIBE_SABOTAGE_COMMS,
    VIBE_SABOTAGE_LIGHTS,
    VIBE_SABOTAGE_OXYGEN,
    VIBE_SABOTAGE_REACTOR,
    admin_station_config,
    comms_station_config,
    critical_station_config,
    security_station_config,
)
from amongcogs.game.common import (
    comms_sabotage_timer_steps,
    lights_sabotage_timer_steps,
    oxygen_sabotage_timer_steps,
    reactor_sabotage_timer_steps,
    sabotage_cooldown_steps,
)
from amongcogs.game.tasks import TasksVariant
from mettagrid.config.event_config import EventConfig, periodic
from mettagrid.config.filter import GameValueFilter, HandlerTarget, hasTag, isNot, targetHas, targetVibe
from mettagrid.config.game_value import num
from mettagrid.config.handler_config import addTag, queryDelta, removeTag, updateTarget
from mettagrid.config.mettagrid_config import MettaGridConfig
from mettagrid.config.mutation.stats_mutation import logActorAgentStat, logStatToGame
from mettagrid.config.query import query
from mettagrid.config.tag import typeTag


class StationEventsVariant(CoGameMissionVariant):
    name: str = "station_events"
    description: str = "Critical sabotage synchronization and reactor/O2 timer events."

    def dependencies(self) -> Deps:
        return Deps(required=[TasksVariant])

    def modify_env(self, mission, env: MettaGridConfig) -> None:
        reactor_steps = reactor_sabotage_timer_steps(mission)
        oxygen_steps = oxygen_sabotage_timer_steps(mission)
        lights_steps = lights_sabotage_timer_steps(mission)
        comms_steps = comms_sabotage_timer_steps(mission)
        sabotage_steps = sabotage_cooldown_steps(mission)
        max_steps = env.game.max_steps
        alive_agents_query = query(typeTag("agent"), [targetHas({ALIVE_RESOURCE: 1})])
        alive_crew_query = query(typeTag("agent"), [targetHas({ROLE_CREW: 1, ALIVE_RESOURCE: 1})])
        alive_impostors_query = query(typeTag("agent"), [targetHas({ROLE_IMPOSTOR: 1, ALIVE_RESOURCE: 1})])
        sabotage_intent_priority = 10
        sabotage_activate_priority = 20
        no_active_critical = isNot(
            GameValueFilter(
                target=HandlerTarget.TARGET,
                value=num(CRITICAL_STATION_TAG, [targetHas({CRITICAL_TIMER_RESOURCE: 1})]),
                min=1,
            )
        )

        env.game.objects["reactor_station"] = critical_station_config(
            "reactor_station",
            system_tag=SYSTEM_REACTOR_TAG,
            timer_steps=reactor_steps,
            sabotage_cooldown_steps=sabotage_steps,
            sabotage_stat="reactor_sabotages",
            repair_stat="reactor_repairs",
        )
        env.game.objects["oxygen_station"] = critical_station_config(
            "oxygen_station",
            system_tag=SYSTEM_OXYGEN_TAG,
            timer_steps=oxygen_steps,
            sabotage_cooldown_steps=sabotage_steps,
            sabotage_stat="oxygen_sabotages",
            repair_stat="oxygen_repairs",
        )
        env.game.objects["lights_station"] = critical_station_config(
            "lights_station",
            system_tag=SYSTEM_LIGHTS_TAG,
            timer_steps=lights_steps,
            sabotage_cooldown_steps=sabotage_steps,
            sabotage_stat="lights_sabotages",
            repair_stat="lights_repairs",
        )
        env.game.objects["admin_station"] = admin_station_config()
        env.game.objects["comms_station"] = comms_station_config()
        env.game.objects["security_station"] = security_station_config()
        env.game.events["impostor_sabotage_cooldown_tick"] = EventConfig(
            name="impostor_sabotage_cooldown_tick",
            target_query=query(typeTag("agent")),
            timesteps=periodic(start=1, period=1, end=max_steps),
            filters=[targetHas({ROLE_IMPOSTOR: 1, SABOTAGE_COOLDOWN_RESOURCE: 1})],
            mutations=[updateTarget({SABOTAGE_COOLDOWN_RESOURCE: -1})],
        )
        env.game.events["impostor_sabotage_lights_intent"] = EventConfig(
            name="impostor_sabotage_lights_intent",
            target_query=query(typeTag("agent")),
            timesteps=periodic(start=1, period=1, end=max_steps),
            priority=sabotage_intent_priority,
            filters=[
                targetHas({ROLE_IMPOSTOR: 1, ALIVE_RESOURCE: 1}),
                isNot(targetHas({SABOTAGE_COOLDOWN_RESOURCE: 1})),
                isNot(targetHas({MEETING_ACTIVE_RESOURCE: 1})),
                targetVibe(VIBE_SABOTAGE_LIGHTS),
                no_active_critical,
            ],
            mutations=[
                queryDelta(
                    query(SYSTEM_LIGHTS_TAG, [hasTag(STATION_ONLINE_TAG)]),
                    {CRITICAL_TIMER_RESOURCE: lights_steps},
                ),
                queryDelta(alive_impostors_query, {SABOTAGE_COOLDOWN_RESOURCE: sabotage_steps}),
                queryDelta(alive_crew_query, {LIGHTS_ALERT_RESOURCE: 1}),
                logActorAgentStat("sabotages"),
                logStatToGame("impostor_sabotages"),
                logStatToGame("lights_sabotages"),
            ],
            max_targets=1,
        )
        env.game.events["impostor_sabotage_comms_intent"] = EventConfig(
            name="impostor_sabotage_comms_intent",
            target_query=query(typeTag("agent")),
            timesteps=periodic(start=1, period=1, end=max_steps),
            priority=sabotage_intent_priority,
            filters=[
                targetHas({ROLE_IMPOSTOR: 1, ALIVE_RESOURCE: 1}),
                isNot(targetHas({SABOTAGE_COOLDOWN_RESOURCE: 1})),
                isNot(targetHas({MEETING_ACTIVE_RESOURCE: 1})),
                targetVibe(VIBE_SABOTAGE_COMMS),
                no_active_critical,
                isNot(
                    GameValueFilter(
                        target=HandlerTarget.TARGET,
                        value=num(SYSTEM_COMMS_TAG, [targetHas({CRITICAL_TIMER_RESOURCE: 1})]),
                        min=1,
                    )
                ),
            ],
            mutations=[
                queryDelta(
                    query(SYSTEM_COMMS_TAG, [hasTag(STATION_ONLINE_TAG)]),
                    {CRITICAL_TIMER_RESOURCE: comms_steps},
                ),
                queryDelta(alive_impostors_query, {SABOTAGE_COOLDOWN_RESOURCE: sabotage_steps}),
                queryDelta(alive_agents_query, {COMMS_ALERT_RESOURCE: 1}),
                logActorAgentStat("sabotages"),
                logStatToGame("impostor_sabotages"),
                logStatToGame("comms_sabotages"),
            ],
            max_targets=1,
        )
        env.game.events["impostor_sabotage_oxygen_intent"] = EventConfig(
            name="impostor_sabotage_oxygen_intent",
            target_query=query(typeTag("agent")),
            timesteps=periodic(start=1, period=1, end=max_steps),
            priority=sabotage_intent_priority,
            filters=[
                targetHas({ROLE_IMPOSTOR: 1, ALIVE_RESOURCE: 1}),
                isNot(targetHas({SABOTAGE_COOLDOWN_RESOURCE: 1})),
                isNot(targetHas({MEETING_ACTIVE_RESOURCE: 1})),
                targetVibe(VIBE_SABOTAGE_OXYGEN),
                no_active_critical,
            ],
            mutations=[
                queryDelta(
                    query(SYSTEM_OXYGEN_TAG, [hasTag(STATION_ONLINE_TAG)]),
                    {CRITICAL_TIMER_RESOURCE: oxygen_steps},
                ),
                queryDelta(alive_impostors_query, {SABOTAGE_COOLDOWN_RESOURCE: sabotage_steps}),
                queryDelta(alive_agents_query, {OXYGEN_ALERT_RESOURCE: 1}),
                logActorAgentStat("sabotages"),
                logStatToGame("impostor_sabotages"),
                logStatToGame("oxygen_sabotages"),
            ],
            max_targets=1,
        )
        env.game.events["impostor_sabotage_reactor_intent"] = EventConfig(
            name="impostor_sabotage_reactor_intent",
            target_query=query(typeTag("agent")),
            timesteps=periodic(start=1, period=1, end=max_steps),
            priority=sabotage_intent_priority,
            filters=[
                targetHas({ROLE_IMPOSTOR: 1, ALIVE_RESOURCE: 1}),
                isNot(targetHas({SABOTAGE_COOLDOWN_RESOURCE: 1})),
                isNot(targetHas({MEETING_ACTIVE_RESOURCE: 1})),
                targetVibe(VIBE_SABOTAGE_REACTOR),
                no_active_critical,
            ],
            mutations=[
                queryDelta(
                    query(SYSTEM_REACTOR_TAG, [hasTag(STATION_ONLINE_TAG)]),
                    {CRITICAL_TIMER_RESOURCE: reactor_steps},
                ),
                queryDelta(alive_impostors_query, {SABOTAGE_COOLDOWN_RESOURCE: sabotage_steps}),
                queryDelta(alive_agents_query, {REACTOR_ALERT_RESOURCE: 1}),
                logActorAgentStat("sabotages"),
                logStatToGame("impostor_sabotages"),
                logStatToGame("reactor_sabotages"),
            ],
            max_targets=1,
        )
        env.game.events["activate_reactor_sabotage"] = EventConfig(
            name="activate_reactor_sabotage",
            target_query=query(SYSTEM_REACTOR_TAG),
            timesteps=periodic(start=1, period=1, end=max_steps),
            priority=sabotage_activate_priority,
            filters=[hasTag(STATION_ONLINE_TAG), targetHas({CRITICAL_TIMER_RESOURCE: reactor_steps})],
            mutations=[removeTag(STATION_ONLINE_TAG), addTag(STATION_SABOTAGED_TAG)],
        )
        env.game.events["activate_oxygen_sabotage"] = EventConfig(
            name="activate_oxygen_sabotage",
            target_query=query(SYSTEM_OXYGEN_TAG),
            timesteps=periodic(start=1, period=1, end=max_steps),
            priority=sabotage_activate_priority,
            filters=[hasTag(STATION_ONLINE_TAG), targetHas({CRITICAL_TIMER_RESOURCE: oxygen_steps})],
            mutations=[removeTag(STATION_ONLINE_TAG), addTag(STATION_SABOTAGED_TAG)],
        )
        env.game.events["activate_lights_sabotage"] = EventConfig(
            name="activate_lights_sabotage",
            target_query=query(SYSTEM_LIGHTS_TAG),
            timesteps=periodic(start=1, period=1, end=max_steps),
            priority=sabotage_activate_priority,
            filters=[hasTag(STATION_ONLINE_TAG), targetHas({CRITICAL_TIMER_RESOURCE: lights_steps})],
            mutations=[removeTag(STATION_ONLINE_TAG), addTag(STATION_SABOTAGED_TAG)],
        )
        env.game.events["sync_lights_alert"] = EventConfig(
            name="sync_lights_alert",
            target_query=query(SYSTEM_LIGHTS_TAG),
            timesteps=periodic(start=1, period=1, end=max_steps),
            priority=sabotage_activate_priority + 1,
            filters=[targetHas({CRITICAL_TIMER_RESOURCE: 1})],
            mutations=[queryDelta(alive_crew_query, {LIGHTS_ALERT_RESOURCE: 1})],
            max_targets=1,
        )
        env.game.events["activate_comms_sabotage"] = EventConfig(
            name="activate_comms_sabotage",
            target_query=query(SYSTEM_COMMS_TAG),
            timesteps=periodic(start=1, period=1, end=max_steps),
            priority=sabotage_activate_priority,
            filters=[hasTag(STATION_ONLINE_TAG), targetHas({CRITICAL_TIMER_RESOURCE: comms_steps})],
            mutations=[removeTag(STATION_ONLINE_TAG), addTag(STATION_SABOTAGED_TAG)],
        )
        env.game.events["disable_admin_during_comms_sabotage"] = EventConfig(
            name="disable_admin_during_comms_sabotage",
            target_query=query(typeTag("admin_station")),
            timesteps=periodic(start=1, period=1, end=max_steps),
            filters=[
                hasTag(STATION_ONLINE_TAG),
                GameValueFilter(
                    target=HandlerTarget.TARGET,
                    value=num(SYSTEM_COMMS_TAG, [hasTag(STATION_SABOTAGED_TAG)]),
                    min=1,
                ),
            ],
            mutations=[removeTag(STATION_ONLINE_TAG), addTag(STATION_SABOTAGED_TAG)],
        )
        env.game.events["disable_security_during_comms_sabotage"] = EventConfig(
            name="disable_security_during_comms_sabotage",
            target_query=query(typeTag("security_station")),
            timesteps=periodic(start=1, period=1, end=max_steps),
            filters=[
                hasTag(STATION_ONLINE_TAG),
                GameValueFilter(
                    target=HandlerTarget.TARGET,
                    value=num(SYSTEM_COMMS_TAG, [hasTag(STATION_SABOTAGED_TAG)]),
                    min=1,
                ),
            ],
            mutations=[removeTag(STATION_ONLINE_TAG), addTag(STATION_SABOTAGED_TAG)],
        )
        env.game.events["restore_admin_after_comms_sabotage"] = EventConfig(
            name="restore_admin_after_comms_sabotage",
            target_query=query(typeTag("admin_station")),
            timesteps=periodic(start=1, period=1, end=max_steps),
            filters=[
                isNot(hasTag(STATION_ONLINE_TAG)),
                isNot(
                    GameValueFilter(
                        target=HandlerTarget.TARGET,
                        value=num(SYSTEM_COMMS_TAG, [hasTag(STATION_SABOTAGED_TAG)]),
                        min=1,
                    )
                ),
            ],
            mutations=[removeTag(STATION_SABOTAGED_TAG), addTag(STATION_ONLINE_TAG)],
        )
        env.game.events["restore_security_after_comms_sabotage"] = EventConfig(
            name="restore_security_after_comms_sabotage",
            target_query=query(typeTag("security_station")),
            timesteps=periodic(start=1, period=1, end=max_steps),
            filters=[
                isNot(hasTag(STATION_ONLINE_TAG)),
                isNot(
                    GameValueFilter(
                        target=HandlerTarget.TARGET,
                        value=num(SYSTEM_COMMS_TAG, [hasTag(STATION_SABOTAGED_TAG)]),
                        min=1,
                    )
                ),
            ],
            mutations=[removeTag(STATION_SABOTAGED_TAG), addTag(STATION_ONLINE_TAG)],
        )

        env.game.events["sync_reactor_sabotage"] = EventConfig(
            name="sync_reactor_sabotage",
            target_query=query(SYSTEM_REACTOR_TAG),
            timesteps=periodic(start=1, period=1, end=max_steps),
            filters=[
                hasTag(STATION_ONLINE_TAG),
                GameValueFilter(
                    target=HandlerTarget.TARGET,
                    value=num(
                        SYSTEM_REACTOR_TAG,
                        [
                            hasTag(STATION_SABOTAGED_TAG),
                            targetHas({CRITICAL_TIMER_RESOURCE: 1}),
                        ],
                    ),
                    min=1,
                ),
            ],
            mutations=[
                removeTag(STATION_ONLINE_TAG),
                addTag(STATION_SABOTAGED_TAG),
                updateTarget({CRITICAL_TIMER_RESOURCE: reactor_steps}),
            ],
        )
        env.game.events["sync_oxygen_sabotage"] = EventConfig(
            name="sync_oxygen_sabotage",
            target_query=query(SYSTEM_OXYGEN_TAG),
            timesteps=periodic(start=1, period=1, end=max_steps),
            filters=[
                hasTag(STATION_ONLINE_TAG),
                GameValueFilter(
                    target=HandlerTarget.TARGET,
                    value=num(
                        SYSTEM_OXYGEN_TAG,
                        [
                            hasTag(STATION_SABOTAGED_TAG),
                            targetHas({CRITICAL_TIMER_RESOURCE: 1}),
                        ],
                    ),
                    min=1,
                ),
            ],
            mutations=[
                removeTag(STATION_ONLINE_TAG),
                addTag(STATION_SABOTAGED_TAG),
                updateTarget({CRITICAL_TIMER_RESOURCE: oxygen_steps}),
            ],
        )

        env.game.events["reactor_timer_tick"] = EventConfig(
            name="reactor_timer_tick",
            target_query=query(SYSTEM_REACTOR_TAG),
            filters=[hasTag(STATION_SABOTAGED_TAG), targetHas({CRITICAL_TIMER_RESOURCE: 1})],
            timesteps=periodic(start=1, period=1, end=max_steps),
            mutations=[updateTarget({CRITICAL_TIMER_RESOURCE: -1})],
        )
        env.game.events["oxygen_timer_tick"] = EventConfig(
            name="oxygen_timer_tick",
            target_query=query(SYSTEM_OXYGEN_TAG),
            filters=[hasTag(STATION_SABOTAGED_TAG), targetHas({CRITICAL_TIMER_RESOURCE: 1})],
            timesteps=periodic(start=1, period=1, end=max_steps),
            mutations=[updateTarget({CRITICAL_TIMER_RESOURCE: -1})],
        )

        env.game.events["resolve_reactor_sabotage"] = EventConfig(
            name="resolve_reactor_sabotage",
            target_query=query(SYSTEM_REACTOR_TAG),
            timesteps=periodic(start=1, period=1, end=max_steps),
            filters=[
                GameValueFilter(
                    target=HandlerTarget.TARGET,
                    value=num(SYSTEM_REACTOR_TAG, [targetHas({CRITICAL_TIMER_RESOURCE: 1})]),
                    min=1,
                ),
                isNot(
                    GameValueFilter(
                        target=HandlerTarget.TARGET,
                        value=num(SYSTEM_REACTOR_TAG, [hasTag(STATION_SABOTAGED_TAG)]),
                        min=1,
                    )
                ),
            ],
            mutations=[
                removeTag(STATION_SABOTAGED_TAG),
                addTag(STATION_ONLINE_TAG),
                updateTarget({CRITICAL_TIMER_RESOURCE: -reactor_steps}),
                logStatToGame("reactor_resolved"),
            ],
        )
        env.game.events["clear_reactor_alert"] = EventConfig(
            name="clear_reactor_alert",
            target_query=query(typeTag("agent")),
            timesteps=periodic(start=1, period=1, end=max_steps),
            filters=[
                targetHas({REACTOR_ALERT_RESOURCE: 1}),
                isNot(
                    GameValueFilter(
                        target=HandlerTarget.TARGET,
                        value=num(SYSTEM_REACTOR_TAG, [targetHas({CRITICAL_TIMER_RESOURCE: 1})]),
                        min=1,
                    )
                ),
            ],
            mutations=[updateTarget({REACTOR_ALERT_RESOURCE: -1})],
        )
        env.game.events["resolve_oxygen_sabotage"] = EventConfig(
            name="resolve_oxygen_sabotage",
            target_query=query(SYSTEM_OXYGEN_TAG),
            timesteps=periodic(start=1, period=1, end=max_steps),
            filters=[
                GameValueFilter(
                    target=HandlerTarget.TARGET,
                    value=num(SYSTEM_OXYGEN_TAG, [targetHas({CRITICAL_TIMER_RESOURCE: 1})]),
                    min=1,
                ),
                isNot(
                    GameValueFilter(
                        target=HandlerTarget.TARGET,
                        value=num(SYSTEM_OXYGEN_TAG, [hasTag(STATION_SABOTAGED_TAG)]),
                        min=1,
                    )
                ),
            ],
            mutations=[
                removeTag(STATION_SABOTAGED_TAG),
                addTag(STATION_ONLINE_TAG),
                updateTarget({CRITICAL_TIMER_RESOURCE: -oxygen_steps}),
                logStatToGame("oxygen_resolved"),
            ],
        )
        env.game.events["clear_oxygen_alert"] = EventConfig(
            name="clear_oxygen_alert",
            target_query=query(typeTag("agent")),
            timesteps=periodic(start=1, period=1, end=max_steps),
            filters=[
                targetHas({OXYGEN_ALERT_RESOURCE: 1}),
                isNot(
                    GameValueFilter(
                        target=HandlerTarget.TARGET,
                        value=num(SYSTEM_OXYGEN_TAG, [targetHas({CRITICAL_TIMER_RESOURCE: 1})]),
                        min=1,
                    )
                ),
            ],
            mutations=[updateTarget({OXYGEN_ALERT_RESOURCE: -1})],
        )
        env.game.events["clear_lights_alert"] = EventConfig(
            name="clear_lights_alert",
            target_query=query(typeTag("agent")),
            timesteps=periodic(start=1, period=1, end=max_steps),
            filters=[
                targetHas({LIGHTS_ALERT_RESOURCE: 1}),
                isNot(
                    GameValueFilter(
                        target=HandlerTarget.TARGET,
                        value=num(SYSTEM_LIGHTS_TAG, [targetHas({CRITICAL_TIMER_RESOURCE: 1})]),
                        min=1,
                    )
                ),
            ],
            mutations=[updateTarget({LIGHTS_ALERT_RESOURCE: -1})],
        )
        env.game.events["clear_comms_alert"] = EventConfig(
            name="clear_comms_alert",
            target_query=query(typeTag("agent")),
            timesteps=periodic(start=1, period=1, end=max_steps),
            filters=[
                targetHas({COMMS_ALERT_RESOURCE: 1}),
                isNot(
                    GameValueFilter(
                        target=HandlerTarget.TARGET,
                        value=num(SYSTEM_COMMS_TAG, [targetHas({CRITICAL_TIMER_RESOURCE: 1})]),
                        min=1,
                    )
                ),
            ],
            mutations=[updateTarget({COMMS_ALERT_RESOURCE: -1})],
        )
