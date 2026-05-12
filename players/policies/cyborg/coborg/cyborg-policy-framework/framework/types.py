"""Generic types for the policy framework.

Game-agnostic definitions used across the framework. Games extend
these with their own domain-specific types.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any


Coord = tuple[int, int]


class CommandKind(Enum):
  NAVIGATE_TO = auto()
  EXPLORE = auto()
  FLEE = auto()
  IDLE = auto()
  CUSTOM = auto()


@dataclass(frozen=True)
class Command:
  """Generic action output from the brain to the executor."""
  kind: CommandKind
  target: Coord | None = None
  params: dict[str, Any] = field(default_factory=dict)
  reason: str = ""


@dataclass
class Directive:
  """LLM strategic override — parsed from LLM response, applied to brain."""
  role: str = ""
  command: str | None = None
  target: Coord | None = None
  reasoning: str = ""
  params: dict[str, Any] = field(default_factory=dict)
  hold: bool = False
  until: str | None = None
  issued_tick: int = 0
  expires_tick: int = 0

  def to_dict(self) -> dict:
    d: dict[str, Any] = {
      "role": self.role,
      "reasoning": self.reasoning,
      "issued_tick": self.issued_tick,
      "expires_tick": self.expires_tick,
    }
    if self.command:
      d["command"] = self.command
    if self.target:
      d["target"] = list(self.target)
    if self.params:
      d["params"] = self.params
    if self.hold:
      d["hold"] = True
    if self.until:
      d["until"] = self.until
    return d


@dataclass
class GameConfig:
  """Game metadata passed to brain.prepare() and used throughout the pipeline."""
  game_name: str = ""
  game_id: str = ""
  max_steps: int = 10000
  seed: int = 0
  mission: str = ""
  run_dir: str = ""
  extras: dict[str, Any] = field(default_factory=dict)


def coord_add(a: Coord, b: Coord) -> Coord:
  return (a[0] + b[0], a[1] + b[1])


def manhattan(a: Coord, b: Coord) -> int:
  return abs(a[0] - b[0]) + abs(a[1] - b[1])
