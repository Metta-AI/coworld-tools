"""Built-in policies for Cogisis smoke runs."""

from __future__ import annotations

from collections.abc import Callable
from random import Random

from cogisis.engine import Character, CharacterStatus, CogisisSimulator, ObjectiveKind

Policy = Callable[[CogisisSimulator], dict[int, str]]


def make_policy(name: str, *, seed: int = 0) -> Policy:
    normalized = name.strip().lower()
    if normalized == "noop":
        return noop_policy
    if normalized == "random":
        rng = Random(seed)
        return lambda sim: random_policy(sim, rng)
    if normalized in {"survivor", "baseline", "signal"}:
        return survivor_policy
    raise ValueError(f"Unknown policy {name!r}. Choose noop, random, or survivor.")


def noop_policy(sim: CogisisSimulator) -> dict[int, str]:
    return {character_id: "pass" for character_id in sim.world.characters}


def random_policy(sim: CogisisSimulator, rng: Random) -> dict[int, str]:
    actions: dict[int, str] = {}
    for character_id, character in sim.world.characters.items():
        if character.status is not CharacterStatus.ACTIVE:
            actions[character_id] = "noop"
            continue
        room = sim.world.rooms[character.room_id]
        choices = ["search", "rest", "use_room", *[f"move:{neighbor}" for neighbor in room.exits.values()]]
        if sim.world.room_intruders(character.room_id):
            choices.extend(["shoot", "melee"])
        actions[character_id] = rng.choice(choices)
    return actions


def survivor_policy(sim: CogisisSimulator) -> dict[int, str]:
    actions: dict[int, str] = {}
    for character_id, character in sorted(sim.world.characters.items()):
        actions[character_id] = _survivor_action(sim, character)
    return actions


def _survivor_action(sim: CogisisSimulator, character: Character) -> str:
    if character.status is not CharacterStatus.ACTIVE:
        return "noop"
    intruders_here = sim.world.room_intruders(character.room_id)
    if intruders_here and character.ammo > 0:
        return f"shoot:{intruders_here[0].intruder_id}"
    if intruders_here:
        return f"melee:{intruders_here[0].intruder_id}"

    objective = character.chosen_objective or (character.objectives[0] if character.objectives else None)
    if objective and objective.kind is ObjectiveKind.SEND_SIGNAL and not character.signal_sent:
        if character.room_id == "comms":
            return "send_signal"
        return _move_toward(sim, character, "comms")
    if objective and objective.kind is ObjectiveKind.DISCOVER_WEAKNESS and sim.world.discovered_weaknesses == 0:
        if character.room_id == "laboratory":
            return "discover_weakness"
        return _move_toward(sim, character, "laboratory")
    if objective and objective.kind is ObjectiveKind.DESTROY_NEST and sim.world.nest_eggs > 0:
        if character.room_id == "nest":
            return "destroy_egg"
        return _move_toward(sim, character, "nest")

    damaged = [engine for engine in sim.world.ship.engines.values() if not engine.working]
    if len(damaged) >= 2:
        target = damaged[0].room_id
        if character.room_id == target:
            return f"repair:{damaged[0].engine_id}"
        return _move_toward(sim, character, target)

    if character.room_id == "hibernatorium" and sim.world.ship.time_remaining <= sim.world.ship.hibernation_opens_at:
        return "hibernate"
    return _move_toward(sim, character, "hibernatorium")


def _move_toward(sim: CogisisSimulator, character: Character, target_room_id: str) -> str:
    path = sim.world.shortest_path(character.room_id, target_room_id)
    if len(path) < 2:
        return "noop"
    return f"move:{path[1]}"
