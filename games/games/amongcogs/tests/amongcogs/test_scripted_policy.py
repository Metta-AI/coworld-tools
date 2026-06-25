from __future__ import annotations

from amongcogs.agent.amongcogs_agent.obs_parser import AmongUsState, VisibleEntity
from amongcogs.agent.amongcogs_agent.policy import AmongThemNotTooDumbAgent, AmongThemNotTooDumbPolicy, AmongUsAgent, AmongUsPolicy
from amongcogs.game import CORPSE_RESOURCE, VIBE_CALL_MEETING, VIBE_KILL, VIBE_REPORT, vote_target_vibe
from amongcogs.runtime import make_game
from mettagrid.policy.policy_env_interface import PolicyEnvInterface
from mettagrid.simulator import Simulation


def _agent_position(sim: Simulation, agent_id: int) -> tuple[int, int]:
    for obj in sim.grid_objects(ignore_types=["wall"]).values():
        if obj.get("type_name") == "agent" and int(obj.get("agent_id", -1)) == agent_id:
            return int(obj["r"]), int(obj["c"])
    raise AssertionError(f"Agent {agent_id} not found")


def test_scripted_policy_tracks_local_position_from_spawn() -> None:
    env = make_game("amongcogs", num_agents=8, max_steps=20)
    policy = AmongUsPolicy(PolicyEnvInterface.from_mg_cfg(env))
    sim = Simulation(env, seed=0)
    agent = policy.agent_policy(0)
    agent.reset(simulation=sim)

    assert agent._position == _agent_position(sim, 0)

    for _ in range(2):
        agent.step(sim.agent(0).observation)
        for other_agent_id in range(1, sim.num_agents):
            sim.agent(other_agent_id).set_action("noop")
        sim.agent(0).set_action("move_west")
        sim.step()
        agent.step(sim.agent(0).observation)
        assert agent._position == _agent_position(sim, 0)

    sim.close()


def test_scripted_policy_ignores_distant_corpse_during_lights_sabotage() -> None:
    env = make_game("amongcogs", num_agents=8, max_steps=20)
    sim = Simulation(env, seed=0)
    try:
        spawn_pos = _agent_position(sim, 0)
        crew_agent = AmongUsAgent(
            PolicyEnvInterface.from_mg_cfg(env),
            agent_id=0,
            desired_role="crew",
            static_known={
                spawn_pos: VisibleEntity(type_name="empty"),
                (spawn_pos[0] - 1, spawn_pos[1]): VisibleEntity(type_name="empty"),
                (spawn_pos[0], spawn_pos[1] + 1): VisibleEntity(type_name="empty"),
            },
            spawn_pos=spawn_pos,
        )
        crew_agent.reset(simulation=sim)

        crew_agent._known[(spawn_pos[0], spawn_pos[1] + 4)] = VisibleEntity(
            type_name="agent",
            inventory={CORPSE_RESOURCE: 1},
            last_seen=0,
        )

        action_without_lights = crew_agent._select_action(  # pyright: ignore[reportPrivateUsage]
            AmongUsState(position=spawn_pos, crew=1, alive=1)
        )
        assert action_without_lights.name == "move_east"

        action_with_lights = crew_agent._select_action(  # pyright: ignore[reportPrivateUsage]
            AmongUsState(position=spawn_pos, crew=1, alive=1, lights_alert=1)
        )
        assert action_with_lights.name != "move_east"
    finally:
        sim.close()


def test_scripted_policy_reports_nearest_room_evidence_for_body() -> None:
    env = make_game("amongcogs", num_agents=8, max_steps=20)
    sim = Simulation(env, seed=0)
    try:
        spawn_pos = _agent_position(sim, 0)
        station_pos = (spawn_pos[0], spawn_pos[1] + 1)
        corpse_pos = (spawn_pos[0], spawn_pos[1] + 2)
        crew_agent = AmongUsAgent(
            PolicyEnvInterface.from_mg_cfg(env),
            agent_id=0,
            desired_role="crew",
            static_known={
                spawn_pos: VisibleEntity(type_name="empty"),
                station_pos: VisibleEntity(type_name="wiring_station"),
                corpse_pos: VisibleEntity(type_name="empty"),
            },
            spawn_pos=spawn_pos,
        )
        crew_agent.reset(simulation=sim)
        crew_agent._known[corpse_pos] = VisibleEntity(  # pyright: ignore[reportPrivateUsage]
            type_name="agent",
            agent_id=4,
            inventory={CORPSE_RESOURCE: 1},
            last_seen=0,
        )

        action = crew_agent._select_action(AmongUsState(position=spawn_pos, crew=1, alive=1))  # pyright: ignore[reportPrivateUsage]

        assert action.name == f"change_vibe_{VIBE_REPORT}"
        assert action.talk == "body in Electrical. no named suspect."
    finally:
        sim.close()


