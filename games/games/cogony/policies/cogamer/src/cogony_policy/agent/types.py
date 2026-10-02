"""Constants and data types used across helper modules."""

from __future__ import annotations

from dataclasses import dataclass

from cogames.policy.starter_agent import ELEMENTS
from cogames.sdk.cogsguard import (
    COGSGUARD_GEAR_COSTS as GEAR_COSTS,
    COGSGUARD_HUB_ALIGN_DISTANCE as HUB_ALIGN_DISTANCE,
    COGSGUARD_JUNCTION_ALIGN_DISTANCE as JUNCTION_ALIGN_DISTANCE,
    COGSGUARD_JUNCTION_AOE_RANGE as JUNCTION_AOE_RANGE,
    COGSGUARD_ROLE_HP_THRESHOLDS as HP_THRESHOLDS,
)

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

_EMERGENCY_RESOURCE_LOW = 1
_HEART_BATCH_TARGETS = {"aligner": 3, "scrambler": 2}
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
