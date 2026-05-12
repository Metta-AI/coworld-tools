"""Telemetry ring-buffer -- records every tick for debugging and LLM context."""

from __future__ import annotations

import json
from collections import deque

from agent_policies.policies.cyborg.cogsguard.cvc_debugger_robot.robot.state import WorldSnapshot


class BlackBox:
  """Ring-buffer recorder. Stores snapshot + action for each tick."""

  def __init__(self, max_records: int = 5000):
    self._buffer: deque[dict] = deque(maxlen=max_records)

  def record(self, snapshot: WorldSnapshot, action: str) -> None:
    entry = snapshot.to_dict()
    entry["action"] = action
    self._buffer.append(entry)

  def last_n(self, n: int = 20) -> list[dict]:
    items = list(self._buffer)
    return items[-n:]

  def dump_json(self, path: str) -> None:
    with open(path, "w") as f:
      json.dump(list(self._buffer), f, indent=2, default=str)

  def summary(self) -> str:
    """Condensed game narrative for LLM consumption."""
    if not self._buffer:
      return "No ticks recorded yet."

    first = self._buffer[0]
    last = self._buffer[-1]
    total = len(self._buffer)

    lines = [
      f"Game log: {total} ticks recorded.",
      f"Started at tick {first.get('tick', '?')}, now at tick {last.get('tick', '?')}.",
      f"Current: pos {last.get('position')}, gear {last.get('gear')}, "
      f"HP {last.get('hp')}, energy {last.get('energy')}.",
      f"Threat: {last.get('threat_level', 'unknown')}.",
    ]

    # Action frequency summary
    actions: dict[str, int] = {}
    for entry in self._buffer:
      a = entry.get("action", "?")
      actions[a] = actions.get(a, 0) + 1
    top = sorted(actions.items(), key=lambda x: -x[1])[:5]
    action_str = ", ".join(f"{a}: {c}" for a, c in top)
    lines.append(f"Top actions: {action_str}")

    # Recent commands
    recent = list(self._buffer)[-5:]
    cmds = [e.get("active_command", "?") for e in recent]
    lines.append(f"Recent commands: {cmds}")

    return "\n".join(lines)

  def reset(self) -> None:
    self._buffer.clear()
