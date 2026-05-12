"""Priority-based event detection framework.

Games subclass BaseEventDetector and implement detect_game_events()
to define their own events. The framework handles debounce, priority
selection, periodic triggers, and idle detection.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from .base_memory import GameMemory, GameEvent


TRIGGER_PERIODIC = "periodic"
TRIGGER_IDLE = "idle_detected"

BASE_TRIGGER_PRIORITY = {
  TRIGGER_PERIODIC: 10,
  TRIGGER_IDLE: 20,
}

DEBOUNCE_TICKS = 0


@dataclass
class TriggerResult:
  trigger: str | None = None
  events: list[GameEvent] = field(default_factory=list)

  @property
  def should_consult(self) -> bool:
    return self.trigger is not None


class BaseEventDetector(ABC):
  """Detects game events by diffing consecutive snapshot dicts.

  Subclasses implement detect_game_events() to return game-specific
  events and trigger names. The base class handles debounce, idle
  detection, periodic triggers, and priority selection.
  """

  def __init__(self, consult_interval: int = 200, idle_threshold: int = 30):
    self._prev: dict | None = None
    self._consult_interval = consult_interval
    self._last_consult_tick = -consult_interval
    self._debounce: dict[str, int] = {}
    self._idle_ticks = 0
    self._idle_threshold = idle_threshold
    self._prev_cmd_reason: str | None = None

  @abstractmethod
  def detect_game_events(
    self, prev: dict, curr: dict, memory: GameMemory
  ) -> list[tuple[str, GameEvent]]:
    """Return (trigger_name, event) pairs for game-specific events.

    Called every tick with the previous and current snapshot dicts.
    Each pair is a trigger name and the event recorded in memory.
    """
    ...

  def get_trigger_priorities(self) -> dict[str, int]:
    """Override to provide game-specific trigger priorities.

    Higher numbers = higher priority = fires first.
    Base priorities: periodic=10, idle=20.
    """
    return {}

  def evaluate(self, snap: dict, memory: GameMemory) -> TriggerResult:
    tick = snap.get("tick", 0)
    prev = self._prev
    self._prev = snap

    events: list[GameEvent] = []
    triggers: list[str] = []

    if prev is None:
      return TriggerResult()

    game_results = self.detect_game_events(prev, snap, memory)
    for trigger_name, event in game_results:
      events.append(event)
      triggers.append(trigger_name)

    cmd_reason = snap.get("active_command", "")
    if cmd_reason == self._prev_cmd_reason:
      self._idle_ticks += 1
    else:
      self._idle_ticks = 0
    self._prev_cmd_reason = cmd_reason
    if self._idle_ticks >= self._idle_threshold:
      triggers.append(TRIGGER_IDLE)
      self._idle_ticks = 0

    if tick - self._last_consult_tick >= self._consult_interval:
      triggers.append(TRIGGER_PERIODIC)

    best_trigger = self._pick_trigger(triggers, tick)
    result = TriggerResult(trigger=best_trigger, events=events)

    if best_trigger:
      self._last_consult_tick = tick
      self._debounce[best_trigger] = tick

    return result

  def _pick_trigger(self, triggers: list[str], tick: int) -> str | None:
    if not triggers:
      return None

    active = []
    for t in triggers:
      if t == TRIGGER_PERIODIC:
        active.append(t)
        continue
      last = self._debounce.get(t, -DEBOUNCE_TICKS)
      if tick - last >= DEBOUNCE_TICKS:
        active.append(t)

    if not active:
      return None

    priorities = {**BASE_TRIGGER_PRIORITY, **self.get_trigger_priorities()}
    return max(active, key=lambda t: priorities.get(t, 0))

  def mark_consulted(self, tick: int) -> None:
    self._last_consult_tick = tick
