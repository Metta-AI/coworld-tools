import pytest

from cogisis.engine import CogisisSimulator, DoorState, IntruderKind
from cogisis.mission import CogisisMission


def test_closed_doors_block_crew_movement_and_danger_intruders_destroy_them() -> None:
    sim = _sim(seed=101)
    character = sim.world.characters[0]

    sim.close_door("hibernatorium", "atrium")
    blocked = sim.perform(0, "move:atrium")

    assert character.room_id == "hibernatorium"
    assert blocked.events == [
        {"type": "move_blocked_by_door", "character_id": 0, "from": "hibernatorium", "to": "atrium"}
    ]

    character.room_id = "storage"
    sim.world.rooms["comms"].explored = True
    intruder = sim.world.spawn_intruder(IntruderKind.ADULT, "atrium")
    sim.close_door("atrium", "comms")

    danger = sim.perform(0, "move:comms", noise_roll="danger")

    assert intruder.room_id == "atrium"
    assert sim.world.door_between("atrium", "comms") is DoorState.DESTROYED
    assert any(event["type"] == "door_destroyed_by_intruder" for event in danger.events)


def test_destroyed_doors_cannot_be_closed_again() -> None:
    sim = _sim(seed=102)

    sim.destroy_door("atrium", "comms")
    result = sim.close_door("atrium", "comms")

    assert sim.world.door_between("atrium", "comms") is DoorState.DESTROYED
    assert result == [{"type": "door_already_destroyed", "from": "atrium", "to": "comms"}]


def test_fire_marker_pool_ends_game_when_exhausted_without_duplicate_consumption() -> None:
    sim = _sim(seed=103)
    room_ids = ["atrium", "cockpit", "comms", "laboratory", "surgery", "armory", "storage", "nest"]

    for room_id in room_ids:
        sim.place_fire(room_id)
    duplicate = sim.place_fire("atrium")
    exhausted = sim.place_fire("engine_1")

    assert duplicate == [{"type": "fire_already_present", "room_id": "atrium"}]
    assert sim.world.phase.value == "finished"
    assert sim.world.finished_reason == "fire_marker_exhausted"
    assert exhausted == [{"type": "game_finished", "reason": "fire_marker_exhausted"}]


def test_malfunction_marker_pool_ends_game_when_exhausted_without_duplicate_consumption() -> None:
    sim = _sim(seed=104)
    room_ids = ["atrium", "cockpit", "comms", "laboratory", "surgery", "armory", "storage", "engine_1"]

    for room_id in room_ids:
        sim.place_malfunction(room_id)
    duplicate = sim.place_malfunction("atrium")
    exhausted = sim.place_malfunction("engine_2")

    assert duplicate == [{"type": "malfunction_already_present", "room_id": "atrium"}]
    assert sim.world.phase.value == "finished"
    assert sim.world.finished_reason == "malfunction_marker_exhausted"
    assert exhausted == [{"type": "game_finished", "reason": "malfunction_marker_exhausted"}]


def test_event_fire_damage_wounds_characters_and_burns_intruders() -> None:
    sim = _sim(seed=105, max_steps=4)
    character = sim.world.characters[0]
    character.room_id = "atrium"
    intruder = sim.world.spawn_intruder(IntruderKind.ADULT, "atrium")
    sim.place_fire("atrium")

    result = sim.event_phase()

    assert character.light_wounds == 1
    assert intruder.damage == 1
    assert any(event["type"] == "fire_wound" for event in result.events)
    assert any(event["type"] == "fire_intruder_damage" for event in result.events)


def test_malfunction_blocks_room_actions_but_not_search_and_repair_clears_marker() -> None:
    sim = _sim(seed=106)
    character = sim.world.characters[0]
    character.room_id = "comms"
    sim.world.rooms["comms"].explored = True
    sim.world.rooms["comms"].search_items = 1
    sim.place_malfunction("comms")

    blocked = sim.perform(0, "send_signal")
    searched = sim.perform(0, "search")
    repaired = sim.perform(0, "repair:room")

    assert character.signal_sent is False
    assert blocked.events[-1] == {"type": "room_malfunction", "character_id": 0, "room_id": "comms"}
    assert any(event["type"] == "item_found" for event in searched.events)
    assert "comms" not in sim.world.malfunction_rooms
    assert repaired.events[-1] == {"type": "malfunction_repaired", "character_id": 0, "room_id": "comms"}


def test_slime_turns_silence_noise_roll_into_danger() -> None:
    sim = _sim(seed=107)
    character = sim.world.characters[0]
    character.room_id = "storage"
    character.slime = True
    sim.world.rooms["comms"].explored = True

    result = sim.perform(0, "move:comms", noise_roll="silence")

    assert any(event["type"] == "danger_noise" for event in result.events)
    assert {marker for marker in sim.world.noise_markers if marker[0] == "comms"} == {("comms", 1), ("comms", 2)}


@pytest.mark.parametrize(
    ("effect", "expected_event"),
    [
        ("fire", "fire_placed"),
        ("malfunction", "malfunction_placed"),
        ("slime", "slimed"),
        ("danger", "danger_noise"),
        ("silence", "noise_silence"),
    ],
)
def test_exploration_token_effects_apply_when_room_is_first_explored(effect: str, expected_event: str) -> None:
    sim = _sim(seed=108)
    sim.world.rooms["atrium"].exploration_effect = effect

    result = sim.perform(0, "move:atrium", noise_roll=1)

    assert sim.world.rooms["atrium"].explored is True
    assert sim.world.rooms["atrium"].exploration_effect is None
    assert any(event["type"] == expected_event for event in result.events)


def test_out_of_combat_actions_are_blocked_in_combat_and_escape_move_triggers_attack() -> None:
    sim = _sim(seed=109)
    character = sim.world.characters[0]
    character.room_id = "atrium"
    sim.world.rooms["comms"].explored = True
    sim.world.spawn_intruder(IntruderKind.ADULT, "atrium")
    hand_before = [card["id"] for card in character.action_hand]

    blocked = sim.perform(0, "search")
    hand_after_blocked = [card["id"] for card in character.action_hand]
    escaped = sim.perform(0, "move:comms", noise_roll="silence")

    assert hand_after_blocked == hand_before
    assert blocked.events == [{"type": "action_blocked_by_combat", "character_id": 0, "action": "search"}]
    assert character.room_id == "comms"
    assert character.serious_wounds == 1
    assert any(event["type"] == "escaped_combat" for event in escaped.events)
    assert any(event["type"] == "intruder_attack" for event in escaped.events)


def _sim(*, seed: int, max_steps: int = 15) -> CogisisSimulator:
    return CogisisSimulator(CogisisMission(num_cogs=1, max_steps=max_steps, seed=seed).build_world())
