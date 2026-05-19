from cogisis.engine import CharacterStatus, CogisisSimulator, IntruderKind, Objective, ObjectiveKind
from cogisis.mission import CogisisMission


def test_mission_builds_ship_with_core_nemesis_systems() -> None:
    world = CogisisMission(num_cogs=3, seed=7).build_world()

    assert world.rooms["hibernatorium"].kind == "hibernatorium"
    assert world.rooms["hibernatorium"].explored is True
    assert world.rooms["atrium"].explored is False
    assert world.rooms["cockpit"].explored is False
    assert {"cockpit", "comms", "laboratory", "nest", "engine_1", "engine_2", "engine_3"} <= set(world.rooms)
    assert len(world.characters) == 3
    assert len(world.ship.engines) == 3
    assert world.ship.destination in {"earth", "mars", "deep_space"}
    assert world.intruder_bag.count(IntruderKind.ADULT) >= 3


def test_noisy_movement_places_noise_then_spawns_intruder_from_bag() -> None:
    world = CogisisMission(num_cogs=1, seed=1).build_world()
    world.intruder_bag = [IntruderKind.ADULT]
    sim = CogisisSimulator(world)

    first = sim.perform(0, "move:atrium", noise_roll=1)

    assert world.characters[0].room_id == "atrium"
    assert ("atrium", 1) in world.noise_markers
    assert [event["type"] for event in first.events] == ["cards_discarded", "move", "explore", "noise_marker"]

    second = sim.perform(0, "move:cockpit", noise_roll=1)
    third = sim.perform(0, "move:atrium", noise_roll=1)

    assert [event["type"] for event in second.events] == ["cards_discarded", "move", "explore", "noise_marker"]
    assert any(event["type"] == "encounter" for event in third.events)
    assert len(world.intruders) == 1
    assert world.characters[0].chosen_objective is not None


def test_intruder_attack_adds_wounds_and_death_unlocks_escape_pods() -> None:
    world = CogisisMission(num_cogs=1, seed=2).build_world()
    sim = CogisisSimulator(world)
    character = world.characters[0]
    character.room_id = "atrium"
    intruder_id = world.spawn_intruder(IntruderKind.ADULT, "atrium").intruder_id

    sim.perform_intruder_attack(intruder_id, 0)
    sim.perform_intruder_attack(intruder_id, 0)
    result = sim.perform_intruder_attack(intruder_id, 0)

    assert character.status is CharacterStatus.DEAD
    assert character.serious_wounds == 3
    assert world.escape_pods["pod_a"].unlocked
    assert any(event["type"] == "first_death" for event in result.events)


def test_repair_signal_hibernate_and_victory_check() -> None:
    world = CogisisMission(num_cogs=1, seed=3).build_world()
    sim = CogisisSimulator(world)
    character = world.characters[0]
    character.objectives = [Objective(ObjectiveKind.SEND_SIGNAL), Objective(ObjectiveKind.SURVIVE_AND_EARTH)]
    character.chosen_objective = character.objectives[0]

    character.room_id = "comms"
    sim.perform(0, "send_signal")
    character.room_id = "engine_1"
    world.ship.engines["engine_1"].working = False
    sim.perform(0, "repair:engine_1")
    world.ship.engines["engine_2"].working = True
    world.ship.engines["engine_3"].working = True
    character.room_id = "hibernatorium"
    world.ship.time_remaining = world.ship.hibernation_opens_at
    sim.perform(0, "hibernate")
    world.finish_game("manual")

    stats = sim.stats()
    assert character.status is CharacterStatus.HIBERNATED
    assert world.ship.engines["engine_1"].working
    assert stats["winners"] == [0]
    assert stats["ship_survived"]


