from __future__ import annotations

from amongcogs.constants import (
    CREW_TASK_GOAL_MIN,
    LIGHTS_ALERT_RESOURCE,
    crew_task_goal_for_lobby,
    critical_station_config,
    SABOTAGE_COOLDOWN_RESOURCE,
    VENT_COOLDOWN_RESOURCE,
    VENT_COOLDOWN_STEPS,
)
from amongcogs.game import (
    ALIVE_RESOURCE,
    CORPSE_RESOURCE,
    CRITICAL_TIMER_RESOURCE,
    EJECTED_RESOURCE,
    KILL_COOLDOWN_RESOURCE,
    MEETING_ACTIVE_RESOURCE,
    MEETING_BALLOT_RESOURCE,
    MEETING_DISCUSSION_RESOURCE,
    MEETING_DISCUSSION_TIMER_RESOURCE,
    MEETING_REPORTED_BODY_RESOURCE,
    MEETING_TIMER_RESOURCE,
    MEETING_TOKEN_RESOURCE,
    ROLE_CREW,
    ROLE_IMPOSTOR,
    STATION_ONLINE_TAG,
    STATION_SABOTAGED_TAG,
    TASK_RESOURCE,
    TASK_PROGRESS_STEPS,
    TASK_PROGRESS_RESOURCE,
    TASK_STATION_NAMES,
    VIBE_KILL,
    VIBE_REPORT,
    VIBE_SABOTAGE_COMMS,
    VIBE_SABOTAGE_LIGHTS,
    VIBE_SABOTAGE_OXYGEN,
    VOTE_IMPOSTOR_RESOURCE,
    VOTE_SKIP_RESOURCE,
    VOTED_RESOURCE,
    WIN_REWARD_RESOURCE,
    agent_id_resource,
    crew_station_config,
    impostor_station_config,
    task_station_config,
    vote_target_resource,
    vote_target_vibe,
)
from amongcogs.runtime import make_game
from mettagrid.config.filter.game_value_filter import GameValueFilter
from mettagrid.config.game_value import Scope, StatValue
from mettagrid.config.mettagrid_config import (
    ActionsConfig,
    AgentConfig,
    GameConfig,
    InventoryConfig,
    MettaGridConfig,
    MoveActionConfig,
    NoopActionConfig,
    ResourceLimitsConfig,
    WallConfig,
)
from mettagrid.map_builder.ascii import AsciiMapBuilder
from mettagrid.simulator import Action, Simulation


def _test_agent() -> AgentConfig:
    return AgentConfig(
        inventory=InventoryConfig(
            initial={ALIVE_RESOURCE: 1, MEETING_TOKEN_RESOURCE: 1},
            limits={
                "role": ResourceLimitsConfig(base=1, max=1, resources=[ROLE_CREW, ROLE_IMPOSTOR]),
                "task": ResourceLimitsConfig(base=100, max=100, resources=[TASK_RESOURCE]),
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
                    base=2,
                    max=2,
                    resources=[MEETING_DISCUSSION_TIMER_RESOURCE],
                ),
                "meeting_token": ResourceLimitsConfig(
                    base=1,
                    max=1,
                    resources=[MEETING_TOKEN_RESOURCE],
                ),
                "meeting_timer": ResourceLimitsConfig(
                    base=6,
                    max=6,
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
                "kill_cooldown": ResourceLimitsConfig(base=8, max=8, resources=[KILL_COOLDOWN_RESOURCE]),
                "sabotage_cooldown": ResourceLimitsConfig(base=18, max=18, resources=[SABOTAGE_COOLDOWN_RESOURCE]),
            },
        ),
    )


def _make_single_station_sim(
    station_name: str,
    station_cfg,
    agent_initial: dict[str, int] | None = None,
) -> Simulation:
    cfg = MettaGridConfig(
        game=GameConfig(
            num_agents=1,
            max_steps=100,
            resource_names=[
                ROLE_CREW,
                ROLE_IMPOSTOR,
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
                KILL_COOLDOWN_RESOURCE,
                SABOTAGE_COOLDOWN_RESOURCE,
                VENT_COOLDOWN_RESOURCE,
                EJECTED_RESOURCE,
                CRITICAL_TIMER_RESOURCE,
                WIN_REWARD_RESOURCE,
            ],
            actions=ActionsConfig(noop=NoopActionConfig(), move=MoveActionConfig()),
            agents=[_test_agent()],
            objects={
                "wall": WallConfig(name="wall"),
                station_name: station_cfg,
            },
            tags=[STATION_SABOTAGED_TAG],
            map_builder=AsciiMapBuilder.Config(
                map_data=[
                    ["#", "#", "#", "#", "#"],
                    ["#", ".", ".", ".", "#"],
                    ["#", "@", "S", ".", "#"],
                    ["#", ".", ".", ".", "#"],
                    ["#", "#", "#", "#", "#"],
                ],
                char_to_map_name={
                    "#": "wall",
                    ".": "empty",
                    "@": "agent.agent",
                    "S": station_name,
                },
            ),
        )
    )
    sim = Simulation(cfg, seed=42)
    if agent_initial is not None:
        sim.agent(0).set_inventory({ALIVE_RESOURCE: 1, MEETING_TOKEN_RESOURCE: 1, **agent_initial})
    return sim