def test_scripted_policy_nearest_target_is_stable_across_known_insertion_order() -> None:
    env = make_game("amongcogs", num_agents=8, max_steps=20)
    sim = Simulation(env, seed=0)
    try:
        spawn_pos = _agent_position(sim, 0)
        west_pos = (spawn_pos[0], spawn_pos[1] - 1)
        east_pos = (spawn_pos[0], spawn_pos[1] + 1)

        class SequenceRng:
            def __init__(self) -> None:
                self._values = iter((10, 0))

            def randint(self, _start: int, _end: int) -> int:
                return next(self._values)

        def _make_agent(known_positions: list[tuple[int, int]]) -> AmongUsAgent:
            agent = AmongUsAgent(
                PolicyEnvInterface.from_mg_cfg(env),
                agent_id=0,
                desired_role="crew",
                static_known={
                    pos: VisibleEntity(
                        type_name="task_station" if pos != spawn_pos else "empty",
                        tags={"station:online"} if pos != spawn_pos else set(),
                        inventory={"task": 1} if pos != spawn_pos else {},
                    )
                    for pos in known_positions
                },
                spawn_pos=spawn_pos,
            )
            agent.reset(simulation=sim)
            agent._rng = SequenceRng()  # pyright: ignore[reportPrivateUsage]
            return agent

        left_first = _make_agent([spawn_pos, west_pos, east_pos])
        right_first = _make_agent([spawn_pos, east_pos, west_pos])

        left_target = left_first._nearest(lambda entity: entity.type_name == "task_station")  # pyright: ignore[reportPrivateUsage]
        right_target = right_first._nearest(lambda entity: entity.type_name == "task_station")  # pyright: ignore[reportPrivateUsage]

        assert left_target is not None
        assert right_target is not None
        assert left_target[0] == right_target[0]
    finally:
        sim.close()


def test_scripted_policy_only_casts_named_vote_after_target_evidence() -> None:
    env = make_game("amongcogs", num_agents=8, max_steps=20)
    sim = Simulation(env, seed=0)
    try:
        spawn_pos = _agent_position(sim, 0)
        crew_agent = AmongUsAgent(
            PolicyEnvInterface.from_mg_cfg(env),
            agent_id=0,
            desired_role="crew",
            static_known={spawn_pos: VisibleEntity(type_name="empty")},
            spawn_pos=spawn_pos,
        )
        crew_agent.reset(simulation=sim)
        crew_agent._meeting_turn = 2  # pyright: ignore[reportPrivateUsage]
        crew_agent._rng = type(  # pyright: ignore[reportPrivateUsage]
            "FixedRng",
            (),
            {
                "random": lambda self: 0.4,
                "randint": lambda self, _start, _end: 0,
            },
        )()

        skip_action = crew_agent._select_action(  # pyright: ignore[reportPrivateUsage]
            AmongUsState(position=spawn_pos, crew=1, alive=1, meeting_active=1, meeting_ballot=1, meeting_timer=1)
        )
        assert skip_action.name == "change_vibe_asterisk"
        assert skip_action.talk == "skipping for now."

        crew_agent._direct_corpse_seen_steps = 3  # pyright: ignore[reportPrivateUsage]
        accuse_action = crew_agent._select_action(  # pyright: ignore[reportPrivateUsage]
            AmongUsState(position=spawn_pos, crew=1, alive=1, meeting_active=1, meeting_ballot=1, meeting_timer=1)
        )
        assert accuse_action.name == "change_vibe_asterisk"
        assert accuse_action.talk == "skipping for now."

        crew_agent._direct_body_suspect_id = 3  # pyright: ignore[reportPrivateUsage]
        accuse_action = crew_agent._select_action(  # pyright: ignore[reportPrivateUsage]
            AmongUsState(position=spawn_pos, crew=1, alive=1, meeting_active=1, meeting_ballot=1, meeting_timer=1)
        )
        assert accuse_action.name == f"change_vibe_{vote_target_vibe(3)}"
        assert accuse_action.talk == "voting Agent 3."
    finally:
        sim.close()


