"""Three-tier game memory — game-agnostic base.

Tier 1: Working Memory — volatile, replaced every tick (current snapshot + directive)
Tier 2: Episodic Memory — ring buffer of game events, categorized by hall
Tier 3: Strategic Memory — learned facts with temporal supersession

Games define their own hall and category constants; the framework
provides the data structures and serialization.
"""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, field
from typing import Optional


MAX_EVENTS = 500


@dataclass
class GameEvent:
  tick: int
  hall: str
  text: str
  landmark: bool = False
  data: dict = field(default_factory=dict)

  def to_dict(self) -> dict:
    d = {"tick": self.tick, "hall": self.hall, "text": self.text}
    if self.landmark:
      d["landmark"] = True
    if self.data:
      d["data"] = self.data
    return d


class EpisodicMemory:
  """Append-only ring buffer of game events with landmark protection."""

  def __init__(self, max_events: int = MAX_EVENTS):
    self._events: deque[GameEvent] = deque()
    self._max_events = max_events
    self._landmark_count = 0

  def record(self, tick: int, hall: str, text: str,
             landmark: bool = False, data: dict | None = None) -> GameEvent:
    ev = GameEvent(tick=tick, hall=hall, text=text, landmark=landmark, data=data or {})
    self._events.append(ev)
    if landmark:
      self._landmark_count += 1
    self._evict()
    return ev

  def _evict(self) -> None:
    while len(self._events) > self._max_events:
      for i, ev in enumerate(self._events):
        if not ev.landmark:
          del self._events[i]  # type: ignore[arg-type]
          return
      oldest = self._events.popleft()
      self._landmark_count -= 1 if oldest.landmark else 0
      return

  def recent(self, n: int = 10, hall: str | None = None) -> list[GameEvent]:
    if hall is None:
      return list(self._events)[-n:]
    filtered = [e for e in self._events if e.hall == hall]
    return filtered[-n:]

  def all_events(self) -> list[GameEvent]:
    return list(self._events)

  def count(self) -> int:
    return len(self._events)

  def dump(self) -> list[dict]:
    return [e.to_dict() for e in self._events]


@dataclass
class MemoryFact:
  key: str
  fact: str
  category: str
  tick_created: int
  tick_expires: int | None = None
  superseded_by: str | None = None

  @property
  def is_current(self) -> bool:
    return self.superseded_by is None

  def to_dict(self) -> dict:
    d = {
      "key": self.key,
      "fact": self.fact,
      "category": self.category,
      "tick_created": self.tick_created,
    }
    if self.tick_expires is not None:
      d["tick_expires"] = self.tick_expires
    if self.superseded_by is not None:
      d["superseded_by"] = self.superseded_by
    return d


class StrategicMemory:
  """Key-value fact store with temporal supersession."""

  def __init__(self):
    self._facts: dict[str, MemoryFact] = {}
    self._history: list[MemoryFact] = []

  def set_fact(self, key: str, fact: str, category: str, tick: int,
               expires: int | None = None) -> MemoryFact:
    old = self._facts.get(key)
    if old and old.is_current:
      old.superseded_by = fact
      self._history.append(old)

    entry = MemoryFact(
      key=key, fact=fact, category=category,
      tick_created=tick, tick_expires=expires,
    )
    self._facts[key] = entry
    return entry

  def get_fact(self, key: str) -> MemoryFact | None:
    return self._facts.get(key)

  def current_facts(self, category: str | None = None, tick: int | None = None) -> list[MemoryFact]:
    results = []
    for f in self._facts.values():
      if not f.is_current:
        continue
      if tick is not None and f.tick_expires is not None and tick > f.tick_expires:
        continue
      if category is not None and f.category != category:
        continue
      results.append(f)
    return results

  def count(self, category: str | None = None) -> int:
    return len(self.current_facts(category=category))

  def dump(self) -> dict:
    return {
      "current": [f.to_dict() for f in self._facts.values() if f.is_current],
      "superseded": [f.to_dict() for f in self._history],
    }


