"""intents.py — per-agent intent advertisements for team rebalancing.

Origin: extracted from Ron Dahlgren's (swgy) agent libraries (sm-policies
``mas_memory.AgentIntent``/``IntentBoard``, near-verbatim; the
hub-relative field is renamed to the neutral "shared frame" vocabulary of
``worldmodel.frames``).

Agents publish their current ``(role, goal_type, target)``; teammates query
the board to decide whether to rebalance (e.g. switch roles when one goal is
over-subscribed). Stale intents — no update for ``stale_after`` ticks — are
pruned on read, so a crashed or stuck agent's ghost goal eventually clears.
"""

from __future__ import annotations

from dataclasses import dataclass

Coordinate = tuple[int, int]

__all__ = ["AgentIntent", "IntentBoard"]


@dataclass
class AgentIntent:
    """Self-reported summary of what an agent is doing.

    ``goal_type`` is caller vocabulary — e.g. "mine", "deposit", "capture",
    "scout", "idle".
    """

    agent_id: int
    role: str
    goal_type: str
    target_shared: Coordinate | None
    last_updated_tick: int


class IntentBoard:
    """Per-agent intent advertisements with staleness pruning on read."""

    def __init__(self, stale_after: int = 60) -> None:
        self._intents: dict[int, AgentIntent] = {}
        self._stale_after = stale_after

    def publish(self, intent: AgentIntent) -> None:
        self._intents[intent.agent_id] = intent

    def get(self, agent_id: int) -> AgentIntent | None:
        return self._intents.get(agent_id)

    def fresh(self, current_tick: int) -> list[AgentIntent]:
        cutoff = current_tick - self._stale_after
        return [i for i in self._intents.values() if i.last_updated_tick >= cutoff]

    def role_counts(self, current_tick: int) -> dict[str, int]:
        counts: dict[str, int] = {}
        for intent in self.fresh(current_tick):
            counts[intent.role] = counts.get(intent.role, 0) + 1
        return counts

    def agents_with_goal(
        self, goal_type: str, current_tick: int, exclude: int | None = None
    ) -> list[AgentIntent]:
        return [
            i
            for i in self.fresh(current_tick)
            if i.goal_type == goal_type and i.agent_id != exclude
        ]

    def clear(self) -> None:
        self._intents.clear()