def test_scripted_policy_impostor_hunts_visible_crew_before_sabotage() -> None:
    env = make_game("amongcogs", num_agents=8, max_steps=20)
    sim = Simulation(env, seed=0)
    try:
        spawn_pos = _agent_position(sim, 0)
        impostor_agent = AmongUsAgent(
            PolicyEnvInterface.from_mg_cfg(env),
            agent_id=0,
            desired_role="impostor",
            static_known={
                spawn_pos: VisibleEntity(type_name="empty"),
                (spawn_pos[0], spawn_pos[1] + 1): VisibleEntity(
                    type_name="agent",
                    inventory={"crew": 1, "alive": 1},
                    agent_id=3,
                    last_seen=1,
                ),
            },
            spawn_pos=spawn_pos,
        )
        impostor_agent.reset(simulation=sim)
        impostor_agent._step = 12  # pyright: ignore[reportPrivateUsage]

        action = impostor_agent._select_action(  # pyright: ignore[reportPrivateUsage]
            AmongUsState(position=spawn_pos, impostor=1, alive=1, kill_cooldown=0, sabotage_cooldown=0)
        )

        assert action.name == f"change_vibe_{VIBE_KILL}"
    finally:
        sim.close()


def test_scripted_policy_crew_button_fallback_when_no_task_goal() -> None:
    env = make_game("amongcogs", num_agents=8, max_steps=20)
    sim = Simulation(env, seed=0)
    try:
        spawn_pos = _agent_position(sim, 0)
        crew_agent = AmongUsAgent(
            PolicyEnvInterface.from_mg_cfg(env),
            agent_id=0,
            desired_role="crew",
            static_known={spawn_pos: VisibleEntity(type_name="emergency_button")},
            spawn_pos=spawn_pos,
        )
        crew_agent.reset(simulation=sim)

        action = crew_agent._select_action(  # pyright: ignore[reportPrivateUsage]
            AmongUsState(position=spawn_pos, crew=1, alive=1, meeting_token=1)
        )

        assert action.name == f"change_vibe_{VIBE_CALL_MEETING}"
    finally:
        sim.close()


def test_scripted_policy_discusses_before_casting_vote() -> None:
    env = make_game("amongcogs", num_agents=8, max_steps=20)
    sim = Simulation(env, seed=0)
    try:
        spawn_pos = _agent_position(sim, 0)
        crew_agent = AmongUsAgent(
            PolicyEnvInterface.from_mg_cfg(env),
            agent_id=0,
            desired_role="crew",
            static_known={spawn_pos: VisibleEntity(type_name="emergency_button")},
            spawn_pos=spawn_pos,
        )
        crew_agent.reset(simulation=sim)
        crew_agent._direct_corpse_seen_steps = 3  # pyright: ignore[reportPrivateUsage]
        crew_agent._direct_body_suspect_id = 3  # pyright: ignore[reportPrivateUsage]
        crew_agent._meeting_turn = 2  # pyright: ignore[reportPrivateUsage]
        crew_agent._rng = type(  # pyright: ignore[reportPrivateUsage]
            "FixedRng",
            (),
            {
                "random": lambda self: 0.4,
                "randint": lambda self, _start, _end: 0,
            },
        )()

        action = crew_agent._select_action(  # pyright: ignore[reportPrivateUsage]
            AmongUsState(position=spawn_pos, crew=1, alive=1, meeting_active=1, meeting_discussion=1, meeting_timer=3)
        )
        assert action.name == "noop"
        assert action.vibe is None
        assert action.talk == "I found the body near Agent 3. vote Agent 3."
    finally:
        sim.close()


def test_scripted_policy_deduplicates_named_suspect_hearsay() -> None:
    env = make_game("amongcogs", num_agents=8, max_steps=20)
    sim = Simulation(env, seed=0)
    try:
        spawn_pos = _agent_position(sim, 0)
        crew_agent = AmongUsAgent(
            PolicyEnvInterface.from_mg_cfg(env),
            agent_id=0,
            desired_role="crew",
            static_known={spawn_pos: VisibleEntity(type_name="empty")},
            spawn_pos=spawn_pos,
        )
        crew_agent.reset(simulation=sim)
        crew_agent._meeting_turn = 2  # pyright: ignore[reportPrivateUsage]
        crew_agent._rng = type(  # pyright: ignore[reportPrivateUsage]
            "FixedRng",
            (),
            {
                "random": lambda self: 0.45,
                "randint": lambda self, _start, _end: 0,
            },
        )()

        crew_agent._remember_meeting_utterance(1, "body found near Agent 3.")  # pyright: ignore[reportPrivateUsage]
        crew_agent._remember_meeting_utterance(1, "body   found   near   Agent   3.")  # pyright: ignore[reportPrivateUsage]
        crew_agent._remember_meeting_utterance(2, "skip unless we have proof.")  # pyright: ignore[reportPrivateUsage]

        assert crew_agent._meeting_body_claims == 1  # pyright: ignore[reportPrivateUsage]
        assert crew_agent._meeting_skip_claims == 1  # pyright: ignore[reportPrivateUsage]
        assert crew_agent._meeting_suspect_counts == {3: 1}  # pyright: ignore[reportPrivateUsage]
        assert crew_agent._crew_meeting_vote_target() == 3  # pyright: ignore[reportPrivateUsage]

        crew_agent._direct_corpse_seen_steps = 3  # pyright: ignore[reportPrivateUsage]
        crew_agent._direct_body_suspect_id = 4  # pyright: ignore[reportPrivateUsage]
        assert crew_agent._crew_meeting_vote_target() == 4  # pyright: ignore[reportPrivateUsage]
    finally:
        sim.close()