@dataclass
class PerfWindow:
  """Tracks a rate metric over rolling windows."""
  window_size: int = 100
  _samples: list[tuple[int, float]] = field(default_factory=list)
  _peak_rate: float = 0.0
  _peak_tick: int = 0

  def record(self, tick: int, value: float) -> None:
    self._samples.append((tick, value))
    cutoff = tick - self.window_size
    while self._samples and self._samples[0][0] < cutoff:
      self._samples.pop(0)

  def current_rate(self) -> float:
    if len(self._samples) < 2:
      return 0.0
    first_tick, first_val = self._samples[0]
    last_tick, last_val = self._samples[-1]
    dt = last_tick - first_tick
    if dt <= 0:
      return 0.0
    rate = (last_val - first_val) / dt
    if rate > self._peak_rate:
      self._peak_rate = rate
      self._peak_tick = last_tick
    return rate

  def peak(self) -> tuple[float, int]:
    return self._peak_rate, self._peak_tick

  def dump(self) -> dict:
    return {
      "current_rate": round(self.current_rate(), 4),
      "peak_rate": round(self._peak_rate, 4),
      "peak_tick": self._peak_tick,
      "samples": len(self._samples),
    }


@dataclass
class WorkingMemory:
  snapshot_dict: dict = field(default_factory=dict)
  active_directive: dict | None = None
  recent_commands: list[str] = field(default_factory=list)
  nav_target: Optional[tuple[int, int]] = None
  nav_eta: int = 0

  def update_from_snapshot(self, snapshot_dict: dict, directive_dict: dict | None = None,
                           commands: list[str] | None = None) -> None:
    self.snapshot_dict = snapshot_dict
    self.active_directive = directive_dict
    if commands is not None:
      self.recent_commands = commands[-5:]
    self.nav_target = snapshot_dict.get("nav_target")
    self.nav_eta = snapshot_dict.get("nav_distance", 0)

  def dump(self) -> dict:
    return {
      "snapshot": self.snapshot_dict,
      "active_directive": self.active_directive,
      "recent_commands": self.recent_commands,
      "nav_target": list(self.nav_target) if self.nav_target else None,
      "nav_eta": self.nav_eta,
    }


class GameMemory:
  """Top-level memory container holding all three tiers + performance windows.

  Games can add custom PerfWindow instances via add_perf_window().
  """

  def __init__(self, game_id: str = "", max_steps: int = 10000,
               model: str = "scripted", seed: int = 0, mission: str = "",
               game_name: str = ""):
    self.game_id = game_id
    self.game_name = game_name
    self.max_steps = max_steps
    self.model = model
    self.seed = seed
    self.mission = mission
    self.start_time = time.time()

    self.working = WorkingMemory()
    self.episodic = EpisodicMemory()
    self.strategic = StrategicMemory()

    self._perf_windows: dict[str, PerfWindow] = {}
    self._directive_history: list[dict] = []
    self._dumped = False

  def add_perf_window(self, name: str, window_size: int = 100) -> PerfWindow:
    pw = PerfWindow(window_size=window_size)
    self._perf_windows[name] = pw
    return pw

  def get_perf_window(self, name: str) -> PerfWindow | None:
    return self._perf_windows.get(name)

  def record_directive(self, directive_dict: dict, tick: int) -> None:
    entry = {"tick": tick, **directive_dict}
    self._directive_history.append(entry)

  def dump(self, trigger: str = "game_end", final_tick: int = 0,
           llm_call_log: list[dict] | None = None,
           total_llm_calls: int = 0, total_tokens: int = 0) -> dict:
    self._dumped = True
    return {
      "meta": {
        "game_name": self.game_name,
        "game_id": self.game_id,
        "seed": self.seed,
        "mission": self.mission,
        "max_steps": self.max_steps,
        "model": self.model,
        "total_llm_calls": total_llm_calls,
        "total_tokens": total_tokens,
        "final_tick": final_tick,
        "dump_trigger": trigger,
        "elapsed_s": round(time.time() - self.start_time, 1),
      },
      "working_memory": self.working.dump(),
      "episodic_memory": self.episodic.dump(),
      "strategic_memory": self.strategic.dump(),
      "llm_call_log": llm_call_log or [],
      "directive_history": self._directive_history,
      "performance_windows": {
        name: pw.dump() for name, pw in self._perf_windows.items()
      },
    }

  @property
  def was_dumped(self) -> bool:
    return self._dumped
