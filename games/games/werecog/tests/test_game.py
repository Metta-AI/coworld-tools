from __future__ import annotations

from werecog import make_game
from werecog import policy as werewolf_policy
from werecog import WerecogMission
from mettagrid import Simulator
from mettagrid.map_builder.ascii import AsciiMapBuilder
from mettagrid.policy.loader import discover_and_register_policies, initialize_or_load_policy
from mettagrid.policy.policy_env_interface import PolicyEnvInterface
from mettagrid.runner.rollout import run_episode_local
from mettagrid.simulator import AgentObservation, VisibleTalk
from mettagrid.util.uri_resolvers.schemes import policy_spec_from_uri


def _make_day_observation_for_policy():
    env = make_game("werewolf_mafia", num_agents=8, max_steps=120)
    env_interface = PolicyEnvInterface.from_mg_cfg(env)
    policy = werewolf_policy.WerewolfMafiaAgentPolicy(env_interface, agent_id=0)
    sim = Simulator().new_simulation(env, seed=7)
    center = werewolf_policy.Location(env_interface.obs_height // 2, env_interface.obs_width // 2)

    for _ in range(32):
        observation = sim.agent(0).observation
        me, entities = werewolf_policy._parse_entities(observation.tokens, env_interface.tag_id_to_name, center)
        if werewolf_policy._phase_name(me.inventory) == "day":
            return sim, policy, observation, me, entities, center, env_interface
        for agent in sim.agents():
            agent.set_action("noop")
        sim.step()

    sim.close()
    raise AssertionError("expected a day-phase observation")


def test_werewolf_mafia_game_contains_public_resources() -> None:
    env = make_game("werewolf_mafia", num_agents=12, max_steps=180)

    assert {
        "alive",
        "vote_token",
        "suspicion",
        "day_phase",
        "night_phase",
        "day_vote_open",
        "night_hunt_open",
        "accusation",
    }.issubset(set(env.game.resource_names))
    assert "villager" not in env.game.resource_names
    assert "werewolf" not in env.game.resource_names
    assert "role_werewolf" in env.game.obs.global_obs.obs
    assert "role_villager" in env.game.obs.global_obs.obs


def test_werewolf_mafia_assigns_werewolf_minority() -> None:
    env = make_game("werewolf_mafia", num_agents=12, max_steps=180)

    werewolf_count = sum(int(agent.initial_stats.get("werewolf", 0)) for agent in env.game.agents)
    villager_count = sum(int(agent.initial_stats.get("villager", 0)) for agent in env.game.agents)

    assert werewolf_count == 3
    assert 0 < werewolf_count < len(env.game.agents)
    assert werewolf_count + villager_count == len(env.game.agents)


def test_werewolf_mafia_uses_compact_village_ascii_map() -> None:
    env = make_game("werewolf_mafia", num_agents=8, max_steps=120)

    map_builder = env.game.map_builder
    assert isinstance(map_builder, AsciiMapBuilder.Config)
    assert map_builder.width <= 21
    assert map_builder.height <= 21

    flattened = "".join("".join(row) for row in map_builder.map_data)
    assert flattened.count("@") == 8
    assert flattened.count("b") == 1
    assert "v" in flattened
    assert "w" in flattened
    assert "l" in flattened
    assert "t" in flattened
    assert "c" in flattened


def test_werewolf_mafia_seeded_spawn_layout_is_deterministic() -> None:
    env = make_game("werewolf_mafia", num_agents=16, max_steps=120)

    sim_a = Simulator().new_simulation(env, seed=7)
    sim_b = Simulator().new_simulation(env, seed=7)
    positions_a = sorted(
        (obj["agent_id"], tuple(obj["location"])) for obj in sim_a.grid_objects().values() if "agent_id" in obj
    )
    positions_b = sorted(
        (obj["agent_id"], tuple(obj["location"])) for obj in sim_b.grid_objects().values() if "agent_id" in obj
    )

    assert positions_a == positions_b

    sim_a.close()
    sim_b.close()


def test_werewolf_mafia_starts_at_night() -> None:
    env = make_game("werewolf_mafia", num_agents=8, max_steps=120)

    for agent in env.game.agents:
        assert agent.inventory.initial.get("night_phase", 0) == 1
        assert agent.inventory.initial.get("day_phase", 0) == 0
        assert agent.inventory.initial.get("vote_token", 0) == 0
        assert agent.inventory.initial.get("day_vote_open", 0) == 0
        assert agent.inventory.initial.get("night_hunt_open", 0) == 0
        assert agent.inventory.initial.get("accusation", 0) == 0


def test_werewolf_mafia_uses_phase_driven_observation_radius() -> None:
    env = make_game("werewolf_mafia", num_agents=8, max_steps=120)

    assert env.game.obs.observation_radius_stat == "vision_radius"
    discussion_radius = max(env.game.map_builder.width, env.game.map_builder.height)
    werewolf_radii = []
    villager_radii = []
    for agent in env.game.agents:
        radius = agent.initial_stats["vision_radius"]
        if int(agent.initial_stats.get("werewolf", 0)) == 1:
            werewolf_radii.append(radius)
        else:
            villager_radii.append(radius)

    assert werewolf_radii
    assert villager_radii
    assert all(radius >= discussion_radius for radius in werewolf_radii)
    assert all(radius == 0 for radius in villager_radii)


def test_werewolf_mafia_keeps_single_cpp_team_group() -> None:
    env = make_game("werewolf_mafia", num_agents=12, max_steps=180)

    werewolf_count = 0
    villager_count = 0
    for agent in env.game.agents:
        if int(agent.initial_stats.get("werewolf", 0)) == 1:
            werewolf_count += 1
        if int(agent.initial_stats.get("villager", 0)) == 1:
            villager_count += 1
        assert agent.team_id == 0

    assert werewolf_count > 0
    assert villager_count > 0
    assert werewolf_count + villager_count == len(env.game.agents)


def test_werewolf_mafia_render_huds_track_game_resources() -> None:
    env = make_game("werewolf_mafia", num_agents=12, max_steps=180)

    huds = env.game.render.agent_huds
    status = env.game.render.object_status["agent"]
    assert {"alive", "vote_token", "suspicion", "day_phase", "night_phase", "day_vote_open", "night_hunt_open"}.issubset(set(huds))
    assert {"alive", "vote_token", "suspicion", "accusation", "day_phase", "night_phase", "day_vote_open", "night_hunt_open"}.issubset(set(status))


def test_werewolf_mafia_enables_talk_for_discussion_sessions() -> None:
    env = make_game("werewolf_mafia", num_agents=12, max_steps=180)

    assert env.game.talk.enabled is True
    assert env.game.talk.max_length == 140
    assert env.game.talk.cooldown_steps == 6


def test_werewolf_mafia_scales_night_kills_with_lobby_size() -> None:
    assert WerecogMission.create(16, 180).night_kills_per_phase == 1
    assert WerecogMission.create(24, 180).night_kills_per_phase == 2


def test_werewolf_mafia_large_pack_splits_hunt_targets() -> None:
    packmates = frozenset({1, 2, 3, 4, 5})
    assert werewolf_policy._night_hunt_slots(packmates) == 2
    assert werewolf_policy._pack_hunt_slot(0, packmates) == 0
    assert werewolf_policy._pack_hunt_slot(2, frozenset({0, 1, 3, 4, 5})) == 0
    assert werewolf_policy._pack_hunt_slot(3, frozenset({0, 1, 2, 4, 5})) == 1


def test_werewolf_mafia_consensus_target_preserves_agent_zero_mentions() -> None:
    center = werewolf_policy.Location(0, 0)
    entity_zero = werewolf_policy.VisibleEntity(
        location=werewolf_policy.Location(5, 0),
        tags=frozenset({"type:agent"}),
        inventory={"alive": 1},
        agent_id=0,
    )
    entity_one = werewolf_policy.VisibleEntity(
        location=werewolf_policy.Location(1, 0),
        tags=frozenset({"type:agent"}),
        inventory={"alive": 1},
        agent_id=1,
    )

    target = werewolf_policy._consensus_target(
        center,
        [entity_zero, entity_one],
        mentioned_counts={0: 2, 1: 1},
    )

    assert target == entity_zero


def test_werewolf_mafia_registers_village_prop_objects() -> None:
    env = make_game("werewolf_mafia", num_agents=12, max_steps=180)

    assert {"village_tree", "cottage", "lantern_post"}.issubset(env.game.objects)


def test_werewolf_mafia_render_uses_shared_public_agent_avatar() -> None:
    env = make_game("werewolf_mafia", num_agents=12, max_steps=180)

    agent_assets = env.game.render.assets["agent"]
    assert len(agent_assets) == 2
    assert agent_assets[0].asset == "werewolf_mafia_villager"
    assert agent_assets[0].resources == {"alive": 1}
    assert agent_assets[1].asset == "werewolf_mafia_dead"


def test_werewolf_mafia_registers_phase_and_winner_events() -> None:
    env = make_game("werewolf_mafia", num_agents=12, max_steps=180)

    assert {
        "night_phase_start",
        "night_phase_villager_visibility",
        "night_phase_werewolf_visibility",
        "night_hunt_open",
        "day_phase_start",
        "day_vote_open",
        "villagers_win_check",
        "werewolves_win_check",
    }.issubset(set(env.game.events))


def test_werewolf_mafia_disables_irrelevant_vibe_actions() -> None:
    env = make_game("werewolf_mafia", num_agents=12, max_steps=180)
    assert all(not action.name.startswith("change_vibe_") for action in env.game.actions.actions())
    assert env.game.talk.enabled is True


def test_werewolf_mafia_keeps_role_inventory_private_in_spatial_observations() -> None:
    env = make_game("werewolf_mafia", num_agents=8, max_steps=120)

    sim = Simulator().new_simulation(env, seed=7)
    obs = sim.observations()[0].tokens
    center = (env.game.obs.height // 2, env.game.obs.width // 2)
    role_tokens = [
        token
        for token in obs
        if token.location is not None and ("werewolf" in token.feature.name or "villager" in token.feature.name)
    ]
    public_status_tokens = [
        token
        for token in obs
        if token.location is not None
        and token.feature.name == "inv:alive"
        and (token.location.row, token.location.col) != center
    ]
    assert role_tokens == []
    assert public_status_tokens
    sim.close()


def test_werewolf_mafia_exposes_private_role_and_packmate_globals() -> None:
    env = make_game("werewolf_mafia", num_agents=8, max_steps=120)

    sim = Simulator().new_simulation(env, seed=7)
    obs = sim.observations()[0].tokens
    globals_by_name = {token.feature.name: int(token.value) for token in obs if token.is_global}
    assert globals_by_name["role_werewolf"] == 1
    assert globals_by_name["role_villager"] == 0
    assert globals_by_name["wolf_pack_0"] == 2
    sim.close()


def test_werewolf_mafia_scripted_agents_visit_mechanics_and_log_game_stats() -> None:
    discover_and_register_policies("werecog")
    env = make_game("werewolf_mafia", num_agents=16, max_steps=220)
    policy_spec = policy_spec_from_uri("metta://policy/werecog", device="cpu")

    results, _ = run_episode_local(
        policy_specs=[policy_spec],
        assignments=[0] * 16,
        env=env,
        seed=7,
        max_action_time_ms=10000,
        render_mode="none",
    )

    game_stats = results.stats["game"]
    assert game_stats["day_executions"] >= 1
    assert game_stats["day_votes_cast"] >= 1
    assert game_stats["accusations_made"] >= 1
    assert game_stats["ballots_collected"] >= 1
    werewolf_executions = game_stats.get("werewolf_executions", 0)
    assert 0 <= werewolf_executions <= game_stats["day_executions"]

    agent_stats = results.stats["agent"]
    day_phase_entries = sum(float(stats.get("day_phase.gained", 0.0)) for stats in agent_stats) / len(agent_stats)
    night_phase_entries = sum(float(stats.get("night_phase.gained", 0.0)) for stats in agent_stats) / len(agent_stats)
    assert day_phase_entries >= 1.0
    assert night_phase_entries >= 1.0


def test_werewolf_mafia_scripted_werewolves_emit_hunt_talk_at_night() -> None:
    discover_and_register_policies("werecog")
    env = make_game("werewolf_mafia", num_agents=8, max_steps=120)
    sim = Simulator().new_simulation(env, seed=7)
    observations = list(sim.observations())
    policy = initialize_or_load_policy(
        PolicyEnvInterface.from_mg_cfg(env),
        policy_spec_from_uri("metta://policy/werecog", device="cpu"),
        device_override="cpu",
    )

    for observation in observations:
        globals_by_name = {token.feature.name: int(token.value) for token in observation.tokens if token.is_global}
        if globals_by_name.get("role_werewolf", 0) < 1:
            continue
        action = policy.agent_policy(observation.agent_id).step(observation)
        assert action.talk is not None
        assert "hunt agent " in action.talk
        sim.close()
        return

    sim.close()
    raise AssertionError("expected at least one werewolf observation")


def test_werewolf_mafia_scripted_agents_open_day_with_discussion_rally() -> None:
    sim, policy, observation, me, _, _, _ = _make_day_observation_for_policy()

    try:
        assert me.inventory["vote_token"] == 1

        policy.step(observation)

        assert policy._infos["plan"] in {"discuss", "search_bell"}
    finally:
        sim.close()


def test_werewolf_mafia_vote_mentions_persist_across_day_discussion_window() -> None:
    sim, policy, observation, me, entities, center, env_interface = _make_day_observation_for_policy()

    try:
        assert me.inventory["vote_token"] == 1
        candidates = [entity for entity in entities if "type:agent" in entity.tags]
        default_target = werewolf_policy._consensus_target(center, candidates, {})
        assert default_target is not None
        talk_target = next(entity for entity in reversed(candidates) if entity.agent_id != default_target.agent_id)
        speaker_id = next(
            (
                entity.agent_id
                for entity in candidates
                if entity.agent_id not in {policy._agent_id, talk_target.agent_id}
            ),
            talk_target.agent_id,
        )
        observation_with_talk = AgentObservation(
            agent_id=observation.agent_id,
            tokens=observation.tokens,
            talk=[
                VisibleTalk(
                    agent_id=speaker_id,
                    text=f"agent {talk_target.agent_id} keeps dodging, vote agent {talk_target.agent_id}",
                    location=center,
                    remaining_steps=env_interface.talk.cooldown_steps,
                )
            ],
        )
        quiet_observation = AgentObservation(agent_id=observation.agent_id, tokens=observation.tokens, talk=[])

        policy.step(observation_with_talk)
        for _ in range(werewolf_policy._DAY_DISCUSSION_STEPS - 1):
            policy.step(quiet_observation)
        action = policy.step(quiet_observation)

        assert action.name == werewolf_policy._move_toward(center, talk_target.location)
    finally:
        sim.close()


def test_werewolf_mafia_embedded_vote_calls_still_count_as_mentions() -> None:
    sim, policy, observation, me, entities, center, env_interface = _make_day_observation_for_policy()

    try:
        assert me.inventory["vote_token"] == 1
        talk_target = next(
            entity for entity in reversed(entities) if "type:agent" in entity.tags and entity.agent_id is not None
        )
        observation_with_talk = AgentObservation(
            agent_id=observation.agent_id,
            tokens=observation.tokens,
            talk=[
                VisibleTalk(
                    agent_id=999,
                    text=f"agent {talk_target.agent_id} feels off, vote agent {talk_target.agent_id}",
                    location=center,
                    remaining_steps=env_interface.talk.cooldown_steps,
                )
            ],
        )

        policy.step(observation_with_talk)

        assert policy._phase_mentions["vote"][talk_target.agent_id] == 1
    finally:
        sim.close()


def test_werewolf_mafia_public_discussion_objective_does_not_force_accusation_run() -> None:
    sim, policy, observation, me, entities, center, _ = _make_day_observation_for_policy()

    try:
        assert me.inventory["vote_token"] == 1
        talk_target = next(entity for entity in entities if "type:agent" in entity.tags and entity.agent_id is not None)
        policy.apply_strategy(
            objective="public_discussion",
            target_agent_id=talk_target.agent_id,
            talk=f"vote agent {talk_target.agent_id}",
        )

        for _ in range(werewolf_policy._DAY_DISCUSSION_STEPS + 1):
            policy.step(observation)

        assert policy._infos["plan"] != "accuse"
    finally:
        sim.close()


def test_werewolf_mafia_public_vote_objective_accuses_directive_target_after_discussion() -> None:
    sim, policy, observation, me, entities, center, _ = _make_day_observation_for_policy()

    try:
        assert me.inventory["vote_token"] == 1
        talk_target = next(
            entity for entity in reversed(entities) if "type:agent" in entity.tags and entity.agent_id is not None
        )
        policy.apply_strategy(
            objective="public_vote",
            target_agent_id=talk_target.agent_id,
            talk=f"vote agent {talk_target.agent_id}",
        )

        for _ in range(werewolf_policy._DAY_DISCUSSION_STEPS + 1):
            action = policy.step(observation)

        assert policy._infos["plan"] == "accuse"
        assert action.name == werewolf_policy._move_toward(center, talk_target.location)
    finally:
        sim.close()


def test_werewolf_blend_in_target_requires_visible_mentioned_candidates() -> None:
    center = werewolf_policy.Location(0, 0)
    villager = werewolf_policy.VisibleEntity(
        location=werewolf_policy.Location(1, 0),
        tags=frozenset({"type:agent"}),
        inventory={"alive": 1},
        agent_id=2,
    )

    target = werewolf_policy._blend_in_target(
        center,
        [villager],
        mentioned_counts={1: 3},
        preferred_agent_id=None,
    )

    assert target is None
