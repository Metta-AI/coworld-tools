"""Mission defaults and ship construction for Cogisis."""

from __future__ import annotations

from dataclasses import dataclass
from random import Random

from cogisis.engine import (
    Character,
    EngineStatus,
    EscapePod,
    IntruderKind,
    Objective,
    ObjectiveKind,
    Room,
    ShipStatus,
    World,
)

ROLES = ["captain", "pilot", "scientist", "scout", "soldier"]


@dataclass(frozen=True)
class CogisisMission:
    name: str = "cogisis"
    description: str = "A Nemesis-style semi-cooperative survival cogame on an infested ship."
    num_cogs: int = 4
    max_steps: int = 15
    seed: int = 42

    def with_cogs(self, cogs: int) -> CogisisMission:
        if cogs < 1 or cogs > len(ROLES):
            raise ValueError(f"Cogisis supports 1-{len(ROLES)} cogs.")
        return CogisisMission(
            name=self.name,
            description=self.description,
            num_cogs=cogs,
            max_steps=self.max_steps,
            seed=self.seed,
        )

    def build_world(self) -> World:
        rng = Random(self.seed)
        rooms = self._build_rooms()
        engines = {
            engine_id: EngineStatus(engine_id=engine_id, room_id=engine_id, working=rng.choice([True, True, False]))
            for engine_id in ("engine_1", "engine_2", "engine_3")
        }
        ship = ShipStatus(
            destination=rng.choice(["earth", "mars", "deep_space"]),
            engines=engines,
            time_remaining=self.max_steps,
            hibernation_opens_at=max(1, self.max_steps // 2),
        )
        characters = {
            character_id: Character(
                character_id=character_id,
                role=ROLES[character_id],
                room_id="hibernatorium",
                objectives=self._objectives_for(character_id),
            )
            for character_id in range(self.num_cogs)
        }
        for character in characters.values():
            character.setup_action_deck(rng)
        return World(
            rooms=rooms,
            characters=characters,
            intruder_bag=[
                IntruderKind.BLANK,
                IntruderKind.LARVA,
                IntruderKind.LARVA,
                IntruderKind.LARVA,
                IntruderKind.LARVA,
                IntruderKind.CREEPER,
                IntruderKind.QUEEN,
                IntruderKind.ADULT,
                IntruderKind.ADULT,
                IntruderKind.ADULT,
                *[IntruderKind.ADULT for _ in range(self.num_cogs)],
            ],
            ship=ship,
            escape_pods={
                "pod_a": EscapePod("pod_a", "escape_a"),
                "pod_b": EscapePod("pod_b", "escape_b"),
            },
            max_steps=self.max_steps,
            rng=rng,
        )

    def _objectives_for(self, character_id: int) -> list[Objective]:
        personal = [
            Objective(ObjectiveKind.SEND_SIGNAL),
            Objective(ObjectiveKind.DISCOVER_WEAKNESS),
            Objective(ObjectiveKind.DESTROY_NEST),
            Objective(ObjectiveKind.SURVIVE_AND_EARTH),
            Objective(ObjectiveKind.SURVIVE_AND_MARS),
        ]
        corporate = [
            Objective(ObjectiveKind.KILL_QUEEN),
            Objective(ObjectiveKind.ONLY_SURVIVOR),
            Objective(ObjectiveKind.SURVIVE_AND_EARTH),
            Objective(ObjectiveKind.SEND_SIGNAL),
            Objective(ObjectiveKind.DISCOVER_WEAKNESS),
        ]
        return [personal[character_id % len(personal)], corporate[character_id % len(corporate)]]

    def _build_rooms(self) -> dict[str, Room]:
        rooms = {
            "hibernatorium": Room("hibernatorium", "Hibernatorium", "hibernatorium"),
            "atrium": Room("atrium", "Central Atrium", "corridor", explored=False, search_items=1),
            "cockpit": Room("cockpit", "Cockpit", "cockpit", explored=False),
            "comms": Room("comms", "Comms Room", "comms", explored=False, search_items=1),
            "laboratory": Room("laboratory", "Laboratory", "laboratory", explored=False, search_items=1),
            "surgery": Room("surgery", "Surgery", "surgery", explored=False, search_items=1),
            "armory": Room("armory", "Armory", "armory", explored=False, search_items=2),
            "storage": Room("storage", "Storage", "storage", explored=False, search_items=3),
            "nest": Room("nest", "Nest", "nest", explored=False),
            "escape_a": Room("escape_a", "Escape Pod A", "escape_pod", explored=False),
            "escape_b": Room("escape_b", "Escape Pod B", "escape_pod", explored=False),
            "engine_1": Room("engine_1", "Engine 1", "engine_1", explored=False),
            "engine_2": Room("engine_2", "Engine 2", "engine_2", explored=False),
            "engine_3": Room("engine_3", "Engine 3", "engine_3", explored=False),
        }
        self._connect(rooms, "hibernatorium", 1, "atrium", 1)
        self._connect(rooms, "hibernatorium", 2, "engine_1", 1)
        self._connect(rooms, "hibernatorium", 3, "escape_a", 1)
        self._connect(rooms, "atrium", 2, "cockpit", 1)
        self._connect(rooms, "atrium", 3, "comms", 1)
        self._connect(rooms, "atrium", 4, "laboratory", 1)
        self._connect(rooms, "atrium", 5, "nest", 1)
        self._connect(rooms, "cockpit", 2, "engine_2", 1)
        self._connect(rooms, "comms", 2, "storage", 1)
        self._connect(rooms, "laboratory", 2, "surgery", 1)
        self._connect(rooms, "surgery", 2, "armory", 1)
        self._connect(rooms, "armory", 2, "engine_2", 2)
        self._connect(rooms, "storage", 2, "engine_1", 2)
        self._connect(rooms, "nest", 2, "engine_3", 1)
        self._connect(rooms, "nest", 3, "escape_b", 1)
        return rooms

    @staticmethod
    def _connect(rooms: dict[str, Room], left: str, left_corridor: int, right: str, right_corridor: int) -> None:
        rooms[left].exits[left_corridor] = right
        rooms[right].exits[right_corridor] = left