def _move_east(sim: Simulation) -> None:
    sim.agent(0).set_action("move_east")
    sim.step()


def _step_with_actions(sim: Simulation, actions_by_agent: dict[int, str] | None = None) -> None:
    actions_by_agent = actions_by_agent or {}
    for agent_id in range(sim.num_agents):
        sim.agent(agent_id).set_action(actions_by_agent.get(agent_id, "noop"))
    sim.step()


def _station_task_inventory(sim: Simulation, station_name: str) -> int:
    for obj in sim.grid_objects(ignore_types=["wall", "agent"]).values():
        if obj.get("type_name") == station_name:
            return int(obj.get(f"inv:{TASK_RESOURCE}", 0))
    raise AssertionError(f"Station {station_name!r} not found in grid objects")


def _total_station_tasks(sim: Simulation) -> int:
    total = 0
    for obj in sim.grid_objects(ignore_types=["wall", "agent"]).values():
        if obj.get("type_name") in TASK_STATION_NAMES:
            total += int(obj.get(f"inv:{TASK_RESOURCE}", 0))
    return total


def _station_tag_count(sim: Simulation, tag_name: str, station_types: tuple[str, ...] | None = None) -> int:
    tag_names = sim.config.game.id_map().tag_names()
    tag_id = tag_names.index(tag_name)
    station_names = set(station_types or TASK_STATION_NAMES)
    count = 0
    for obj in sim.grid_objects(ignore_types=["wall", "agent"]).values():
        if obj.get("type_name") in station_names and tag_id in obj.get("tag_ids", []):
            count += 1
    return count


def _step_all_noop(sim: Simulation, n: int) -> None:
    for _ in range(n):
        if sim.is_done():
            return
        for agent_id in range(sim.num_agents):
            sim.agent(agent_id).set_action("noop")
        sim.step()


def _agent_position(sim: Simulation, agent_id: int = 0) -> tuple[int, int]:
    for obj in sim.grid_objects(ignore_types=["wall"]).values():
        if obj.get("type_name") == "agent" and int(obj.get("agent_id", -1)) == agent_id:
            return int(obj["r"]), int(obj["c"])
    raise AssertionError(f"Agent {agent_id} not found")


def _observation_token_names(sim: Simulation, agent_id: int = 0) -> set[str]:
    return {token.feature.name for token in sim.agent(agent_id).observation.tokens if token.location is not None}


def _object_has_tag(sim: Simulation, type_name: str, tag_name: str) -> bool:
    tag_names = sim.config.game.id_map().tag_names()
    tag_id = tag_names.index(tag_name)
    for obj in sim.grid_objects(ignore_types=["wall", "agent"]).values():
        if obj.get("type_name") == type_name:
            return tag_id in obj.get("tag_ids", [])
    raise AssertionError(f"Object {type_name!r} not found")


def test_among_us_game_is_registered_and_builds() -> None:
    env = make_game("amongcogs", num_agents=6, max_steps=120)
    assert env.game.num_agents == 6
    assert "crew_station" in env.game.objects
    assert "impostor_station" in env.game.objects
    assert "wiring_station" in env.game.objects
    assert "lights_station" in env.game.objects
    assert "emergency_button" in env.game.objects
    assert "sync_reactor_sabotage" in env.game.events
    assert "sync_oxygen_sabotage" in env.game.events
    assert "reactor_timer_tick" in env.game.events
    assert "impostor_kill_nearby_crew" in env.game.events
    assert "crew_report_corpse" in env.game.events
    assert "meeting_vote_target_0" in env.game.events
    assert "meeting_vote_target_0_intent" in env.game.events
    assert "meeting_teleport_agents" in env.game.events
    assert "force_assign_impostor_role" in env.game.events
    assert "force_assign_crew_roles" in env.game.events
    assert "impostor_win_parity_check" in env.game.events
    assert env.game.end_episode_on_game_stats == {"winner_declared": 1}


def test_lights_alert_reduces_crew_observation_radius() -> None:
    env = make_game("amongcogs", num_agents=3, max_steps=20)
    env.game.end_episode_on_game_stats = {}
    env.game.map_builder = AsciiMapBuilder.Config(
        map_data=[
            ["#", "#", "#", "#", "#", "#", "#", "#", "#"],
            ["#", "I", ".", ".", ".", ".", ".", ".", "#"],
            ["#", "C", ".", ".", ".", "B", ".", ".", "#"],
            ["#", "#", "#", "#", "#", "#", "#", "#", "#"],
        ],
        char_to_map_name={
            "#": "wall",
            ".": "empty",
            "I": "agent.agent",
            "C": "agent.agent",
            "B": "agent.agent",
        },
    )

    sim = Simulation(env, seed=13)
    try:
        sim.agent(0).set_inventory({ROLE_IMPOSTOR: 1, ALIVE_RESOURCE: 1})
        sim.agent(1).set_inventory({ROLE_CREW: 1, ALIVE_RESOURCE: 1})
        sim.agent(2).set_inventory({ROLE_CREW: 1, CORPSE_RESOURCE: 1})
        _step_with_actions(sim)

        assert "inv:corpse" in _observation_token_names(sim, agent_id=1)

        _step_with_actions(sim, {0: f"change_vibe_{VIBE_SABOTAGE_LIGHTS}"})

        assert sim.agent(1).inventory.get(LIGHTS_ALERT_RESOURCE, 0) == 1
        assert "inv:corpse" not in _observation_token_names(sim, agent_id=1)
    finally:
        sim.close()


