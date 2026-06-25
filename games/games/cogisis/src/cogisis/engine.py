"""First-party Cogisis engine modeled after Nemesis-style board-game play."""

from __future__ import annotations

from collections import deque
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from random import Random
from typing import Any

PLAYER_TURN_ACTIONS = 2
ACTION_HAND_SIZE = 5
MAX_AMMO = 5
HEAVY_OBJECT_LIMIT = 2

ACTION_CARD_LIBRARY: dict[str, dict[str, str]] = {
    "move_1": {"id": "move_1", "name": "Move"},
    "move_2": {"id": "move_2", "name": "Move"},
    "search_1": {"id": "search_1", "name": "Search"},
    "repair_1": {"id": "repair_1", "name": "Repair"},
    "rest_1": {"id": "rest_1", "name": "Rest"},
    "attack_1": {"id": "attack_1", "name": "Attack"},
    "plan_1": {"id": "plan_1", "name": "Plan"},
    "improvise_1": {"id": "improvise_1", "name": "Improvise"},
    "sprint_1": {"id": "sprint_1", "name": "Sprint"},
    "jury_rig_1": {"id": "jury_rig_1", "name": "Jury Rig"},
}
DEFAULT_ACTION_DECK = list(ACTION_CARD_LIBRARY)
ACTION_COSTS: dict[str, int] = {
    "noop": 0,
    "pass": 0,
    "set-name": 0,
    "set_name": 0,
    "cautious_move": 2,
    "start_self_destruct": 2,
}
DEFAULT_ACTION_COST = 1
CRAFT_RECIPES: dict[str, tuple[str, ...]] = {
    "flamethrower": ("chemicals", "tools"),
    "taser": ("battery", "cables"),
}


class CharacterStatus(StrEnum):
    ACTIVE = "active"
    PASSED = "passed"
    HIBERNATED = "hibernated"
    ESCAPED = "escaped"
    DEAD = "dead"


class Phase(StrEnum):
    PLAYER = "player"
    EVENT = "event"
    FINISHED = "finished"


class DoorState(StrEnum):
    OPEN = "open"
    CLOSED = "closed"
    DESTROYED = "destroyed"


class IntruderKind(StrEnum):
    BLANK = "blank"
    LARVA = "larva"
    CREEPER = "creeper"
    ADULT = "adult"
    BREEDER = "breeder"
    QUEEN = "queen"


class ObjectiveKind(StrEnum):
    SURVIVE_AND_EARTH = "survive_and_earth"
    SURVIVE_AND_MARS = "survive_and_mars"
    SEND_SIGNAL = "send_signal"
    DISCOVER_WEAKNESS = "discover_weakness"
    DESTROY_NEST = "destroy_nest"
    KILL_QUEEN = "kill_queen"
    ONLY_SURVIVOR = "only_survivor"


@dataclass(frozen=True)
class Objective:
    kind: ObjectiveKind
    target_character_id: int | None = None

    def snapshot(self) -> dict[str, Any]:
        data: dict[str, Any] = {"kind": self.kind.value}
        if self.target_character_id is not None:
            data["target_character_id"] = self.target_character_id
        return data


@dataclass
class Room:
    room_id: str
    name: str
    kind: str
    exits: dict[int, str] = field(default_factory=dict)
    explored: bool = True
    search_items: int = 0
    exploration_effect: str | None = None

    def snapshot(self) -> dict[str, Any]:
        return {
            "id": self.room_id,
            "name": self.name,
            "kind": self.kind,
            "exits": dict(sorted(self.exits.items())),
            "explored": self.explored,
            "search_items": self.search_items,
            "exploration_effect": self.exploration_effect,
        }


@dataclass
class EngineStatus:
    engine_id: str
    room_id: str
    working: bool
    checked: bool = False

    def snapshot(self) -> dict[str, Any]:
        return {
            "id": self.engine_id,
            "room_id": self.room_id,
            "working": self.working,
            "checked": self.checked,
        }


@dataclass
class EscapePod:
    pod_id: str
    room_id: str
    unlocked: bool = False
    launched: bool = False
    occupants: list[int] = field(default_factory=list)

    def snapshot(self) -> dict[str, Any]:
        return {
            "id": self.pod_id,
            "room_id": self.room_id,
            "unlocked": self.unlocked,
            "launched": self.launched,
            "occupants": list(self.occupants),
        }


@dataclass
class ShipStatus:
    destination: str
    engines: dict[str, EngineStatus]
    time_remaining: int = 15
    hibernation_opens_at: int = 8
    coordinates_known: bool = False
    self_destruct: int | None = None

    def damaged_engines(self) -> int:
        return sum(1 for engine in self.engines.values() if not engine.working)

    def survived(self) -> bool:
        return self.damaged_engines() < 2 and self.self_destruct != 0

    def snapshot(self) -> dict[str, Any]:
        return {
            "destination": self.destination,
            "time_remaining": self.time_remaining,
            "hibernation_open": self.time_remaining <= self.hibernation_opens_at,
            "coordinates_known": self.coordinates_known,
            "self_destruct": self.self_destruct,
            "engines": {
                engine_id: engine.snapshot()
                for engine_id, engine in sorted(self.engines.items())
            },
        }


@dataclass
class Character:
    character_id: int
    role: str
    room_id: str
    objectives: list[Objective]
    name: str | None = None
    chosen_objective: Objective | None = None
    status: CharacterStatus = CharacterStatus.ACTIVE
    light_wounds: int = 0
    serious_wounds: int = 0
    contamination: int = 0
    contamination_cards: list[dict[str, Any]] = field(default_factory=list)
    larva: bool = False
    slime: bool = False
    ammo: int = 3
    signal_sent: bool = False
    items: list[str] = field(default_factory=list)
    heavy_objects: list[str] = field(default_factory=list)
    action_deck: list[dict[str, str]] = field(default_factory=list)
    action_hand: list[dict[str, str]] = field(default_factory=list)
    action_discard: list[dict[str, str]] = field(default_factory=list)

    def active(self) -> bool:
        return self.status is CharacterStatus.ACTIVE

    def survived_marker(self) -> bool:
        return self.status in {CharacterStatus.ESCAPED, CharacterStatus.HIBERNATED}

    def display_name(self) -> str:
        return self.name or f"Cog {self.character_id}"

    def snapshot(self) -> dict[str, Any]:
        return {
            "id": self.character_id,
            "name": self.name,
            "display_name": self.display_name(),
            "role": self.role,
            "room_id": self.room_id,
            "status": self.status.value,
            "light_wounds": self.light_wounds,
            "serious_wounds": self.serious_wounds,
            "contamination": self.contamination,
            "contamination_cards": [dict(card) for card in self.contamination_cards],
            "larva": self.larva,
            "slime": self.slime,
            "ammo": self.ammo,
            "signal_sent": self.signal_sent,
            "items": list(self.items),
            "heavy_objects": list(self.heavy_objects),
            "action_hand": [dict(card) for card in self.action_hand],
            "action_discard": [dict(card) for card in self.action_discard],
            "action_deck_count": len(self.action_deck),
            "action_discard_count": len(self.action_discard),
            "objectives": [objective.snapshot() for objective in self.objectives],
            "chosen_objective": self.chosen_objective.snapshot() if self.chosen_objective else None,
        }

    def setup_action_deck(self, rng: Random) -> None:
        self.action_deck = [dict(ACTION_CARD_LIBRARY[card_id]) for card_id in DEFAULT_ACTION_DECK]
        rng.shuffle(self.action_deck)
        self.action_hand = []
        self.action_discard = []
        self.draw_action_cards(ACTION_HAND_SIZE, rng)

    def draw_action_cards(self, count: int, rng: Random) -> None:
        while count > 0:
            if not self.action_deck:
                if not self.action_discard:
                    return
                self.action_deck = self.action_discard
                self.action_discard = []
                rng.shuffle(self.action_deck)
            self.action_hand.append(self.action_deck.pop(0))
            count -= 1


