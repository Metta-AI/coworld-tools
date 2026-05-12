"""Constants and data types used across helper modules."""

from __future__ import annotations

from dataclasses import dataclass

_MOVE_DELTAS = {
    "north": (0, -1),
    "south": (0, 1),
    "east": (1, 0),
    "west": (-1, 0),
}

_ALIGNER_EXPLORE_OFFSETS = (
    (0, -22),
    (16, -16),
    (22, 0),
    (16, 16),
    (0, 22),
    (-16, 16),
    (-22, 0),
    (-16, -16),
)
_MINER_EXPLORE_OFFSETS = ((-28, -28), (28, -28), (-28, 28), (28, 28))
_SCRAMBLER_EXPLORE_OFFSETS = ((36, -36), (36, 36), (-36, 36), (-36, -36))

_ELEMENTS = ("carbon", "oxygen", "germanium", "silicon")
_HP_THRESHOLDS = {
    "miner": 15,
    "aligner": 50,
    "scrambler": 30,
    "scout": 30,
    "unknown": 30,
}
_GEAR_COSTS = {
    "miner": {"carbon": 1, "oxygen": 1, "germanium": 3, "silicon": 1},
    "aligner": {"carbon": 3, "oxygen": 1, "germanium": 1, "silicon": 1},
    "scrambler": {"carbon": 1, "oxygen": 3, "germanium": 1, "silicon": 1},
    "scout": {"carbon": 1, "oxygen": 1, "germanium": 1, "silicon": 3},
}
_EMERGENCY_RESOURCE_LOW = 1
_HEART_BATCH_TARGETS = {"aligner": 3, "scrambler": 2}
_HUB_ALIGN_DISTANCE = 25
_JUNCTION_ALIGN_DISTANCE = 15
_JUNCTION_AOE_RANGE = 10
_CLAIMED_TARGET_PENALTY = 12.0
_TARGET_CLAIM_STEPS = 30
_EXTRACTOR_MEMORY_STEPS = 800
_STATION_TARGETS_BY_AGENT = {
    "aligner": {
        0: (-3, 7),
        1: (-3, 6),
        2: (0, 4),
        3: (-1, 4),
        4: (-5, 4),
        5: (-6, 4),
        6: (-3, 2),
        7: (-3, 1),
    },
    "scrambler": {
        0: (-1, 7),
        1: (-1, 6),
        2: (2, 4),
        3: (1, 4),
        4: (-3, 4),
        5: (-4, 4),
        6: (-1, 2),
        7: (-1, 1),
    },
    "miner": {
        0: (1, 7),
        1: (1, 6),
        2: (4, 4),
        3: (3, 4),
        4: (-1, 4),
        5: (-2, 4),
        6: (1, 2),
        7: (1, 1),
    },
}


@dataclass(slots=True)
class KnownEntity:
    entity_type: str
    global_x: int
    global_y: int
    labels: tuple[str, ...]
    team: str | None
    owner: str | None
    last_seen_step: int
    attributes: dict[str, str | int | float | bool]

    @property
    def position(self) -> tuple[int, int]:
        return (self.global_x, self.global_y)