def test_crew_win_task_goal_scales_with_lobby_size() -> None:
    assert crew_task_goal_for_lobby(5) == 16

    for num_agents in (5, 8, 12):
        env = make_game("amongcogs", num_agents=num_agents, max_steps=120)
        filters = env.game.events["crew_win_check"].filters
        matching = [
            f
            for f in filters
            if isinstance(f, GameValueFilter)
            and isinstance(f.value, StatValue)
            and f.value.scope == Scope.GAME
            and f.value.name == "crew_tasks_completed"
        ]
        assert len(matching) == 1
        expected_goal = crew_task_goal_for_lobby(num_agents)
        assert expected_goal >= CREW_TASK_GOAL_MIN
        assert matching[0].min == expected_goal


def test_impostor_station_assigns_role_once() -> None:
    sim = _make_single_station_sim("impostor_station", impostor_station_config())
    _move_east(sim)
    inv = sim.agent(0).inventory
    assert inv.get(ROLE_IMPOSTOR, 0) == 1
    sim.close()


def test_role_switch_is_blocked_after_first_pick() -> None:
    sim = _make_single_station_sim("impostor_station", impostor_station_config(), {ROLE_CREW: 1})
    _move_east(sim)
    inv = sim.agent(0).inventory
    assert inv.get(ROLE_CREW, 0) == 1
    assert inv.get(ROLE_IMPOSTOR, 0) == 0
    sim.close()


def test_crew_completes_task_and_drains_station() -> None:
    station_name = "wiring_station"
    sim = _make_single_station_sim(station_name, task_station_config(station_name), {ROLE_CREW: 1, TASK_RESOURCE: 0})
    assert _station_task_inventory(sim, station_name) == 3
    for expected_progress in range(1, TASK_PROGRESS_STEPS):
        _move_east(sim)
        assert sim.agent(0).inventory.get(TASK_RESOURCE, 0) == 0
        assert sim.agent(0).inventory.get(TASK_PROGRESS_RESOURCE, 0) == expected_progress
        assert _station_task_inventory(sim, station_name) == 3
    _move_east(sim)
    assert sim.agent(0).inventory.get(TASK_RESOURCE, 0) == 1
    assert sim.agent(0).inventory.get(TASK_PROGRESS_RESOURCE, 0) == 0
    assert _station_task_inventory(sim, station_name) == 2
    assert sim.episode_stats["game"].get("crew_tasks_completed", 0) == 1
    sim.close()


def test_impostor_triggers_critical_sabotage_without_gaining_task() -> None:
    station_name = "lights_station"
    sim = _make_single_station_sim(
        station_name,
        critical_station_config(
            station_name,
            system_tag="system:lights",
            timer_steps=16,
            sabotage_stat="lights_sabotages",
            repair_stat="lights_repairs",
        ),
        {ROLE_IMPOSTOR: 1, TASK_RESOURCE: 0},
    )
    _move_east(sim)
    assert sim.agent(0).inventory.get(TASK_RESOURCE, 0) == 0
    assert _station_tag_count(sim, STATION_SABOTAGED_TAG, (station_name,)) == 1
    assert any(
        int(obj.get(f"inv:{CRITICAL_TIMER_RESOURCE}", 0)) > 0
        for obj in sim.grid_objects(ignore_types=["wall", "agent"]).values()
        if obj.get("type_name") == station_name
    )
    assert sim.episode_stats["game"].get("impostor_sabotages", 0) == 1
    sim.close()


def test_impostor_can_travel_between_vents() -> None:
    env = make_game("amongcogs", num_agents=1, max_steps=40)
    env.game.end_episode_on_game_stats = {}
    env.game.map_builder = AsciiMapBuilder.Config(
        map_data=[
            ["#", "#", "#", "#", "#", "#", "#", "#", "#"],
            ["#", "@", "R", ".", ".", ".", ".", ".", "#"],
            ["#", "#", "#", "#", "#", "#", "S", "#", "#"],
            ["#", "#", "#", "#", "#", "#", "#", "#", "#"],
        ],
        char_to_map_name={
            "#": "wall",
            ".": "empty",
            "@": "agent.agent",
            "R": "reactor_vent",
            "S": "security_vent",
        },
    )

    sim = Simulation(env, seed=5)
    try:
        sim.agent(0).set_inventory({ROLE_IMPOSTOR: 1, ALIVE_RESOURCE: 1})
        sim.agent(0).set_action("move_east")
        sim.step()

        assert _agent_position(sim) == (1, 6)
        assert sim.episode_stats["game"].get("vents_used", 0) == 1
        sim.agent(0).set_action("move_south")
        sim.step()

        assert _agent_position(sim) == (1, 6)
        assert sim.episode_stats["game"].get("vents_used", 0) == 1
        assert sim.agent(0).inventory.get(VENT_COOLDOWN_RESOURCE, 0) > 0

        for _ in range(VENT_COOLDOWN_STEPS + 1):
            if sim.agent(0).inventory.get(VENT_COOLDOWN_RESOURCE, 0) == 0:
                break
            sim.agent(0).set_action("noop")
            sim.step()

        assert sim.agent(0).inventory.get(VENT_COOLDOWN_RESOURCE, 0) == 0
        sim.agent(0).set_action("move_south")
        sim.step()

        assert _agent_position(sim) == (1, 1)
        assert sim.episode_stats["game"].get("vents_used", 0) == 2
    finally:
        sim.close()