@dataclass
class Intruder:
    intruder_id: int
    kind: IntruderKind
    room_id: str
    damage: int = 0

    @property
    def health(self) -> int:
        return {
            IntruderKind.LARVA: 1,
            IntruderKind.CREEPER: 2,
            IntruderKind.ADULT: 3,
            IntruderKind.BREEDER: 5,
            IntruderKind.QUEEN: 7,
            IntruderKind.BLANK: 0,
        }[self.kind]

    def snapshot(self) -> dict[str, Any]:
        return {
            "id": self.intruder_id,
            "kind": self.kind.value,
            "room_id": self.room_id,
            "damage": self.damage,
            "health": self.health,
        }


@dataclass
class StepResult:
    step: int
    rewards: dict[int, int]
    events: list[dict[str, Any]]
    done: bool


ActionPlan = str | Sequence[str]
StepPolicy = Callable[["CogisisSimulator"], Mapping[int, str]]


@dataclass
class World:
    rooms: dict[str, Room]
    characters: dict[int, Character]
    intruder_bag: list[IntruderKind]
    ship: ShipStatus
    escape_pods: dict[str, EscapePod]
    max_steps: int
    rng: Random = field(default_factory=Random)
    intruders: dict[int, Intruder] = field(default_factory=dict)
    noise_markers: set[tuple[str, int]] = field(default_factory=set)
    fire_rooms: set[str] = field(default_factory=set)
    malfunction_rooms: set[str] = field(default_factory=set)
    doors: dict[tuple[str, str], DoorState] = field(default_factory=dict)
    fire_marker_limit: int = 8
    malfunction_marker_limit: int = 8
    discovered_weaknesses: int = 0
    nest_eggs: int = 5
    killed_intruders: list[IntruderKind] = field(default_factory=list)
    first_encounter_done: bool = False
    first_death_done: bool = False
    phase: Phase = Phase.PLAYER
    current_step: int = 0
    finished_reason: str | None = None
    _next_intruder_id: int = 0

    def room_intruders(self, room_id: str) -> list[Intruder]:
        return [intruder for intruder in self.intruders.values() if intruder.room_id == room_id]

    def room_characters(self, room_id: str) -> list[Character]:
        return [character for character in self.characters.values() if character.room_id == room_id]

    def corridor_between(self, source_room_id: str, target_room_id: str) -> int | None:
        for corridor, neighbor in self.rooms[source_room_id].exits.items():
            if neighbor == target_room_id:
                return corridor
        return None

    @staticmethod
    def door_key(left_room_id: str, right_room_id: str) -> tuple[str, str]:
        return tuple(sorted((left_room_id, right_room_id)))

    def door_between(self, left_room_id: str, right_room_id: str) -> DoorState:
        return self.doors.get(self.door_key(left_room_id, right_room_id), DoorState.OPEN)

    def set_door(self, left_room_id: str, right_room_id: str, state: DoorState) -> None:
        key = self.door_key(left_room_id, right_room_id)
        if state is DoorState.OPEN:
            self.doors.pop(key, None)
        else:
            self.doors[key] = state

    def shortest_path(self, source_room_id: str, target_room_id: str) -> list[str]:
        if source_room_id == target_room_id:
            return [source_room_id]
        queue: deque[tuple[str, list[str]]] = deque([(source_room_id, [source_room_id])])
        seen = {source_room_id}
        while queue:
            room_id, path = queue.popleft()
            for next_room_id in self.rooms[room_id].exits.values():
                if next_room_id in seen:
                    continue
                next_path = [*path, next_room_id]
                if next_room_id == target_room_id:
                    return next_path
                seen.add(next_room_id)
                queue.append((next_room_id, next_path))
        return [source_room_id]

    def spawn_intruder(self, kind: IntruderKind, room_id: str) -> Intruder:
        intruder = Intruder(self._next_intruder_id, kind, room_id)
        self.intruders[intruder.intruder_id] = intruder
        self._next_intruder_id += 1
        return intruder

    def draw_intruder(self) -> IntruderKind:
        if not self.intruder_bag:
            return IntruderKind.ADULT
        index = self.rng.randrange(len(self.intruder_bag))
        return self.intruder_bag.pop(index)

    def choose_objective_for_first_encounter(self, character: Character, events: list[dict[str, Any]]) -> None:
        if character.chosen_objective is None and character.objectives:
            character.chosen_objective = character.objectives[0]
        if not self.first_encounter_done:
            self.first_encounter_done = True
            for other in self.characters.values():
                if other.chosen_objective is None and other.objectives:
                    other.chosen_objective = other.objectives[0]
            events.append({"type": "first_encounter", "chosen": character.chosen_objective.snapshot()})

    def mark_character_dead(self, character: Character, events: list[dict[str, Any]]) -> None:
        if character.status is CharacterStatus.DEAD:
            return
        character.status = CharacterStatus.DEAD
        events.append({"type": "character_dead", "character_id": character.character_id})
        if not self.first_death_done:
            self.first_death_done = True
            for pod in self.escape_pods.values():
                pod.unlocked = True
            events.append({"type": "first_death", "escape_pods_unlocked": sorted(self.escape_pods)})

    def finish_game(self, reason: str) -> None:
        self.phase = Phase.FINISHED
        self.finished_reason = reason

    def done(self) -> bool:
        return self.phase is Phase.FINISHED or self.current_step >= self.max_steps

    def character_survived_for_objectives(self, character: Character) -> bool:
        if character.status is CharacterStatus.ESCAPED:
            return True
        if character.status is CharacterStatus.HIBERNATED:
            return self.ship.survived()
        return False

    def objective_satisfied(self, character: Character) -> bool:
        objective = character.chosen_objective
        if objective is None or not self.character_survived_for_objectives(character):
            return False
        if objective.kind is ObjectiveKind.SURVIVE_AND_EARTH:
            return self.ship.survived() and self.ship.destination == "earth"
        if objective.kind is ObjectiveKind.SURVIVE_AND_MARS:
            return self.ship.survived() and self.ship.destination == "mars"
        if objective.kind is ObjectiveKind.SEND_SIGNAL:
            return character.signal_sent
        if objective.kind is ObjectiveKind.DISCOVER_WEAKNESS:
            return self.discovered_weaknesses > 0
        if objective.kind is ObjectiveKind.DESTROY_NEST:
            return self.nest_eggs <= 0
        if objective.kind is ObjectiveKind.KILL_QUEEN:
            return IntruderKind.QUEEN in self.killed_intruders
        if objective.kind is ObjectiveKind.ONLY_SURVIVOR:
            return all(
                other.character_id == character.character_id or not self.character_survived_for_objectives(other)
                for other in self.characters.values()
            )
        return False

    def snapshot(self) -> dict[str, Any]:
        return {
            "phase": self.phase.value,
            "step": self.current_step,
            "finished_reason": self.finished_reason,
            "ship": self.ship.snapshot(),
            "rooms": {room_id: room.snapshot() for room_id, room in sorted(self.rooms.items())},
            "characters": {
                character_id: character.snapshot()
                for character_id, character in sorted(self.characters.items())
            },
            "intruders": {
                intruder_id: intruder.snapshot()
                for intruder_id, intruder in sorted(self.intruders.items())
            },
            "intruder_bag": [kind.value for kind in self.intruder_bag],
            "escape_pods": {
                pod_id: pod.snapshot()
                for pod_id, pod in sorted(self.escape_pods.items())
            },
            "noise_markers": [
                {"room_id": room_id, "corridor": corridor}
                for room_id, corridor in sorted(self.noise_markers)
            ],
            "fire_rooms": sorted(self.fire_rooms),
            "malfunction_rooms": sorted(self.malfunction_rooms),
            "doors": [
                {"rooms": list(rooms), "state": state.value}
                for rooms, state in sorted(self.doors.items())
            ],
            "discovered_weaknesses": self.discovered_weaknesses,
            "nest_eggs": self.nest_eggs,
        }


