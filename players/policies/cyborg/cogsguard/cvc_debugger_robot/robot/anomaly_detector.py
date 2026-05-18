"""Live anomaly detector for the tick stream.

Monitors per-agent tick data and flags behavioral anomalies:
- Stuck agents (same position for N+ ticks)
- Death spirals (dying repeatedly in a short window)
- Wasted hearts (carrying heart with no junction target)
- Resource starvation (no deposits despite miners alive)
- Position oscillation (flip-flopping between positions)
- Gearless agents (acting without proper gear)

Each anomaly is broadcast through the ObservabilityHub as a structured event.
"""

from __future__ import annotations

from collections import defaultdict, deque
from typing import TYPE_CHECKING

if TYPE_CHECKING:
  from policies.cyborg.cogsguard.cvc_debugger_robot.robot.observability import ObservabilityHub


class AnomalyDetector:
  """Stateful anomaly detector that processes tick payloads."""

  def __init__(self, hub: ObservabilityHub):
    self.hub = hub
    self.enabled = False

    self._positions: dict[int, deque[tuple[int, int]]] = defaultdict(lambda: deque(maxlen=20))
    self._deaths: dict[int, deque[int]] = defaultdict(lambda: deque(maxlen=10))
    self._last_deposit_tick: dict[int, int] = defaultdict(int)
    self._gearless_ticks: dict[int, int] = defaultdict(int)
    self._last_hp: dict[int, int] = defaultdict(lambda: 100)
    self._emitted: set[str] = set()
    self._cooldowns: dict[str, int] = {}

  def set_enabled(self, enabled: bool) -> None:
    self.enabled = enabled
    if not enabled:
      self._emitted.clear()
      self._cooldowns.clear()

  def reset(self) -> None:
    self._positions.clear()
    self._deaths.clear()
    self._last_deposit_tick.clear()
    self._gearless_ticks.clear()
    self._last_hp.clear()
    self._emitted.clear()
    self._cooldowns.clear()

  def process_tick(self, payload: dict) -> None:
    """Process a single tick payload and emit anomalies if detected."""
    if not self.enabled:
      return

    agent_id = payload.get("agent_id")
    tick = payload.get("tick", 0)
    if agent_id is None:
      return

    self._check_stuck(agent_id, tick, payload)
    self._check_death_spiral(agent_id, tick, payload)
    self._check_wasted_heart(agent_id, tick, payload)
    self._check_resource_starvation(agent_id, tick, payload)
    self._check_oscillation(agent_id, tick, payload)
    self._check_gearless(agent_id, tick, payload)

  def _emit(self, agent_id: int, tick: int, category: str, description: str, severity: str = "warning") -> None:
    key = f"{agent_id}:{category}"
    cooldown = self._cooldowns.get(key, 0)
    if tick < cooldown:
      return
    self._cooldowns[key] = tick + 50

    event = {
      "type": "anomaly",
      "tick": tick,
      "agent_id": agent_id,
      "category": category,
      "description": description,
      "severity": severity,
    }
    self.hub._broadcast(event)

  def _check_stuck(self, agent_id: int, tick: int, payload: dict) -> None:
    pos = payload.get("position")
    if not pos:
      return
    pos_tuple = (pos[0], pos[1])
    history = self._positions[agent_id]
    history.append(pos_tuple)

    if len(history) < 15:
      return

    recent = list(history)[-15:]
    if all(p == recent[0] for p in recent):
      self._emit(
        agent_id, tick, "stuck",
        f"Agent {agent_id} stuck at ({pos[0]}, {pos[1]}) for 15+ ticks",
        "warning",
      )

    brain = payload.get("brain", {})
    congestion = brain.get("congestion_ticks", 0)
    if congestion >= 14:
      self._emit(
        agent_id, tick, "stuck",
        f"Agent {agent_id} congestion at max ({congestion}/15)",
        "critical",
      )

  def _check_death_spiral(self, agent_id: int, tick: int, payload: dict) -> None:
    hp = payload.get("hp", 100)
    prev_hp = self._last_hp[agent_id]
    self._last_hp[agent_id] = hp

    if hp <= 0 and prev_hp > 0:
      deaths = self._deaths[agent_id]
      deaths.append(tick)

      recent_deaths = [t for t in deaths if tick - t <= 200]
      if len(recent_deaths) >= 3:
        self._emit(
          agent_id, tick, "death_spiral",
          f"Agent {agent_id} died {len(recent_deaths)} times in last 200 ticks",
          "critical",
        )

  def _check_wasted_heart(self, agent_id: int, tick: int, payload: dict) -> None:
    has_heart = payload.get("has_heart", False)
    role = payload.get("role")
    nav_status = payload.get("nav_status", "")
    brain = payload.get("brain", {})

    if not has_heart:
      return

    if role in ("aligner", "scrambler") and nav_status in ("STUCK", "UNREACHABLE"):
      self._emit(
        agent_id, tick, "wasted_heart",
        f"Agent {agent_id} ({role}) carrying heart but nav is {nav_status}",
        "warning",
      )

  def _check_resource_starvation(self, agent_id: int, tick: int, payload: dict) -> None:
    role = payload.get("role")
    brain = payload.get("brain", {})
    deposit_count = brain.get("deposit_count", 0)

    if role == "miner" and deposit_count > 0:
      self._last_deposit_tick[agent_id] = tick

    if role == "miner":
      last_deposit = self._last_deposit_tick.get(agent_id, 0)
      if tick - last_deposit > 100 and tick > 100:
        self._emit(
          agent_id, tick, "resource_starvation",
          f"Agent {agent_id} (miner) no deposits for {tick - last_deposit} ticks",
          "warning",
        )

  def _check_oscillation(self, agent_id: int, tick: int, payload: dict) -> None:
    pos = payload.get("position")
    if not pos:
      return

    history = self._positions[agent_id]
    if len(history) < 10:
      return

    recent = list(history)[-10:]
    pos_counts: dict[tuple[int, int], int] = {}
    for p in recent:
      pos_counts[p] = pos_counts.get(p, 0) + 1

    max_revisits = max(pos_counts.values()) if pos_counts else 0
    if max_revisits >= 5:
      hot_pos = max(pos_counts, key=lambda k: pos_counts[k])
      self._emit(
        agent_id, tick, "oscillation",
        f"Agent {agent_id} oscillating — visited ({hot_pos[0]}, {hot_pos[1]}) {max_revisits}x in 10 ticks",
        "warning",
      )

  def _check_gearless(self, agent_id: int, tick: int, payload: dict) -> None:
    gear = payload.get("gear")
    role = payload.get("role")

    if role and not gear:
      self._gearless_ticks[agent_id] = self._gearless_ticks.get(agent_id, 0) + 1
    else:
      self._gearless_ticks[agent_id] = 0

    if self._gearless_ticks[agent_id] >= 20:
      self._emit(
        agent_id, tick, "gearless",
        f"Agent {agent_id} ({role}) has no gear for {self._gearless_ticks[agent_id]}+ ticks",
        "warning",
      )