def test_scripted_policy_does_not_vote_from_report_context_without_named_suspect() -> None:
    env = make_game("amongcogs", num_agents=8, max_steps=20)
    sim = Simulation(env, seed=0)
    try:
        spawn_pos = _agent_position(sim, 0)
        crew_agent = AmongUsAgent(
            PolicyEnvInterface.from_mg_cfg(env),
            agent_id=0,
            desired_role="crew",
            static_known={spawn_pos: VisibleEntity(type_name="empty")},
            spawn_pos=spawn_pos,
        )
        crew_agent.reset(simulation=sim)
        crew_agent._meeting_turn = 2  # pyright: ignore[reportPrivateUsage]
        crew_agent._rng = type(  # pyright: ignore[reportPrivateUsage]
            "FixedRng",
            (),
            {
                "random": lambda self: 0.55,
                "randint": lambda self, _start, _end: 0,
            },
        )()

        assert crew_agent._crew_meeting_vote_target() is None  # pyright: ignore[reportPrivateUsage]

        crew_agent._meeting_reported_body = True  # pyright: ignore[reportPrivateUsage]
        assert crew_agent._crew_meeting_vote_target() is None  # pyright: ignore[reportPrivateUsage]
    finally:
        sim.close()


def test_scripted_policy_escalates_report_meetings_on_late_discussion_turns() -> None:
    env = make_game("amongcogs", num_agents=8, max_steps=20)
    sim = Simulation(env, seed=0)
    try:
        spawn_pos = _agent_position(sim, 0)
        crew_agent = AmongUsAgent(
            PolicyEnvInterface.from_mg_cfg(env),
            agent_id=0,
            desired_role="crew",
            static_known={spawn_pos: VisibleEntity(type_name="emergency_button")},
            spawn_pos=spawn_pos,
        )
        crew_agent.reset(simulation=sim)
        crew_agent._meeting_turn = 2  # pyright: ignore[reportPrivateUsage]
        crew_agent._meeting_reported_body = True  # pyright: ignore[reportPrivateUsage]
        crew_agent._rng = type(  # pyright: ignore[reportPrivateUsage]
            "FixedRng",
            (),
            {
                "random": lambda self: 0.5,
                "randint": lambda self, _start, _end: 0,
            },
        )()

        action = crew_agent._select_action(  # pyright: ignore[reportPrivateUsage]
            AmongUsState(
                position=spawn_pos,
                crew=1,
                alive=1,
                meeting_active=1,
                meeting_discussion=1,
                meeting_reported_body=1,
                meeting_timer=2,
            )
        )
        assert action.vibe is None
        assert action.talk == "body was reported. no named suspect."
    finally:
        sim.close()


def test_scripted_policy_cycles_sabotage_vibes() -> None:
    env = make_game("amongcogs", num_agents=8, max_steps=20)
    policy = AmongUsPolicy(PolicyEnvInterface.from_mg_cfg(env))
    sim = Simulation(env, seed=0)
    try:
        agent = policy.agent_policy(0)
        agent.reset(simulation=sim)
        vibes = [agent._sabotage_vibe() for _ in range(5)]  # pyright: ignore[reportPrivateUsage]
        assert vibes == ["lightning", "wave", "water", "fire", "lightning"]
    finally:
        sim.close()


