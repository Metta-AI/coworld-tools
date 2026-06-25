"""Integration tests for Euchre game mechanics."""

import random

import pytest
from mettagrid.simulator import Simulation

from cogame_euchre.game import (
    DEFAULT_MAX_STEPS,
    NUM_PLAYERS,
    EuchreMission,
)


def _make_sim(seed: int = 42, max_steps: int = DEFAULT_MAX_STEPS) -> Simulation:
    mission = EuchreMission.create(num_agents=NUM_PLAYERS, max_steps=max_steps)
    mission.seed = seed  # Deterministic card dealing
    env = mission.make_env()
    return Simulation(env, seed=seed)


def _step_all_noop(sim: Simulation, n: int = 1) -> None:
    for _ in range(n):
        for i in range(sim.num_agents):
            sim.agent(i).set_action("noop")
        sim.step()


def _agent_id_for_player(sim: Simulation, player: int) -> int:
    """Find the agent_id for a given player number (0-based). Player IDs are 1-based in inventory."""
    player_id = player + 1
    for obj in sim.grid_objects().values():
        if obj.get("type_name") == "agent" and obj.get("inv:player_id", 0) == player_id:
            return obj["agent_id"]
    raise ValueError(f"No agent found with player_id={player_id}")


def _agent_pos(sim: Simulation, agent_idx: int) -> tuple[int, int]:
    for obj in sim.grid_objects().values():
        if obj.get("type_name") == "agent" and obj.get("agent_id") == agent_idx:
            return (obj["r"], obj["c"])
    raise ValueError(f"Agent {agent_idx} not found")


def _step_one(sim: Simulation, agent_idx: int, action: str) -> None:
    """Step one tick with the given agent taking the given action, others noop."""
    sim.agent(agent_idx).set_action(action)
    for i in range(sim.num_agents):
        if i != agent_idx:
            sim.agent(i).set_action("noop")
    sim.step()


def _navigate_and_use(sim: Simulation, agent_idx: int, target_r: int, target_c: int, max_steps: int = 40) -> bool:
    """Navigate agent to adjacent cell, then move onto target to trigger on_use."""
    for _ in range(max_steps):
        ar, ac = _agent_pos(sim, agent_idx)
        dr = target_r - ar
        dc = target_c - ac
        if dr == 0 and dc == 0:
            return True  # Already on target (shouldn't happen with objects)
        if abs(dr) + abs(dc) == 1:
            # Adjacent — one more move triggers on_use
            action = "move_south" if dr > 0 else "move_north" if dr < 0 else "move_east" if dc > 0 else "move_west"
            _step_one(sim, agent_idx, action)
            return True
        # Navigate toward target
        if abs(dr) >= abs(dc):
            action = "move_south" if dr > 0 else "move_north"
        else:
            action = "move_east" if dc > 0 else "move_west"
        _step_one(sim, agent_idx, action)
    return False


def _play_one_card(sim: Simulation, player: int) -> bool:
    """Navigate the agent to a card slot and play a card.

    Tries each available card slot (nearest first). With follow-suit rules,
    the nearest card may not be playable, so we try the next one.
    """
    agent_idx = _agent_id_for_player(sim, player)
    prev = sim.episode_stats.get("game", {}).get("cards_played", 0)

    # Gather all available card slots sorted by distance
    ar, ac = _agent_pos(sim, agent_idx)
    slots = []
    for obj in sim.grid_objects().values():
        tn = obj.get("type_name", "")
        if tn.startswith(f"card_slot_p{player}_") and obj.get("inv:has_card", 0) >= 1:
            dist = abs(obj["r"] - ar) + abs(obj["c"] - ac)
            slots.append((dist, obj["r"], obj["c"]))
    slots.sort()

    for _, r, c in slots:
        _navigate_and_use(sim, agent_idx, r, c)
        if sim.episode_stats.get("game", {}).get("cards_played", 0) > prev:
            return True
    return False


def _agents_with_current_player_tag(sim: Simulation) -> list[int]:
    """Return player_ids (1-based) of agents that have the current_player tag."""
    objects = sim.grid_objects()
    agents = [
        (obj.get("inv:player_id", 0), set(obj.get("tag_ids", [])))
        for obj in objects.values()
        if obj.get("type_name") == "agent"
    ]
    if not agents:
        return []
    all_tag_sets = [tags for _, tags in agents]
    common_tags = all_tag_sets[0].intersection(*all_tag_sets[1:])
    return [pid for pid, tags in agents if tags - common_tags]


class TestGameCreation:
    def test_creates_with_4_agents(self):
        sim = _make_sim()
        assert sim.num_agents == NUM_PLAYERS
        sim.close()

    def test_game_has_correct_max_steps(self):
        sim = _make_sim(max_steps=100)
        _step_all_noop(sim, 90)
        assert not sim.is_done()
        sim.close()

    def test_agents_have_player_ids(self):
        sim = _make_sim()
        player_ids = set()
        for i in range(NUM_PLAYERS):
            pid = sim.agent(i).inventory.get("player_id", -1)
            player_ids.add(pid)
        assert player_ids == {1, 2, 3, 4}
        sim.close()