class CogisisSimulator:
    """Deterministic ship-board simulator."""

    def __init__(self, world: World):
        self.world = world

    @property
    def done(self) -> bool:
        return self.world.done()

    def perform(
        self,
        character_id: int,
        action: str,
        *,
        noise_roll: int | str | None = None,
        discard_cards: Sequence[str] | None = None,
        require_discard_selection: bool = False,
    ) -> StepResult:
        events: list[dict[str, Any]] = []
        rewards = {agent_id: 0 for agent_id in self.world.characters}
        character = self.world.characters[character_id]
        if self.world.phase is Phase.FINISHED:
            return StepResult(self.world.current_step, rewards, [{"type": "game_finished"}], True)
        if not character.active():
            return StepResult(self.world.current_step, rewards, [{"type": "inactive", "character_id": character_id}], self.done)

        verb, args = self._parse_action(action)
        blocked_event = self._blocked_action_event(character, action, verb, args)
        if blocked_event is not None:
            return StepResult(self.world.current_step, rewards, [blocked_event], self.done)
        if self._action_is_known(verb):
            events.extend(
                self._pay_action_cost(
                    character,
                    action,
                    discard_cards=discard_cards,
                    require_discard_selection=require_discard_selection,
                )
            )
        if verb == "noop":
            events.append({"type": "noop", "character_id": character_id})
        elif verb == "pass":
            events.append({"type": "pass", "character_id": character_id})
        elif verb in {"set-name", "set_name"}:
            events.extend(self._set_name(character, ":".join(args)))
        elif verb in {"move", "cautious_move"}:
            target_room_id = args[0] if args else ""
            chosen_corridor = int(args[1]) if verb == "cautious_move" and len(args) > 1 else None
            events.extend(self._move(character, target_room_id, noise_roll=noise_roll, chosen_corridor=chosen_corridor))
        elif verb == "search":
            events.extend(self._search(character))
        elif verb == "rest":
            events.extend(self._rest(character))
        elif verb == "shoot":
            events.extend(self._attack_intruder(character, int(args[0]) if args else None, ranged=True))
        elif verb == "melee":
            events.extend(self._attack_intruder(character, int(args[0]) if args else None, ranged=False))
        elif verb == "repair":
            events.extend(self._repair(character, args[0] if args else ""))
        elif verb == "send_signal":
            events.extend(self._send_signal(character))
        elif verb == "set_destination":
            events.extend(self._set_destination(character, args[0] if args else "earth"))
        elif verb == "discover_weakness":
            events.extend(self._discover_weakness(character))
        elif verb == "destroy_egg":
            events.extend(self._destroy_egg(character))
        elif verb == "hibernate":
            events.extend(self._hibernate(character))
        elif verb == "escape":
            events.extend(self._escape(character, args[0] if args else ""))
        elif verb == "use_room":
            events.extend(self._use_room(character))
        elif verb == "start_self_destruct":
            self.world.ship.self_destruct = 4
            events.append({"type": "self_destruct_started", "character_id": character_id})
        elif verb == "craft":
            events.extend(self._craft(character, args[0] if args else ""))
        elif verb == "take_object":
            events.extend(self.take_object(character_id, args[0] if args else ""))
        elif verb == "drop_object":
            events.extend(self.drop_object(character_id, args[0] if args else ""))
        elif verb == "check_engine":
            events.extend(self._check_engine(character, args[0] if args else ""))
        else:
            events.append({"type": "unknown_action", "character_id": character_id, "action": action})

        self._finish_if_no_active_characters(events)
        return StepResult(self.world.current_step, rewards, events, self.done)

    def close_door(self, left_room_id: str, right_room_id: str) -> list[dict[str, Any]]:
        state = self.world.door_between(left_room_id, right_room_id)
        if state is DoorState.DESTROYED:
            return [{"type": "door_already_destroyed", "from": left_room_id, "to": right_room_id}]
        if state is DoorState.CLOSED:
            return [{"type": "door_already_closed", "from": left_room_id, "to": right_room_id}]
        self.world.set_door(left_room_id, right_room_id, DoorState.CLOSED)
        return [{"type": "door_closed", "from": left_room_id, "to": right_room_id}]

    def open_door(self, left_room_id: str, right_room_id: str) -> list[dict[str, Any]]:
        state = self.world.door_between(left_room_id, right_room_id)
        if state is DoorState.DESTROYED:
            return [{"type": "door_already_destroyed", "from": left_room_id, "to": right_room_id}]
        if state is DoorState.OPEN:
            return [{"type": "door_already_open", "from": left_room_id, "to": right_room_id}]
        self.world.set_door(left_room_id, right_room_id, DoorState.OPEN)
        return [{"type": "door_opened", "from": left_room_id, "to": right_room_id}]

    def destroy_door(self, left_room_id: str, right_room_id: str) -> list[dict[str, Any]]:
        state = self.world.door_between(left_room_id, right_room_id)
        if state is DoorState.DESTROYED:
            return [{"type": "door_already_destroyed", "from": left_room_id, "to": right_room_id}]
        self.world.set_door(left_room_id, right_room_id, DoorState.DESTROYED)
        return [{"type": "door_destroyed", "from": left_room_id, "to": right_room_id}]

    def place_fire(self, room_id: str) -> list[dict[str, Any]]:
        if room_id in self.world.fire_rooms:
            return [{"type": "fire_already_present", "room_id": room_id}]
        if len(self.world.fire_rooms) >= self.world.fire_marker_limit:
            self.world.finish_game("fire_marker_exhausted")
            return [{"type": "game_finished", "reason": "fire_marker_exhausted"}]
        self.world.fire_rooms.add(room_id)
        return [{"type": "fire_placed", "room_id": room_id}]

    def place_malfunction(self, room_id: str) -> list[dict[str, Any]]:
        if room_id in {"nest", "slime"}:
            return [{"type": "malfunction_forbidden", "room_id": room_id}]
        if room_id in self.world.malfunction_rooms:
            return [{"type": "malfunction_already_present", "room_id": room_id}]
        if len(self.world.malfunction_rooms) >= self.world.malfunction_marker_limit:
            self.world.finish_game("malfunction_marker_exhausted")
            return [{"type": "game_finished", "reason": "malfunction_marker_exhausted"}]
        self.world.malfunction_rooms.add(room_id)
        return [{"type": "malfunction_placed", "room_id": room_id}]

    def suffer_light_wound(self, character_id: int) -> list[dict[str, Any]]:
        return self._suffer_light_wound(self.world.characters[character_id])

    def suffer_serious_wound(self, character_id: int) -> list[dict[str, Any]]:
        return self._suffer_serious_wound(self.world.characters[character_id])

    def scan_contamination(self, character_id: int) -> list[dict[str, Any]]:
        return self._scan_contamination(self.world.characters[character_id])

    def take_object(self, character_id: int, object_name: str) -> list[dict[str, Any]]:
        character = self.world.characters[character_id]
        if len(character.heavy_objects) >= HEAVY_OBJECT_LIMIT:
            return [{"type": "object_limit", "character_id": character_id, "object": object_name}]
        character.heavy_objects.append(object_name)
        return [{"type": "object_taken", "character_id": character_id, "object": object_name}]

    def drop_object(self, character_id: int, object_name: str) -> list[dict[str, Any]]:
        character = self.world.characters[character_id]
        if object_name not in character.heavy_objects:
            return [{"type": "object_missing", "character_id": character_id, "object": object_name}]
        character.heavy_objects.remove(object_name)
        return [{"type": "object_dropped", "character_id": character_id, "object": object_name}]

    def step(self, actions: Mapping[int, ActionPlan]) -> StepResult:
        return self._run_player_phase(
            lambda character_id, action_index: self._planned_action_at(
                actions.get(character_id, "pass"),
                action_index,
            )
        )

    def step_with_policy(self, policy: StepPolicy) -> StepResult:
        return self._run_player_phase(
            lambda character_id, _action_index: policy(self).get(character_id, "pass")
        )

    def _run_player_phase(self, action_for_slot: Callable[[int, int], str | None]) -> StepResult:
        events: list[dict[str, Any]] = []
        rewards = {agent_id: 0 for agent_id in self.world.characters}
        if self.world.phase is Phase.FINISHED:
            return StepResult(self.world.current_step, rewards, [], True)

        for character_id in sorted(self.world.characters):
            character = self.world.characters[character_id]
            if not character.active():
                continue
            for action_index in range(PLAYER_TURN_ACTIONS):
                if self.done or not character.active():
                    break
                action = action_for_slot(character_id, action_index)
                if action is None:
                    break
                events.extend(self.perform(character_id, action).events)
                if self.action_ends_turn(action):
                    break

        if not self.done:
            events.extend(self.event_phase().events)
        return StepResult(self.world.current_step, rewards, events, self.done)

    @staticmethod
    def _planned_action_at(action_plan: ActionPlan, action_index: int) -> str | None:
        if action_index >= PLAYER_TURN_ACTIONS:
            return None
        if isinstance(action_plan, str):
            return action_plan if action_index == 0 else None
        if not action_plan:
            return "pass" if action_index == 0 else None
        if action_index >= len(action_plan):
            return None
        return str(action_plan[action_index])

    @staticmethod
    def action_ends_turn(action: str) -> bool:
        return CogisisSimulator._parse_action(action)[0] == "pass"

    @staticmethod
    def action_is_metadata(action: str) -> bool:
        return CogisisSimulator._parse_action(action)[0] in {"set-name", "set_name"}

    @staticmethod
    def action_cost(action: str) -> int:
        verb = CogisisSimulator._parse_action(action)[0]
        return ACTION_COSTS.get(verb, DEFAULT_ACTION_COST if CogisisSimulator._action_is_known(verb) else 0)

    @staticmethod
    def _action_is_known(verb: str) -> bool:
        return verb in {
            "noop",
            "pass",
            "set-name",
            "set_name",
            "move",
            "cautious_move",
            "search",
            "rest",
            "shoot",
            "melee",
            "repair",
            "send_signal",
            "set_destination",
            "discover_weakness",
            "destroy_egg",
            "hibernate",
            "escape",
            "use_room",
            "start_self_destruct",
            "craft",
            "take_object",
            "drop_object",
            "check_engine",
        }

    def _blocked_action_event(
        self,
        character: Character,
        action: str,
        verb: str,
        args: Sequence[str],
    ) -> dict[str, Any] | None:
        room_intruders = self.world.room_intruders(character.room_id)
        if room_intruders and verb not in {"noop", "pass", "set-name", "set_name", "move", "cautious_move", "shoot", "melee"}:
            return {"type": "action_blocked_by_combat", "character_id": character.character_id, "action": action}
        if verb in {"move", "cautious_move"}:
            target_room_id = args[0] if args else ""
            if target_room_id in self.world.rooms and self.world.door_between(character.room_id, target_room_id) is DoorState.CLOSED:
                return {
                    "type": "move_blocked_by_door",
                    "character_id": character.character_id,
                    "from": character.room_id,
                    "to": target_room_id,
                }
        if self._room_action_disabled_by_malfunction(character, verb):
            return {"type": "room_malfunction", "character_id": character.character_id, "room_id": character.room_id}
        if verb == "start_self_destruct" and any(
            other.status is CharacterStatus.HIBERNATED for other in self.world.characters.values()
        ):
            return {"type": "self_destruct_blocked", "character_id": character.character_id, "reason": "hibernated_character"}
        return None

    def _room_action_disabled_by_malfunction(self, character: Character, verb: str) -> bool:
        if character.room_id not in self.world.malfunction_rooms:
            return False
        return verb in {
            "send_signal",
            "set_destination",
            "discover_weakness",
            "destroy_egg",
            "hibernate",
            "escape",
            "use_room",
            "start_self_destruct",
        }

    def event_phase(self) -> StepResult:
        events: list[dict[str, Any]] = []
        rewards = {agent_id: 0 for agent_id in self.world.characters}
        if self.world.phase is Phase.FINISHED:
            return StepResult(self.world.current_step, rewards, events, True)

        self.world.phase = Phase.EVENT
        self.world.current_step += 1
        self.world.ship.time_remaining -= 1
        events.append({"type": "time_advanced", "time_remaining": self.world.ship.time_remaining})

        for room_id in sorted(self.world.fire_rooms):
            for character in self.world.room_characters(room_id):
                if character.active():
                    events.extend(self._suffer_light_wound(character, room_id=room_id, event_type="fire_wound"))
            for intruder in list(self.world.room_intruders(room_id)):
                events.extend(self._damage_intruder(intruder, 1, "fire_intruder_damage"))

        for intruder in list(self.world.intruders.values()):
            targets = [character for character in self.world.room_characters(intruder.room_id) if character.active()]
            if targets:
                events.extend(self.perform_intruder_attack(intruder.intruder_id, targets[0].character_id).events)

        if self.world.ship.self_destruct is not None:
            self.world.ship.self_destruct -= 1
            events.append({"type": "self_destruct_tick", "remaining": self.world.ship.self_destruct})
            if self.world.ship.self_destruct <= 2:
                unlocked = []
                for pod_id, pod in sorted(self.world.escape_pods.items()):
                    if not pod.unlocked:
                        pod.unlocked = True
                        unlocked.append(pod_id)
                if unlocked:
                    events.append({"type": "escape_pods_unlocked", "pods": unlocked, "reason": "self_destruct"})
            if self.world.ship.self_destruct <= 0:
                self.world.finish_game("self_destruct")

        if self.world.ship.time_remaining <= 0:
            self.world.finish_game("hyperjump")
        if self.world.current_step >= self.world.max_steps:
            self.world.finish_game("max_steps")
        self._finish_if_no_active_characters(events)
        if self.world.phase is not Phase.FINISHED:
            events.extend(self._draw_action_hands())
            self.world.phase = Phase.PLAYER
        return StepResult(self.world.current_step, rewards, events, self.done)

    def _draw_action_hands(self) -> list[dict[str, Any]]:
        events: list[dict[str, Any]] = []
        for character in self.world.characters.values():
            if not character.active():
                continue
            missing = ACTION_HAND_SIZE - len(character.action_hand)
            if missing <= 0:
                continue
            before = len(character.action_hand)
            character.draw_action_cards(missing, self.world.rng)
            drawn = len(character.action_hand) - before
            if drawn:
                events.append(
                    {
                        "type": "action_cards_drawn",
                        "character_id": character.character_id,
                        "count": drawn,
                        "hand_count": len(character.action_hand),
                    }
                )
        return events

    def perform_intruder_attack(self, intruder_id: int, target_character_id: int) -> StepResult:
        events: list[dict[str, Any]] = []
        rewards = {agent_id: 0 for agent_id in self.world.characters}
        intruder = self.world.intruders[intruder_id]
        character = self.world.characters[target_character_id]
        if not character.active():
            return StepResult(self.world.current_step, rewards, [], self.done)

        if intruder.kind is IntruderKind.LARVA:
            events.append({"type": "intruder_attack", "intruder_id": intruder_id, "character_id": target_character_id, "wound": "contamination"})
            events.extend(self._add_contamination_card(character, infected=False))
        elif intruder.kind is IntruderKind.CREEPER:
            events.append({"type": "intruder_attack", "intruder_id": intruder_id, "character_id": target_character_id, "wound": "light"})
            events.extend(self._suffer_light_wound(character))
            events.extend(self._suffer_light_wound(character))
        elif intruder.kind is IntruderKind.ADULT:
            events.append({"type": "intruder_attack", "intruder_id": intruder_id, "character_id": target_character_id, "wound": "serious"})
            events.extend(self._suffer_serious_wound(character))
        else:
            events.append({"type": "intruder_attack", "intruder_id": intruder_id, "character_id": target_character_id, "wound": "critical"})
            events.extend(self._suffer_serious_wound(character))
            events.extend(self._add_contamination_card(character, infected=False))
        return StepResult(self.world.current_step, rewards, events, self.done)

    def _suffer_light_wound(
        self,
        character: Character,
        *,
        room_id: str | None = None,
        event_type: str = "light_wound",
    ) -> list[dict[str, Any]]:
        events: list[dict[str, Any]] = [
            {"type": event_type, "character_id": character.character_id, **({"room_id": room_id} if room_id else {})}
        ]
        character.light_wounds += 1
        if character.light_wounds < 3:
            return events
        character.light_wounds = 0
        events.append({"type": "serious_wound_from_light", "character_id": character.character_id})
        events.extend(self._suffer_serious_wound(character))
        return events

    def _suffer_serious_wound(self, character: Character) -> list[dict[str, Any]]:
        events = [{"type": "serious_wound", "character_id": character.character_id}]
        character.serious_wounds += 1
        if character.serious_wounds >= 3:
            self.world.mark_character_dead(character, events)
        return events

    def _add_contamination_card(self, character: Character, *, infected: bool) -> list[dict[str, Any]]:
        card = {
            "id": f"contamination_{len(character.contamination_cards) + 1}",
            "infected": infected,
        }
        character.contamination_cards.append(card)
        character.contamination = len(character.contamination_cards)
        return [{"type": "contamination_card_added", "character_id": character.character_id, "card": card["id"]}]

    def _scan_contamination(self, character: Character) -> list[dict[str, Any]]:
        infected_cards = [card for card in character.contamination_cards if card.get("infected")]
        removed = len(character.contamination_cards) - len(infected_cards)
        character.contamination_cards = infected_cards
        character.contamination = len(character.contamination_cards)
        events: list[dict[str, Any]] = [
            {
                "type": "contamination_scanned",
                "character_id": character.character_id,
                "removed": removed,
                "infected": len(infected_cards),
            }
        ]
        if not infected_cards:
            return events
        if character.larva:
            self.world.mark_character_dead(character, events)
            creeper = self.world.spawn_intruder(IntruderKind.CREEPER, character.room_id)
            events.append(
                {
                    "type": "creeper_spawned_from_larva",
                    "character_id": character.character_id,
                    "intruder_id": creeper.intruder_id,
                    "room_id": character.room_id,
                }
            )
            return events
        character.larva = True
        events.append({"type": "larva_attached", "character_id": character.character_id})
        return events

    def observation(self, character_id: int) -> dict[str, Any]:
        character = self.world.characters[character_id]
        room = self.world.rooms[character.room_id]
        return {
            "self": character.snapshot(),
            "room": room.snapshot(),
            "neighbors": {
                corridor: self.world.rooms[neighbor].snapshot()
                for corridor, neighbor in sorted(room.exits.items())
            },
            "intruders_here": [intruder.snapshot() for intruder in self.world.room_intruders(room.room_id)],
            "noise_markers": [
                {"room_id": room_id, "corridor": corridor}
                for room_id, corridor in sorted(self.world.noise_markers)
                if room_id == room.room_id
            ],
            "ship": self.world.ship.snapshot(),
            "phase": self.world.phase.value,
            "step": self.world.current_step,
        }

    def stats(self) -> dict[str, Any]:
        winners = [
            character_id
            for character_id, character in sorted(self.world.characters.items())
            if self.world.objective_satisfied(character)
        ]
        return {
            "steps": self.world.current_step,
            "phase": self.world.phase.value,
            "done": self.done,
            "finished_reason": self.world.finished_reason,
            "ship_survived": self.world.ship.survived(),
            "destination": self.world.ship.destination,
            "winners": winners,
            "survivors": [
                character_id
                for character_id, character in sorted(self.world.characters.items())
                if self.world.character_survived_for_objectives(character)
            ],
            "characters": {
                character_id: character.snapshot()
                for character_id, character in sorted(self.world.characters.items())
            },
            "ship": self.world.ship.snapshot(),
            "intruders": {
                intruder_id: intruder.snapshot()
                for intruder_id, intruder in sorted(self.world.intruders.items())
            },
        }

    def render_unicode(self) -> str:
        lines = [
            f"Cogisis step={self.world.current_step} phase={self.world.phase.value} time={self.world.ship.time_remaining}",
            f"destination={self.world.ship.destination} damaged_engines={self.world.ship.damaged_engines()}",
        ]
        for room_id in sorted(self.world.rooms):
            room = self.world.rooms[room_id]
            chars = ",".join(str(character.character_id) for character in self.world.room_characters(room_id))
            intruders = ",".join(f"{intruder.kind.value[0]}{intruder.intruder_id}" for intruder in self.world.room_intruders(room_id))
            noise = ",".join(str(corridor) for marker_room, corridor in sorted(self.world.noise_markers) if marker_room == room_id)
            parts = [room_id]
            if chars:
                parts.append(f"C[{chars}]")
            if intruders:
                parts.append(f"I[{intruders}]")
            if noise:
                parts.append(f"N[{noise}]")
            if room_id in self.world.fire_rooms:
                parts.append("fire")
            if room_id in self.world.malfunction_rooms:
                parts.append("malfunction")
            parts.append("->" + ",".join(f"{corridor}:{target}" for corridor, target in sorted(room.exits.items())))
            lines.append(" ".join(parts))
        return "\n".join(lines)

    def _move(
        self,
        character: Character,
        target_room_id: str,
        *,
        noise_roll: int | str | None,
        chosen_corridor: int | None,
    ) -> list[dict[str, Any]]:
        events: list[dict[str, Any]] = []
        corridor = self.world.corridor_between(character.room_id, target_room_id)
        if corridor is None:
            return [{"type": "move_blocked", "character_id": character.character_id, "target": target_room_id}]

        source_room_id = character.room_id
        escaping_intruders = list(self.world.room_intruders(source_room_id))
        character.room_id = target_room_id
        events.append({"type": "move", "character_id": character.character_id, "from": source_room_id, "to": target_room_id})
        if not self.world.rooms[target_room_id].explored:
            self.world.rooms[target_room_id].explored = True
            events.append({"type": "explore", "character_id": character.character_id, "room_id": target_room_id})
            events.extend(self._resolve_exploration_effect(character, target_room_id))

        if escaping_intruders:
            events.append(
                {
                    "type": "escaped_combat",
                    "character_id": character.character_id,
                    "from": source_room_id,
                    "to": target_room_id,
                }
            )
            for intruder in escaping_intruders:
                if character.active():
                    events.extend(self.perform_intruder_attack(intruder.intruder_id, character.character_id).events)

        if self.world.room_intruders(target_room_id):
            self.world.choose_objective_for_first_encounter(character, events)
            return events

        if chosen_corridor is not None:
            events.extend(self._place_noise_or_encounter(character, target_room_id, chosen_corridor))
            return events

        events.extend(self._resolve_noise(character, target_room_id, noise_roll=noise_roll))
        return events

    def _resolve_noise(self, character: Character, room_id: str, *, noise_roll: int | str | None) -> list[dict[str, Any]]:
        roll = noise_roll if noise_roll is not None else self.world.rng.choice([1, 2, 3, 4, "danger", "silence"])
        if roll == "silence" and character.slime:
            roll = "danger"
        if roll == "silence":
            return [{"type": "noise_silence", "character_id": character.character_id, "room_id": room_id}]
        if roll == "danger":
            return self._resolve_danger(character, room_id)
        return self._place_noise_or_encounter(character, room_id, int(roll))

    def _resolve_danger(self, character: Character, room_id: str) -> list[dict[str, Any]]:
        events: list[dict[str, Any]] = []
        moved = False
        for neighbor_id in self.world.rooms[room_id].exits.values():
            for intruder in self.world.room_intruders(neighbor_id):
                if self.world.door_between(neighbor_id, room_id) is DoorState.CLOSED:
                    self.world.set_door(neighbor_id, room_id, DoorState.DESTROYED)
                    events.append(
                        {
                            "type": "door_destroyed_by_intruder",
                            "intruder_id": intruder.intruder_id,
                            "from": neighbor_id,
                            "to": room_id,
                        }
                    )
                    continue
                intruder.room_id = room_id
                moved = True
                events.append({"type": "danger_intruder_moves", "intruder_id": intruder.intruder_id, "to": room_id})
        if events and not moved:
            return events
        if moved:
            self.world.choose_objective_for_first_encounter(character, events)
            return events
        for corridor in self.world.rooms[room_id].exits:
            self.world.noise_markers.add((room_id, corridor))
        events.append({"type": "danger_noise", "character_id": character.character_id, "room_id": room_id})
        return events

    def _place_noise_or_encounter(self, character: Character, room_id: str, corridor: int) -> list[dict[str, Any]]:
        marker = (room_id, corridor)
        if marker not in self.world.noise_markers:
            self.world.noise_markers.add(marker)
            return [{"type": "noise_marker", "character_id": character.character_id, "room_id": room_id, "corridor": corridor}]
        self.world.noise_markers = {
            existing
            for existing in self.world.noise_markers
            if existing[0] != room_id
        }
        kind = self.world.draw_intruder()
        if kind is IntruderKind.BLANK:
            self.world.intruder_bag.append(IntruderKind.ADULT)
            return [{"type": "bag_blank", "character_id": character.character_id, "room_id": room_id}]
        intruder = self.world.spawn_intruder(kind, room_id)
        events = [
            {
                "type": "encounter",
                "character_id": character.character_id,
                "intruder_id": intruder.intruder_id,
                "kind": kind.value,
                "room_id": room_id,
            }
        ]
        self.world.choose_objective_for_first_encounter(character, events)
        if kind is IntruderKind.LARVA:
            events.append({"type": "larva_contamination", "character_id": character.character_id})
            events.extend(self._add_contamination_card(character, infected=False))
        return events

    def _search(self, character: Character) -> list[dict[str, Any]]:
        room = self.world.rooms[character.room_id]
        if self.world.room_intruders(room.room_id):
            return [{"type": "search_blocked_by_intruder", "character_id": character.character_id, "room_id": room.room_id}]
        if room.search_items <= 0:
            return [{"type": "search_empty", "character_id": character.character_id, "room_id": room.room_id}]
        room.search_items -= 1
        item = f"{room.kind}_item_{room.search_items}"
        character.items.append(item)
        return [{"type": "item_found", "character_id": character.character_id, "room_id": room.room_id, "item": item}]

    def _rest(self, character: Character) -> list[dict[str, Any]]:
        if character.contamination_cards:
            return self._scan_contamination(character)
        if character.contamination:
            character.contamination -= 1
            return [{"type": "contamination_removed", "character_id": character.character_id}]
        if character.light_wounds:
            character.light_wounds -= 1
            return [{"type": "light_wound_healed", "character_id": character.character_id}]
        return [{"type": "rest", "character_id": character.character_id}]

    def _resolve_exploration_effect(self, character: Character, room_id: str) -> list[dict[str, Any]]:
        room = self.world.rooms[room_id]
        effect = room.exploration_effect
        if effect is None:
            return []
        room.exploration_effect = None
        if effect == "fire":
            return self.place_fire(room_id)
        if effect == "malfunction":
            return self.place_malfunction(room_id)
        if effect == "slime":
            character.slime = True
            return [{"type": "slimed", "character_id": character.character_id, "room_id": room_id}]
        if effect == "danger":
            return self._resolve_danger(character, room_id)
        if effect == "silence":
            return [{"type": "noise_silence", "character_id": character.character_id, "room_id": room_id}]
        return [{"type": "exploration_effect_unknown", "room_id": room_id, "effect": effect}]

    def _craft(self, character: Character, item: str) -> list[dict[str, Any]]:
        components = CRAFT_RECIPES.get(item)
        if components is None:
            return [{"type": "craft_failed", "character_id": character.character_id, "item": item, "reason": "unknown_recipe"}]
        missing = [component for component in components if component not in character.items]
        if missing:
            return [
                {
                    "type": "craft_failed",
                    "character_id": character.character_id,
                    "item": item,
                    "reason": "missing_components",
                    "missing": missing,
                }
            ]
        for component in components:
            character.items.remove(component)
        character.items.append(item)
        return [{"type": "crafted", "character_id": character.character_id, "item": item}]

    def _pay_action_cost(
        self,
        character: Character,
        action: str,
        *,
        discard_cards: Sequence[str] | None,
        require_discard_selection: bool,
    ) -> list[dict[str, Any]]:
        cost = self.action_cost(action)
        if cost <= 0:
            return []

        selected = list(discard_cards or [])
        if require_discard_selection and len(selected) != cost:
            raise ValueError(f"{action} requires {cost} discarded card{'s' if cost != 1 else ''}")
        if not selected:
            selected = [card["id"] for card in character.action_hand[:cost]]
        if len(selected) != cost:
            raise ValueError(f"{action} requires {cost} discarded card{'s' if cost != 1 else ''}")

        hand_by_id = {card["id"]: card for card in character.action_hand}
        missing = [card_id for card_id in selected if card_id not in hand_by_id]
        if missing:
            raise ValueError(f"cannot discard cards not in hand: {', '.join(missing)}")
        if len(set(selected)) != len(selected):
            raise ValueError("cannot discard the same card twice")

        selected_set = set(selected)
        discarded = [card for card in character.action_hand if card["id"] in selected_set]
        character.action_hand = [card for card in character.action_hand if card["id"] not in selected_set]
        character.action_discard.extend(discarded)
        return [
            {
                "type": "cards_discarded",
                "character_id": character.character_id,
                "action": action,
                "cost": cost,
                "cards": selected,
            }
        ]

    def _set_name(self, character: Character, raw_name: str) -> list[dict[str, Any]]:
        name = self._clean_character_name(raw_name)
        character.name = name or None
        return [{"type": "name_set", "character_id": character.character_id, "name": character.display_name()}]

    def _attack_intruder(self, character: Character, intruder_id: int | None, *, ranged: bool) -> list[dict[str, Any]]:
        if intruder_id is None:
            intruders = self.world.room_intruders(character.room_id)
            intruder = intruders[0] if intruders else None
        else:
            intruder = self.world.intruders.get(intruder_id)
        if intruder is None or intruder.room_id != character.room_id:
            return [{"type": "attack_failed", "character_id": character.character_id}]
        if ranged:
            if character.ammo <= 0:
                return [{"type": "shoot_no_ammo", "character_id": character.character_id, "intruder_id": intruder.intruder_id}]
            character.ammo -= 1
            damage = 2
            event_type = "shoot"
        else:
            damage = 1
            event_type = "melee"
        events = [
            {"type": event_type, "character_id": character.character_id, "intruder_id": intruder.intruder_id, "damage": damage},
        ]
        if not ranged:
            events.extend(self._suffer_light_wound(character))
        events.extend(self._damage_intruder(intruder, damage, "intruder_damage"))
        return events

    def _repair(self, character: Character, engine_id: str) -> list[dict[str, Any]]:
        if engine_id in {"", "room"} and character.room_id in self.world.malfunction_rooms:
            self.world.malfunction_rooms.remove(character.room_id)
            return [{"type": "malfunction_repaired", "character_id": character.character_id, "room_id": character.room_id}]
        engine = self.world.ship.engines.get(engine_id)
        if engine is None or engine.room_id != character.room_id:
            return [{"type": "repair_failed", "character_id": character.character_id, "engine_id": engine_id}]
        engine.working = True
        engine.checked = True
        return [{"type": "engine_repaired", "character_id": character.character_id, "engine_id": engine_id}]

    def _check_engine(self, character: Character, engine_id: str) -> list[dict[str, Any]]:
        engine = self.world.ship.engines.get(engine_id)
        if engine is None or engine.room_id != character.room_id:
            return [{"type": "engine_check_failed", "character_id": character.character_id, "engine_id": engine_id}]
        engine.checked = True
        return [
            {
                "type": "engine_checked",
                "character_id": character.character_id,
                "engine_id": engine_id,
                "working": engine.working,
            }
        ]

    def _damage_intruder(self, intruder: Intruder, damage: int, event_type: str) -> list[dict[str, Any]]:
        intruder.damage += damage
        events = [{"type": event_type, "intruder_id": intruder.intruder_id, "damage": damage, "total_damage": intruder.damage}]
        if intruder.damage >= intruder.health:
            self.world.killed_intruders.append(intruder.kind)
            del self.world.intruders[intruder.intruder_id]
            events.append({"type": "intruder_killed", "intruder_id": intruder.intruder_id, "kind": intruder.kind.value})
        return events

    def _send_signal(self, character: Character) -> list[dict[str, Any]]:
        if self.world.rooms[character.room_id].kind != "comms":
            return [{"type": "send_signal_failed", "character_id": character.character_id, "room_id": character.room_id}]
        character.signal_sent = True
        return [{"type": "signal_sent", "character_id": character.character_id}]

    def _set_destination(self, character: Character, destination: str) -> list[dict[str, Any]]:
        if self.world.rooms[character.room_id].kind != "cockpit" or destination not in {"earth", "mars", "deep_space"}:
            return [{"type": "set_destination_failed", "character_id": character.character_id, "destination": destination}]
        self.world.ship.destination = destination
        self.world.ship.coordinates_known = True
        return [{"type": "destination_set", "character_id": character.character_id, "destination": destination}]

    def _discover_weakness(self, character: Character) -> list[dict[str, Any]]:
        if self.world.rooms[character.room_id].kind != "laboratory":
            return [{"type": "discover_weakness_failed", "character_id": character.character_id}]
        self.world.discovered_weaknesses += 1
        return [{"type": "weakness_discovered", "character_id": character.character_id, "count": self.world.discovered_weaknesses}]

    def _destroy_egg(self, character: Character) -> list[dict[str, Any]]:
        if self.world.rooms[character.room_id].kind != "nest" or self.world.nest_eggs <= 0:
            return [{"type": "destroy_egg_failed", "character_id": character.character_id}]
        self.world.nest_eggs -= 1
        return [{"type": "egg_destroyed", "character_id": character.character_id, "remaining": self.world.nest_eggs}]

    def _hibernate(self, character: Character) -> list[dict[str, Any]]:
        if self.world.rooms[character.room_id].kind != "hibernatorium":
            return [{"type": "hibernate_failed", "character_id": character.character_id, "reason": "wrong_room"}]
        if self.world.ship.time_remaining > self.world.ship.hibernation_opens_at:
            return [{"type": "hibernate_failed", "character_id": character.character_id, "reason": "closed"}]
        if self.world.room_intruders(character.room_id):
            return [{"type": "hibernate_failed", "character_id": character.character_id, "reason": "intruder"}]
        character.status = CharacterStatus.HIBERNATED
        return [{"type": "hibernated", "character_id": character.character_id}]

    def _escape(self, character: Character, pod_id: str) -> list[dict[str, Any]]:
        pod = self.world.escape_pods.get(pod_id)
        if pod is None or pod.room_id != character.room_id:
            return [{"type": "escape_failed", "character_id": character.character_id, "pod_id": pod_id, "reason": "wrong_room"}]
        if not pod.unlocked:
            return [{"type": "escape_failed", "character_id": character.character_id, "pod_id": pod_id, "reason": "locked"}]
        if self.world.room_intruders(character.room_id):
            return [{"type": "escape_failed", "character_id": character.character_id, "pod_id": pod_id, "reason": "intruder"}]
        pod.occupants.append(character.character_id)
        pod.launched = True
        character.status = CharacterStatus.ESCAPED
        return [{"type": "escaped", "character_id": character.character_id, "pod_id": pod_id}]

    def _use_room(self, character: Character) -> list[dict[str, Any]]:
        kind = self.world.rooms[character.room_id].kind
        if kind == "comms":
            return self._send_signal(character)
        if kind == "cockpit":
            return self._set_destination(character, "earth")
        if kind == "laboratory":
            return self._discover_weakness(character)
        if kind == "nest":
            return self._destroy_egg(character)
        if kind == "surgery":
            character.contamination_cards = []
            character.contamination = 0
            character.larva = False
            events = [{"type": "surgery", "character_id": character.character_id}]
            events.extend(self._suffer_light_wound(character))
            return events
        if kind == "armory":
            character.ammo = min(MAX_AMMO, character.ammo + 2)
            return [{"type": "ammo_loaded", "character_id": character.character_id, "ammo": character.ammo}]
        if kind.startswith("engine"):
            return self._repair(character, kind)
        return [{"type": "room_action_none", "character_id": character.character_id, "room_id": character.room_id}]

    def _finish_if_no_active_characters(self, events: list[dict[str, Any]]) -> None:
        if self.world.phase is Phase.FINISHED:
            return
        if all(not character.active() for character in self.world.characters.values()):
            self.world.finish_game("no_active_characters")
            events.append({"type": "game_finished", "reason": "no_active_characters"})

    @staticmethod
    def _parse_action(action: str) -> tuple[str, list[str]]:
        parts = [part for part in action.split(":") if part != ""]
        if not parts:
            return "noop", []
        return parts[0], parts[1:]

    @staticmethod
    def _clean_character_name(raw_name: str) -> str:
        cleaned = " ".join(raw_name.strip().split())
        return cleaned[:32]
