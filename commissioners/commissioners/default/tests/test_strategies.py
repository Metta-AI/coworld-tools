from strategies import round_robin_matchups


def test_round_robin_pairs_all_combinations():
    policies = ["a", "b", "c", "d"]
    episodes = round_robin_matchups(policies, variant_id="v", num_agents=2)
    # C(4, 2) = 6 unordered pairs.
    assert len(episodes) == 6
    pairs = {tuple(e["policy_version_ids"]) for e in episodes}
    assert len(pairs) == 6
    for episode in episodes:
        assert episode["variant_id"] == "v"
        assert len(episode["policy_version_ids"]) == 2


def test_episodes_per_pair_multiplies_count():
    episodes = round_robin_matchups(["a", "b", "c"], variant_id="v", num_agents=2, episodes_per_pair=3)
    # C(3, 2) = 3 pairs x 3 episodes each.
    assert len(episodes) == 9


def test_request_ids_unique_and_seeds_increment():
    episodes = round_robin_matchups(["a", "b", "c"], variant_id="v", num_agents=2, seed_base=10)
    request_ids = [e["request_id"] for e in episodes]
    assert len(set(request_ids)) == len(request_ids)
    assert [e["seed"] for e in episodes] == [10, 11, 12]


def test_too_few_policies_returns_no_episodes():
    assert round_robin_matchups(["only"], variant_id="v", num_agents=2) == []


def test_single_agent_variant_schedules_each_policy():
    episodes = round_robin_matchups(["a", "b", "c"], variant_id="v", num_agents=1)
    assert len(episodes) == 3
    assert all(len(e["policy_version_ids"]) == 1 for e in episodes)