def test_crew_cannot_travel_between_vents() -> None:
    env = make_game("amongcogs", num_agents=1, max_steps=20)
    env.game.end_episode_on_game_stats = {}
    env.game.map_builder = AsciiMapBuilder.Config(
        map_data=[
            ["#", "#", "#", "#", "#", "#", "#", "#", "#"],
            ["#", "@", "R", ".", ".", ".", ".", ".", "#"],
            ["#", "#", "#", "#", "#", "#", "S", "#", "#"],
            ["#", "#", "#", "#", "#", "#", "#", "#", "#"],
        ],
        char_to_map_name={
            "#": "wall",
            ".": "empty",
            "@": "agent.agent",
            "R": "reactor_vent",
            "S": "security_vent",
        },
    )

    sim = Simulation(env, seed=5)
    try:
        sim.agent(0).set_inventory({ROLE_CREW: 1, ALIVE_RESOURCE: 1})
        sim.agent(0).set_action("move_east")
        sim.step()

        assert _agent_position(sim) == (1, 1)
        assert sim.episode_stats["game"].get("vents_used", 0) == 0
    finally:
        sim.close()


def test_vibe_sabotage_does_not_resolve_before_activation() -> None:
    env = make_game("amongcogs", num_agents=3, max_steps=30)
    env.game.end_episode_on_game_stats = {}
    env.game.map_builder = AsciiMapBuilder.Config(
        map_data=[
            ["#", "#", "#", "#", "#", "#", "#", "#"],
            ["#", "I", ".", "O", ".", "C", ".", "#"],
            ["#", ".", ".", "O", ".", "D", ".", "#"],
            ["#", "#", "#", "#", "#", "#", "#", "#"],
        ],
        char_to_map_name={
            "#": "wall",
            ".": "empty",
            "I": "agent.agent",
            "C": "agent.agent",
            "D": "agent.agent",
            "O": "oxygen_station",
        },
    )

    sim = Simulation(env, seed=7)
    try:
        sim.agent(0).set_inventory({ROLE_IMPOSTOR: 1, ALIVE_RESOURCE: 1})
        sim.agent(1).set_inventory({ROLE_CREW: 1, ALIVE_RESOURCE: 1})
        sim.agent(2).set_inventory({ROLE_CREW: 1, ALIVE_RESOURCE: 1})

        _step_with_actions(sim, {0: f"change_vibe_{VIBE_SABOTAGE_OXYGEN}"})

        assert _station_tag_count(sim, STATION_SABOTAGED_TAG, ("oxygen_station",)) == 2
        game_stats = sim.episode_stats["game"]
        assert game_stats.get("oxygen_sabotages", 0) == 1
        assert game_stats.get("oxygen_resolved", 0) == 0
        assert game_stats.get("impostor_win_oxygen", 0) == 0
    finally:
        sim.close()


def test_comms_sabotage_disables_security_until_repaired() -> None:
    env = make_game("amongcogs", num_agents=3, max_steps=30)
    env.game.end_episode_on_game_stats = {}
    env.game.map_builder = AsciiMapBuilder.Config(
        map_data=[
            ["#", "#", "#", "#", "#", "#", "#", "#", "#", "#"],
            ["#", "I", ".", "A", "S", ".", "B", "M", ".", "#"],
            ["#", ".", ".", ".", ".", ".", ".", ".", ".", "#"],
            ["#", "#", "#", "#", "#", "#", "#", "#", "#", "#"],
        ],
        char_to_map_name={
            "#": "wall",
            ".": "empty",
            "I": "agent.agent",
            "A": "agent.agent",
            "B": "agent.agent",
            "S": "security_station",
            "M": "comms_station",
        },
    )

    sim = Simulation(env, seed=6)
    try:
        sim.agent(0).set_inventory({ROLE_IMPOSTOR: 1, ALIVE_RESOURCE: 1})
        sim.agent(1).set_inventory({ROLE_CREW: 1, ALIVE_RESOURCE: 1})
        sim.agent(2).set_inventory({ROLE_CREW: 1, ALIVE_RESOURCE: 1})

        _step_with_actions(sim, {0: f"change_vibe_{VIBE_SABOTAGE_COMMS}"})
        _step_all_noop(sim, 2)
        assert _object_has_tag(sim, "security_station", STATION_ONLINE_TAG) is False

        _step_with_actions(sim, {0: "change_vibe_default"})
        _step_with_actions(sim, {1: "move_east"})
        assert sim.episode_stats["game"].get("camera_checks", 0) == 0

        _step_with_actions(sim, {2: "move_east"})
        _step_all_noop(sim, 1)

        assert sim.episode_stats["game"].get("comms_sabotages", 0) >= 1
        assert sim.episode_stats["game"].get("comms_repairs", 0) == 1
        assert _object_has_tag(sim, "security_station", STATION_ONLINE_TAG) is True

        _step_with_actions(sim, {1: "move_east"})
        assert sim.episode_stats["game"].get("camera_checks", 0) == 1
    finally:
        sim.close()


