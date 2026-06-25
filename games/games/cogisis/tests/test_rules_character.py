from cogisis.engine import CharacterStatus, CogisisSimulator
from cogisis.mission import CogisisMission


def test_light_wounds_convert_to_serious_and_third_serious_wound_kills() -> None:
    sim = _sim(seed=201)
    character = sim.world.characters[0]

    sim.suffer_light_wound(0)
    sim.suffer_light_wound(0)
    converted = sim.suffer_light_wound(0)
    sim.suffer_serious_wound(0)
    killed = sim.suffer_serious_wound(0)

    assert character.light_wounds == 0
    assert character.serious_wounds == 3
    assert character.status is CharacterStatus.DEAD
    assert any(event["type"] == "serious_wound_from_light" for event in converted)
    assert any(event["type"] == "character_dead" for event in killed)
    assert sim.world.escape_pods["pod_a"].unlocked
    assert sim.world.escape_pods["pod_b"].unlocked


def test_contamination_scan_discards_clean_cards_and_infected_card_attaches_larva() -> None:
    sim = _sim(seed=202)
    character = sim.world.characters[0]
    character.contamination_cards = [
        {"id": "clean_1", "infected": False},
        {"id": "infected_1", "infected": True},
    ]
    character.contamination = 2

    result = sim.scan_contamination(0)

    assert character.contamination_cards == [{"id": "infected_1", "infected": True}]
    assert character.contamination == 1
    assert character.larva is True
    assert result[-1] == {"type": "larva_attached", "character_id": 0}


def test_scanning_infected_contamination_with_larva_kills_character_and_spawns_creeper() -> None:
    sim = _sim(seed=203)
    character = sim.world.characters[0]
    character.room_id = "atrium"
    character.larva = True
    character.contamination_cards = [{"id": "infected_1", "infected": True}]
    character.contamination = 1

    result = sim.scan_contamination(0)

    assert character.status is CharacterStatus.DEAD
    assert any(intruder.kind.value == "creeper" and intruder.room_id == "atrium" for intruder in sim.world.intruders.values())
    assert any(event["type"] == "character_dead" for event in result)
    assert any(event["type"] == "creeper_spawned_from_larva" for event in result)


def test_surgery_removes_larva_and_contamination_then_adds_light_wound() -> None:
    sim = _sim(seed=204)
    character = sim.world.characters[0]
    character.room_id = "surgery"
    character.larva = True
    character.contamination_cards = [{"id": "infected_1", "infected": True}]
    character.contamination = 1

    result = sim.perform(0, "use_room")

    assert character.larva is False
    assert character.contamination_cards == []
    assert character.contamination == 0
    assert character.light_wounds == 1
    assert any(event["type"] == "surgery" for event in result.events)


def test_heavy_objects_are_limited_to_two_and_can_be_dropped() -> None:
    sim = _sim(seed=205)
    character = sim.world.characters[0]

    first = sim.take_object(0, "egg")
    second = sim.take_object(0, "corpse")
    third = sim.take_object(0, "intruder_carcass")
    dropped = sim.drop_object(0, "egg")

    assert first == [{"type": "object_taken", "character_id": 0, "object": "egg"}]
    assert second == [{"type": "object_taken", "character_id": 0, "object": "corpse"}]
    assert third == [{"type": "object_limit", "character_id": 0, "object": "intruder_carcass"}]
    assert dropped == [{"type": "object_dropped", "character_id": 0, "object": "egg"}]
    assert character.heavy_objects == ["corpse"]


def test_crafting_consumes_components_and_creates_crafted_item() -> None:
    sim = _sim(seed=206)
    character = sim.world.characters[0]
    character.items = ["chemicals", "tools"]

    result = sim.perform(0, "craft:flamethrower")

    assert character.items == ["flamethrower"]
    assert result.events[-1] == {"type": "crafted", "character_id": 0, "item": "flamethrower"}


def test_armory_room_reload_is_capped_by_ammo_capacity() -> None:
    sim = _sim(seed=207)
    character = sim.world.characters[0]
    character.room_id = "armory"
    character.ammo = 4

    result = sim.perform(0, "use_room")

    assert character.ammo == 5
    assert result.events[-1] == {"type": "ammo_loaded", "character_id": 0, "ammo": 5}


def test_self_destruct_cannot_start_after_hibernation_and_unlocks_pods_on_yellow_track() -> None:
    sim = CogisisSimulator(CogisisMission(num_cogs=2, max_steps=6, seed=208).build_world())
    sim.world.characters[1].status = CharacterStatus.HIBERNATED

    blocked = sim.perform(0, "start_self_destruct")

    assert blocked.events == [{"type": "self_destruct_blocked", "character_id": 0, "reason": "hibernated_character"}]

    sim = _sim(seed=209, max_steps=6)
    sim.perform(0, "start_self_destruct")
    sim.event_phase()
    unlocked = sim.event_phase()

    assert sim.world.escape_pods["pod_a"].unlocked
    assert sim.world.escape_pods["pod_b"].unlocked
    assert any(event["type"] == "escape_pods_unlocked" for event in unlocked.events)


def test_engine_status_can_be_checked_without_repairing_engine() -> None:
    sim = _sim(seed=210)
    character = sim.world.characters[0]
    character.room_id = "engine_1"
    engine = sim.world.ship.engines["engine_1"]
    engine.working = False
    engine.checked = False

    result = sim.perform(0, "check_engine:engine_1")

    assert engine.working is False
    assert engine.checked is True
    assert result.events[-1] == {
        "type": "engine_checked",
        "character_id": 0,
        "engine_id": "engine_1",
        "working": False,
    }


def _sim(*, seed: int, max_steps: int = 15) -> CogisisSimulator:
    return CogisisSimulator(CogisisMission(num_cogs=1, max_steps=max_steps, seed=seed).build_world())
