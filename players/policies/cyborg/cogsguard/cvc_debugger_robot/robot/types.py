"""Shared constants and data types for the robot controller.

Pure definitions -- no logic, no external imports.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto

Coord = tuple[int, int]

# Cardinal movement deltas: action name -> (row_delta, col_delta)
MOVE_DELTAS: dict[str, Coord] = {
  "move_north": (-1, 0),
  "move_south": (1, 0),
  "move_west": (0, -1),
  "move_east": (0, 1),
}
MOVE_NAMES = tuple(MOVE_DELTAS.keys())
CARDINAL_DELTAS = ((-1, 0), (1, 0), (0, -1), (0, 1))

ELEMENTS = ("carbon", "oxygen", "germanium", "silicon")
GEAR_TYPES = ("miner", "aligner", "scrambler", "scout")

TEAM_TAG_PREFIX = "team:"
NET_TAG_PREFIX = "net:"

STALE_THRESHOLD = 200

HUB_ALIGN_RADIUS = 25
JUNCTION_NETWORK_ALIGN_RADIUS = 15


class MacroKind(Enum):
  NAVIGATE_TO = auto()
  EXPLORE = auto()
  FLEE = auto()
  IDLE = auto()


class NavStatus(Enum):
  IDLE = auto()
  NAVIGATING = auto()
  ARRIVED = auto()
  STUCK = auto()
  UNREACHABLE = auto()


@dataclass(frozen=True)
class MacroCommand:
  kind: MacroKind
  target: Coord | None = None
  params: dict = field(default_factory=dict)
  reason: str = ""


@dataclass
class NavState:
  status: NavStatus = NavStatus.IDLE
  target: Coord | None = None
  path: list[Coord] = field(default_factory=list)
  distance_remaining: int = 0
  ticks_active: int = 0


def coord_add(a: Coord, b: Coord) -> Coord:
  return (a[0] + b[0], a[1] + b[1])


def manhattan(a: Coord, b: Coord) -> int:
  return abs(a[0] - b[0]) + abs(a[1] - b[1])