def test_crew_station_assigns_crew_role() -> None:
    sim = _make_single_station_sim("crew_station", crew_station_config())
    _move_east(sim)
    assert sim.agent(0).inventory.get(ROLE_CREW, 0) == 1
    sim.close()


def test_reactor_sabotage_syncs_across_both_panels_and_can_be_repaired() -> None:
    env = make_game("amongcogs", num_agents=3, max_steps=40)
    env.game.end_episode_on_game_stats = {}
    env.game.map_builder = AsciiMapBuilder.Config(
        map_data=[
            ["#", "#", "#", "#", "#", "#", "#", "#"],
            ["#", "I", ".", "R", "C", ".", ".", "#"],
            ["#", ".", ".", "R", "D", ".", ".", "#"],
            ["#", "#", "#", "#", "#", "#", "#", "#"],
        ],
        char_to_map_name={
            "#": "wall",
            ".": "empty",
            "I": "agent.agent",
            "C": "agent.agent",
            "D": "agent.agent",
            "R": "reactor_station",
        },
    )

    sim = Simulation(env, seed=42)
    sim.agent(0).set_inventory({ROLE_IMPOSTOR: 1, agent_id_resource(0): 1, ALIVE_RESOURCE: 1})
    sim.agent(1).set_inventory({ROLE_CREW: 1, agent_id_resource(1): 1, ALIVE_RESOURCE: 1})
    sim.agent(2).set_inventory({ROLE_CREW: 1, agent_id_resource(2): 1, ALIVE_RESOURCE: 1})

    _step_with_actions(sim, {0: "move_east"})
    _step_with_actions(sim, {0: "move_east"})
    _step_all_noop(sim, 1)
    assert _station_tag_count(sim, STATION_SABOTAGED_TAG, ("reactor_station",)) == 2

    _step_with_actions(sim, {1: "move_west", 2: "move_west"})
    _step_all_noop(sim, 1)
    after_repair = _station_tag_count(sim, STATION_SABOTAGED_TAG, ("reactor_station",))
    assert after_repair == 0
    game_stats = sim.episode_stats["game"]
    assert game_stats.get("reactor_sabotages", 0) > 0
    assert game_stats.get("reactor_repairs", 0) > 0
    sim.close()


def test_unrepaired_oxygen_sabotage_declares_impostor_win() -> None:
    env = make_game("amongcogs", num_agents=3, max_steps=40)
    env.game.map_builder = AsciiMapBuilder.Config(
        map_data=[
            ["#", "#", "#", "#", "#", "#", "#", "#"],
            ["#", "I", ".", "O", ".", "C", ".", "#"],
            ["#", ".", ".", "O", ".", "D", ".", "#"],
            ["#", "#", "#", "#", "#", "#", "#", "#"],
        ],
        char_to_map_name={
            "#": "wall",
            ".": "empty",
            "I": "agent.agent",
            "C": "agent.agent",
            "D": "agent.agent",
            "O": "oxygen_station",
        },
    )

    sim = Simulation(env, seed=7)
    sim.agent(0).set_inventory({ROLE_IMPOSTOR: 1, agent_id_resource(0): 1, ALIVE_RESOURCE: 1})
    sim.agent(1).set_inventory({ROLE_CREW: 1, agent_id_resource(1): 1, ALIVE_RESOURCE: 1})
    sim.agent(2).set_inventory({ROLE_CREW: 1, agent_id_resource(2): 1, ALIVE_RESOURCE: 1})

    _step_with_actions(sim, {0: "move_east"})
    _step_with_actions(sim, {0: "move_east"})
    _step_all_noop(sim, 12)

    game_stats = sim.episode_stats["game"]
    assert game_stats.get("impostor_win", 0) > 0
    assert game_stats.get("impostor_win_oxygen", 0) > 0
    assert game_stats.get("winner_declared", 0) > 0
    assert sim.agent(0).inventory.get(WIN_REWARD_RESOURCE, 0) == 1
    assert sim.agent(1).inventory.get(WIN_REWARD_RESOURCE, 0) == 0
    assert sim.agent(2).inventory.get(WIN_REWARD_RESOURCE, 0) == 0
    sim.close()