class TestTurnSystem:
    def test_current_player_starts_at_1(self):
        sim = _make_sim()
        _step_all_noop(sim, 1)
        stats = sim.episode_stats
        assert stats.get("game", {}).get("current_player", 0) == 1.0
        sim.close()

    def test_current_player_stays_without_card_play(self):
        sim = _make_sim()
        _step_all_noop(sim, 10)
        assert sim.episode_stats.get("game", {}).get("current_player", 0) == 1.0
        sim.close()

    def test_current_player_tag_on_active_agent(self):
        sim = _make_sim()
        _step_all_noop(sim, 1)
        tagged = _agents_with_current_player_tag(sim)
        assert tagged == [1], f"Expected [1], got {tagged}"
        sim.close()

    def test_only_one_agent_tagged(self):
        sim = _make_sim()
        _step_all_noop(sim, 20)
        assert len(_agents_with_current_player_tag(sim)) == 1
        sim.close()


class TestCardSlots:
    def test_card_slots_exist(self):
        sim = _make_sim()
        objects = sim.grid_objects()
        card_slot_count = sum(1 for obj in objects.values() if obj.get("type_name", "").startswith("card_slot_"))
        assert card_slot_count == NUM_PLAYERS * 5
        sim.close()


class TestCardPlay:
    def test_playing_card_advances_turn(self):
        """Playing a card should increment cards_played and advance current_player."""
        sim = _make_sim(max_steps=500)
        _step_all_noop(sim, 1)
        assert _play_one_card(sim, player=0), "Player 0 failed to play a card"
        stats = sim.episode_stats.get("game", {})
        assert stats["cards_played"] >= 1
        assert stats["current_player"] == 2.0
        sim.close()

    def test_card_power_transfers_to_play_slot(self):
        """When a card is played, its power should appear on the play slot."""
        sim = _make_sim(max_steps=500)
        _step_all_noop(sim, 1)
        _play_one_card(sim, player=0)
        for obj in sim.grid_objects().values():
            if obj.get("type_name") == "play_slot_0":
                assert obj.get("inv:card_power", 0) > 0, "card_power should transfer to play_slot"
                assert obj.get("inv:team_id", 0) > 0, "team_id should be set on play_slot"
                break
        sim.close()

    def test_trick_evaluation_after_4_cards(self):
        """After all 4 players play a card, the trick should be evaluated."""
        sim = _make_sim(max_steps=500)
        _step_all_noop(sim, 1)
        for player in range(4):
            assert _play_one_card(sim, player=player), f"Player {player} failed to play"
        # Let trick eval + reset events fire
        _step_all_noop(sim, 3)
        stats = sim.episode_stats.get("game", {})
        tricks_a = stats.get("tricks_won_a", 0)
        tricks_b = stats.get("tricks_won_b", 0)
        assert tricks_a + tricks_b >= 1, f"Expected trick won, got a={tricks_a}, b={tricks_b}"
        sim.close()

    def test_game_progresses_after_trick(self):
        """After trick eval, winner leads next (current_player = winner's player_id)."""
        sim = _make_sim(max_steps=500)
        _step_all_noop(sim, 1)
        for player in range(4):
            _play_one_card(sim, player=player)
        _step_all_noop(sim, 3)
        stats = sim.episode_stats.get("game", {})
        # current_player should be set to the trick winner's player_id (1-4)
        cp = stats.get("current_player", 0)
        assert 1 <= cp <= 4, f"current_player should be 1-4, got {cp}"
        # cards_played on controller should be reset (0 = absent from inventory)
        for obj in sim.grid_objects().values():
            if obj.get("type_name") == "controller":
                assert obj.get("inv:cards_played", 0) == 0, "cards_played should reset after trick"
        sim.close()


class TestFullGame:
    def test_game_runs_to_completion(self):
        sim = _make_sim(max_steps=DEFAULT_MAX_STEPS)
        for _ in range(DEFAULT_MAX_STEPS):
            if sim.is_done():
                break
            for i in range(sim.num_agents):
                sim.agent(i).set_action("noop")
            sim.step()
        sim.close()

    def test_game_runs_with_random_actions(self):
        rng = random.Random(123)
        sim = _make_sim(max_steps=DEFAULT_MAX_STEPS)
        actions = sim.action_names
        for _ in range(DEFAULT_MAX_STEPS):
            if sim.is_done():
                break
            for i in range(sim.num_agents):
                sim.agent(i).set_action(rng.choice(actions))
            sim.step()
        sim.close()

    @pytest.mark.parametrize("seed", [42, 123, 7, 99])
    def test_different_seeds_produce_valid_games(self, seed: int):
        mission = EuchreMission.create(num_agents=NUM_PLAYERS, max_steps=DEFAULT_MAX_STEPS)
        mission.seed = seed
        env = mission.make_env()
        sim = Simulation(env, seed=seed)
        _step_all_noop(sim, 10)
        assert sim.num_agents == NUM_PLAYERS
        sim.close()