def test_amongthem_nottoodumb_policy_uses_dedicated_agent_class() -> None:
    env = make_game("amongcogs", num_agents=5, max_steps=20)
    policy = AmongThemNotTooDumbPolicy(PolicyEnvInterface.from_mg_cfg(env))
    sim = Simulation(env, seed=0)
    try:
        agent = policy.agent_policy(0)
        agent.reset(simulation=sim)
        assert isinstance(agent, AmongThemNotTooDumbAgent)
    finally:
        sim.close()


def test_amongthem_nottoodumb_task_goal_persists_until_exhausted() -> None:
    env = make_game("amongcogs", num_agents=5, max_steps=20)
    sim = Simulation(env, seed=0)
    try:
        spawn_pos = _agent_position(sim, 0)
        task_pos = (spawn_pos[0], spawn_pos[1] + 1)
        agent = AmongThemNotTooDumbAgent(
            PolicyEnvInterface.from_mg_cfg(env),
            agent_id=0,
            desired_role="crew",
            static_known={
                spawn_pos: VisibleEntity(type_name="empty"),
                task_pos: VisibleEntity(
                    type_name="wiring_station",
                    tags={"station:online"},
                    inventory={"task": 1},
                ),
                (spawn_pos[0], spawn_pos[1] + 4): VisibleEntity(
                    type_name="admin_station",
                    tags={"station:online"},
                    inventory={"task": 1},
                ),
            },
            spawn_pos=spawn_pos,
        )
        agent.reset(simulation=sim)

        action = agent._select_action(AmongUsState(position=spawn_pos, crew=1, alive=1))  # pyright: ignore[reportPrivateUsage]
        assert action.name == "move_east"
        assert agent._task_goal_station_name == "wiring_station"  # pyright: ignore[reportPrivateUsage]

        agent._task_hold_steps = 0  # pyright: ignore[reportPrivateUsage]
        agent._known[task_pos].inventory["task"] = 0  # pyright: ignore[reportPrivateUsage]
        action = agent._select_action(AmongUsState(position=spawn_pos, crew=1, alive=1))  # pyright: ignore[reportPrivateUsage]
        assert action.name == "move_east"
        assert agent._task_goal_station_name == "admin_station"  # pyright: ignore[reportPrivateUsage]
    finally:
        sim.close()


def test_amongthem_nottoodumb_button_fallback_precedes_info_patrol() -> None:
    env = make_game("amongcogs", num_agents=5, max_steps=20)
    sim = Simulation(env, seed=0)
    try:
        spawn_pos = _agent_position(sim, 0)
        agent = AmongThemNotTooDumbAgent(
            PolicyEnvInterface.from_mg_cfg(env),
            agent_id=0,
            desired_role="crew",
            static_known={
                spawn_pos: VisibleEntity(type_name="emergency_button"),
                (spawn_pos[0], spawn_pos[1] + 1): VisibleEntity(
                    type_name="security_station",
                    tags={"station:online"},
                ),
            },
            spawn_pos=spawn_pos,
        )
        agent.reset(simulation=sim)
        agent._info_patrol_steps = 10  # pyright: ignore[reportPrivateUsage]

        action = agent._select_action(AmongUsState(position=spawn_pos, crew=1, alive=1, meeting_token=1))  # pyright: ignore[reportPrivateUsage]

        assert action.name == f"change_vibe_{VIBE_CALL_MEETING}"
    finally:
        sim.close()


def test_amongthem_nottoodumb_security_observation_can_interrupt_task_run() -> None:
    env = make_game("amongcogs", num_agents=5, max_steps=20)
    sim = Simulation(env, seed=0)
    try:
        spawn_pos = _agent_position(sim, 0)
        agent = AmongThemNotTooDumbAgent(
            PolicyEnvInterface.from_mg_cfg(env),
            agent_id=0,
            desired_role="crew",
            static_known={
                spawn_pos: VisibleEntity(type_name="empty"),
                (spawn_pos[0], spawn_pos[1] + 1): VisibleEntity(
                    type_name="security_station",
                    tags={"station:online"},
                ),
                (spawn_pos[0], spawn_pos[1] - 1): VisibleEntity(
                    type_name="wiring_station",
                    tags={"station:online"},
                    inventory={"task": 1},
                ),
            },
            spawn_pos=spawn_pos,
        )
        agent.reset(simulation=sim)
        agent._step = 30  # pyright: ignore[reportPrivateUsage]

        action = agent._select_action(AmongUsState(position=spawn_pos, crew=1, alive=1))  # pyright: ignore[reportPrivateUsage]

        assert action.name == "move_east"
        assert agent._task_goal_station_name is None  # pyright: ignore[reportPrivateUsage]
    finally:
        sim.close()