def test_social_deduction_event_loop_kill_report_vote() -> None:
    env = make_game("amongcogs", num_agents=3, max_steps=80)
    env.game.end_episode_on_game_stats = {}
    env.game.map_builder = AsciiMapBuilder.Config(
        map_data=[
            ["#", "#", "#", "#", "#", "#", "#"],
            ["#", ".", ".", ".", ".", ".", "#"],
            ["#", "I", "V", "R", ".", ".", "#"],
            ["#", ".", ".", ".", ".", ".", "#"],
            ["#", "#", "#", "#", "#", "#", "#"],
        ],
        char_to_map_name={
            "#": "wall",
            ".": "empty",
            "I": "agent.agent",
            "V": "agent.agent",
            "R": "agent.agent",
        },
    )

    sim = Simulation(env, seed=9)
    sim.agent(0).set_inventory({ROLE_IMPOSTOR: 1, agent_id_resource(0): 1, ALIVE_RESOURCE: 1})
    sim.agent(1).set_inventory({ROLE_CREW: 1, agent_id_resource(1): 1, ALIVE_RESOURCE: 1})
    sim.agent(2).set_inventory({ROLE_CREW: 1, agent_id_resource(2): 1, ALIVE_RESOURCE: 1})

    _step_with_actions(sim, {0: f"change_vibe_{VIBE_KILL}"})
    _step_with_actions(sim, {2: f"change_vibe_{VIBE_REPORT}"})  # prepare report intent
    _step_with_actions(sim, {2: f"change_vibe_{vote_target_vibe(0)}"})  # prepare vote intent
    _step_all_noop(sim, 8)  # allow vote + resolution events to run
    game_stats = sim.episode_stats["game"]

    assert game_stats.get("impostor_kills", 0) > 0
    assert game_stats.get("reports", 0) > 0
    assert game_stats.get("votes_impostor", 0) > 0
    assert game_stats.get("meeting_votes", 0) > 0
    assert game_stats.get("ejections", 0) > 0

    ejected = sum(int(sim.agent(i).inventory.get(EJECTED_RESOURCE, 0)) for i in range(sim.num_agents))
    assert ejected > 0
    sim.close()


def test_impostor_kill_requires_explicit_intent() -> None:
    env = make_game("amongcogs", num_agents=2, max_steps=20)
    env.game.end_episode_on_game_stats = {}
    env.game.map_builder = AsciiMapBuilder.Config(
        map_data=[
            ["#", "#", "#", "#", "#"],
            ["#", "I", "C", ".", "#"],
            ["#", "#", "#", "#", "#"],
        ],
        char_to_map_name={
            "#": "wall",
            ".": "empty",
            "I": "agent.agent",
            "C": "agent.agent",
        },
    )

    sim = Simulation(env, seed=11)
    try:
        sim.agent(0).set_inventory({ROLE_IMPOSTOR: 1, ALIVE_RESOURCE: 1})
        sim.agent(1).set_inventory({ROLE_CREW: 1, ALIVE_RESOURCE: 1})

        _step_with_actions(sim)
        assert sim.agent(1).inventory.get(CORPSE_RESOURCE, 0) == 0
        assert sim.episode_stats["game"].get("impostor_kills", 0) == 0

        _step_with_actions(sim, {0: f"change_vibe_{VIBE_KILL}"})
        assert sim.agent(1).inventory.get(CORPSE_RESOURCE, 0) == 1
        assert sim.episode_stats["game"].get("impostor_kills", 0) == 1
    finally:
        sim.close()


def test_body_report_meeting_sets_shared_report_context() -> None:
    env = make_game("amongcogs", num_agents=3, max_steps=40)
    env.game.end_episode_on_game_stats = {}
    env.game.map_builder = AsciiMapBuilder.Config(
        map_data=[
            ["#", "#", "#", "#", "#", "#", "#"],
            ["#", ".", ".", ".", ".", ".", "#"],
            ["#", "I", "V", "R", ".", ".", "#"],
            ["#", ".", ".", ".", ".", ".", "#"],
            ["#", "#", "#", "#", "#", "#", "#"],
        ],
        char_to_map_name={
            "#": "wall",
            ".": "empty",
            "I": "agent.agent",
            "V": "agent.agent",
            "R": "agent.agent",
        },
    )

    sim = Simulation(env, seed=9)
    try:
        sim.agent(0).set_inventory({ROLE_IMPOSTOR: 1, ALIVE_RESOURCE: 1})
        sim.agent(1).set_inventory({ROLE_CREW: 1, ALIVE_RESOURCE: 1})
        sim.agent(2).set_inventory({ROLE_CREW: 1, ALIVE_RESOURCE: 1})

        _step_with_actions(sim, {0: f"change_vibe_{VIBE_KILL}"})
        _step_with_actions(sim, {2: f"change_vibe_{VIBE_REPORT}"})
        _step_with_actions(sim)

        assert sim.agent(0).inventory.get(MEETING_ACTIVE_RESOURCE, 0) == 1
        assert sim.agent(2).inventory.get(MEETING_ACTIVE_RESOURCE, 0) == 1
        assert sim.agent(0).inventory.get(MEETING_REPORTED_BODY_RESOURCE, 0) == 1
        assert sim.agent(2).inventory.get(MEETING_REPORTED_BODY_RESOURCE, 0) == 1
    finally:
        sim.close()