def test_damaged_engines_make_hibernated_character_lose() -> None:
    world = CogisisMission(num_cogs=1, seed=4).build_world()
    sim = CogisisSimulator(world)
    character = world.characters[0]
    character.chosen_objective = Objective(ObjectiveKind.SURVIVE_AND_EARTH)
    character.status = CharacterStatus.HIBERNATED
    world.ship.destination = "earth"
    world.ship.engines["engine_1"].working = False
    world.ship.engines["engine_2"].working = False
    world.finish_game("manual")

    stats = sim.stats()
    assert stats["ship_survived"] is False
    assert stats["winners"] == []


def test_character_can_set_public_display_name() -> None:
    world = CogisisMission(num_cogs=1, seed=14).build_world()
    sim = CogisisSimulator(world)

    result = sim.perform(0, "set-name: Ripley Prime ")

    assert world.characters[0].name == "Ripley Prime"
    assert world.characters[0].snapshot()["display_name"] == "Ripley Prime"
    assert result.events == [{"type": "name_set", "character_id": 0, "name": "Ripley Prime"}]


def test_paid_actions_discard_selected_action_cards() -> None:
    world = CogisisMission(num_cogs=1, seed=15).build_world()
    sim = CogisisSimulator(world)
    character = world.characters[0]
    paid_card = character.action_hand[0]["id"]

    result = sim.perform(0, "search", discard_cards=[paid_card], require_discard_selection=True)

    assert paid_card not in [card["id"] for card in character.action_hand]
    assert paid_card in [card["id"] for card in character.action_discard]
    assert result.events[0] == {
        "type": "cards_discarded",
        "character_id": 0,
        "action": "search",
        "cost": 1,
        "cards": [paid_card],
    }
    assert any(event["type"] in {"item_found", "search_empty"} for event in result.events)


def test_paid_actions_can_require_explicit_discards() -> None:
    world = CogisisMission(num_cogs=1, seed=16).build_world()
    sim = CogisisSimulator(world)

    try:
        sim.perform(0, "search", require_discard_selection=True)
    except ValueError as exc:
        assert "requires 1 discarded card" in str(exc)
    else:
        raise AssertionError("expected missing discard selection to fail")


def test_event_phase_refills_action_hand_to_five_cards() -> None:
    world = CogisisMission(num_cogs=1, max_steps=3, seed=17).build_world()
    sim = CogisisSimulator(world)
    character = world.characters[0]
    discarded = character.action_hand.pop(0)
    character.action_discard.append(discarded)

    result = sim.event_phase()

    assert len(character.action_hand) == 5
    assert any(
        event == {"type": "action_cards_drawn", "character_id": 0, "count": 1, "hand_count": 5}
        for event in result.events
    )


def test_player_phase_allows_two_actions_per_character_before_event_phase() -> None:
    world = CogisisMission(num_cogs=2, max_steps=4, seed=11).build_world()
    sim = CogisisSimulator(world)

    result = sim.step({0: ["noop", "noop"], 1: ["pass", "noop"]})

    actor_events = [(event["type"], event.get("character_id")) for event in result.events[:3]]
    assert actor_events == [("noop", 0), ("noop", 0), ("pass", 1)]
    assert any(event["type"] == "time_advanced" for event in result.events)
    assert world.current_step == 1


def test_policy_player_phase_replans_between_actions() -> None:
    world = CogisisMission(num_cogs=1, max_steps=4, seed=13).build_world()
    sim = CogisisSimulator(world)

    def policy(simulator: CogisisSimulator) -> dict[int, str]:
        room_id = simulator.world.characters[0].room_id
        if room_id == "hibernatorium":
            return {0: "cautious_move:atrium:1"}
        if room_id == "atrium":
            return {0: "cautious_move:cockpit:2"}
        return {0: "pass"}

    result = sim.step_with_policy(policy)

    assert world.characters[0].room_id == "cockpit"
    move_targets = [event["to"] for event in result.events if event["type"] == "move"]
    assert move_targets == ["atrium", "cockpit"]
    assert world.current_step == 1