def test_meeting_targeted_vote_ejects_named_impostor() -> None:
    env = make_game("amongcogs", num_agents=3, max_steps=20)
    env.game.end_episode_on_game_stats = {}

    sim = Simulation(env, seed=3)
    try:
        sim.agent(0).set_inventory(
            {
                ROLE_IMPOSTOR: 1,
                agent_id_resource(0): 1,
                ALIVE_RESOURCE: 1,
                MEETING_ACTIVE_RESOURCE: 1,
                VOTED_RESOURCE: 1,
                VOTE_SKIP_RESOURCE: 1,
            }
        )
        for agent_id in (1, 2):
            sim.agent(agent_id).set_inventory(
                {
                    ROLE_CREW: 1,
                    agent_id_resource(agent_id): 1,
                    ALIVE_RESOURCE: 1,
                    MEETING_ACTIVE_RESOURCE: 1,
                    VOTED_RESOURCE: 1,
                    VOTE_IMPOSTOR_RESOURCE: 1,
                    vote_target_resource(0): 1,
                }
            )

        _step_with_actions(sim)

        assert sim.agent(0).inventory.get(EJECTED_RESOURCE, 0) == 1
        assert sim.agent(0).inventory.get(ALIVE_RESOURCE, 0) == 0
        assert sim.agent(1).inventory.get(EJECTED_RESOURCE, 0) == 0
        assert sim.agent(1).inventory.get(ALIVE_RESOURCE, 0) == 1
        assert sim.agent(2).inventory.get(EJECTED_RESOURCE, 0) == 0
        assert sim.agent(2).inventory.get(ALIVE_RESOURCE, 0) == 1
    finally:
        sim.close()


def test_meeting_targeted_vote_can_eject_named_crewmate() -> None:
    env = make_game("amongcogs", num_agents=3, max_steps=20)
    env.game.end_episode_on_game_stats = {}

    sim = Simulation(env, seed=12)
    try:
        sim.agent(0).set_inventory(
            {
                ROLE_IMPOSTOR: 1,
                agent_id_resource(0): 1,
                ALIVE_RESOURCE: 1,
                MEETING_ACTIVE_RESOURCE: 1,
                VOTED_RESOURCE: 1,
                VOTE_SKIP_RESOURCE: 1,
            }
        )
        for agent_id in (1, 2):
            sim.agent(agent_id).set_inventory(
                {
                    ROLE_CREW: 1,
                    agent_id_resource(agent_id): 1,
                    ALIVE_RESOURCE: 1,
                    MEETING_ACTIVE_RESOURCE: 1,
                    VOTED_RESOURCE: 1,
                    VOTE_IMPOSTOR_RESOURCE: 1,
                    vote_target_resource(1): 1,
                }
            )

        _step_with_actions(sim)

        assert sim.agent(0).inventory.get(EJECTED_RESOURCE, 0) == 0
        assert sim.agent(0).inventory.get(ALIVE_RESOURCE, 0) == 1
        assert sim.agent(1).inventory.get(EJECTED_RESOURCE, 0) == 1
        assert sim.agent(1).inventory.get(ALIVE_RESOURCE, 0) == 0
        assert sim.agent(2).inventory.get(EJECTED_RESOURCE, 0) == 0
        assert sim.agent(2).inventory.get(ALIVE_RESOURCE, 0) == 1
    finally:
        sim.close()


def test_generic_accuse_without_named_target_does_not_eject() -> None:
    env = make_game("amongcogs", num_agents=3, max_steps=20)
    env.game.end_episode_on_game_stats = {}

    sim = Simulation(env, seed=14)
    try:
        for agent_id in range(sim.num_agents):
            role = ROLE_IMPOSTOR if agent_id == 0 else ROLE_CREW
            sim.agent(agent_id).set_inventory(
                {
                    role: 1,
                    agent_id_resource(agent_id): 1,
                    ALIVE_RESOURCE: 1,
                    MEETING_ACTIVE_RESOURCE: 1,
                    VOTED_RESOURCE: 1,
                    VOTE_IMPOSTOR_RESOURCE: 1,
                }
            )

        _step_with_actions(sim)

        assert all(sim.agent(agent_id).inventory.get(EJECTED_RESOURCE, 0) == 0 for agent_id in range(sim.num_agents))
        assert sim.episode_stats["game"].get("meeting_ties", 0) == 1
    finally:
        sim.close()


def test_meeting_vote_tie_resolves_without_ejection() -> None:
    env = make_game("amongcogs", num_agents=2, max_steps=20)
    env.game.end_episode_on_game_stats = {}

    sim = Simulation(env, seed=4)
    try:
        sim.agent(0).set_inventory(
            {
                ROLE_IMPOSTOR: 1,
                agent_id_resource(0): 1,
                ALIVE_RESOURCE: 1,
                MEETING_ACTIVE_RESOURCE: 1,
                VOTED_RESOURCE: 1,
                VOTE_SKIP_RESOURCE: 1,
            }
        )
        sim.agent(1).set_inventory(
            {
                ROLE_CREW: 1,
                agent_id_resource(1): 1,
                ALIVE_RESOURCE: 1,
                MEETING_ACTIVE_RESOURCE: 1,
                VOTED_RESOURCE: 1,
                VOTE_IMPOSTOR_RESOURCE: 1,
                vote_target_resource(0): 1,
            }
        )

        _step_with_actions(sim)

        assert sim.agent(0).inventory.get(EJECTED_RESOURCE, 0) == 0
        assert sim.agent(1).inventory.get(EJECTED_RESOURCE, 0) == 0
        assert sim.agent(0).inventory.get(MEETING_ACTIVE_RESOURCE, 0) == 0
        assert sim.agent(1).inventory.get(MEETING_ACTIVE_RESOURCE, 0) == 0
        assert sim.episode_stats["game"].get("meeting_ties", 0) == 1
    finally:
        sim.close()


def test_meeting_discussion_opens_ballot_before_resolution() -> None:
    env = make_game("amongcogs", num_agents=2, max_steps=20)
    env.game.end_episode_on_game_stats = {}

    sim = Simulation(env, seed=5)
    try:
        for agent_id in range(2):
            sim.agent(agent_id).set_inventory(
                {
                    ROLE_CREW: 1,
                    ALIVE_RESOURCE: 1,
                    MEETING_ACTIVE_RESOURCE: 1,
                    MEETING_DISCUSSION_RESOURCE: 1,
                    MEETING_DISCUSSION_TIMER_RESOURCE: 1,
                    MEETING_TIMER_RESOURCE: 3,
                }
            )

        _step_with_actions(sim)

        assert sim.agent(0).inventory.get(MEETING_DISCUSSION_RESOURCE, 0) == 0
        assert sim.agent(0).inventory.get(MEETING_BALLOT_RESOURCE, 0) == 1
        assert sim.agent(0).inventory.get(MEETING_TIMER_RESOURCE, 0) == 2
        assert sim.agent(1).inventory.get(MEETING_BALLOT_RESOURCE, 0) == 1
    finally:
        sim.close()


def test_active_meeting_gathers_alive_agents_near_button() -> None:
    env = make_game("amongcogs", num_agents=8, max_steps=20)
    env.game.end_episode_on_game_stats = {}

    sim = Simulation(env, seed=0)
    try:
        pre_positions = {agent_id: _agent_position(sim, agent_id) for agent_id in range(sim.num_agents)}
        button_pos = next(
            (int(obj["r"]), int(obj["c"]))
            for obj in sim.grid_objects(ignore_types=["wall", "agent"]).values()
            if obj.get("type_name") == "emergency_button"
        )
        for agent_id in range(sim.num_agents):
            sim.agent(agent_id).set_inventory(
                {
                    ROLE_CREW: 1,
                    ALIVE_RESOURCE: 1,
                    MEETING_ACTIVE_RESOURCE: 1,
                    MEETING_DISCUSSION_RESOURCE: 1,
                    MEETING_DISCUSSION_TIMER_RESOURCE: 1,
                    MEETING_TIMER_RESOURCE: 3,
                }
            )

        _step_with_actions(sim)

        post_positions = {agent_id: _agent_position(sim, agent_id) for agent_id in range(sim.num_agents)}
        assert any(post_positions[agent_id] != pre_positions[agent_id] for agent_id in range(sim.num_agents))
        assert any(abs(pos[0] - button_pos[0]) + abs(pos[1] - button_pos[1]) <= 1 for pos in post_positions.values())
    finally:
        sim.close()


def test_discussion_turn_can_set_vote_via_dual_action() -> None:
    env = make_game("amongcogs", num_agents=2, max_steps=20)
    env.game.end_episode_on_game_stats = {}

    sim = Simulation(env, seed=5)
    try:
        sim.agent(0).set_inventory(
            {
                ROLE_IMPOSTOR: 1,
                agent_id_resource(0): 1,
                ALIVE_RESOURCE: 1,
                MEETING_ACTIVE_RESOURCE: 1,
                MEETING_DISCUSSION_RESOURCE: 1,
                MEETING_DISCUSSION_TIMER_RESOURCE: 1,
                MEETING_TIMER_RESOURCE: 3,
            }
        )
        sim.agent(1).set_inventory(
            {
                ROLE_CREW: 1,
                agent_id_resource(1): 1,
                ALIVE_RESOURCE: 1,
                MEETING_ACTIVE_RESOURCE: 1,
                MEETING_DISCUSSION_RESOURCE: 1,
                MEETING_DISCUSSION_TIMER_RESOURCE: 1,
                MEETING_TIMER_RESOURCE: 3,
            }
        )

        sim.agent(0).set_action("noop")
        sim.agent(1).set_action(Action(name="noop", vibe=f"change_vibe_{vote_target_vibe(0)}"))
        sim.step()
        assert sim.agent(1).inventory.get(MEETING_BALLOT_RESOURCE, 0) == 1
        sim.agent(0).set_action("noop")
        sim.agent(1).set_action("noop")
        sim.step()

        assert sim.agent(1).inventory.get(VOTED_RESOURCE, 0) == 1
        assert sim.agent(1).inventory.get(VOTE_IMPOSTOR_RESOURCE, 0) == 1
        assert sim.episode_stats["game"].get("votes_impostor", 0) == 1
    finally:
        sim.close()
