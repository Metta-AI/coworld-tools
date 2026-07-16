"""census.py — who on the team is (probably) still alive, by role.

Origin: extracted from Ron Dahlgren's (swgy) agent libraries (the roster /
liveness subset of sm-policies ``dedicated_runtime.TeamLedger`` +
``SharedRuntime.report_alive``/``alive_role_count``; the economy fields —
hub stocks, extractor counts, gear costs — are game-specific and did not
port).

Pattern: in engines where every agent is stepped every tick (dead agents
included), each agent reports its own HP into the shared census each tick.
Liveness is then "reported recently AND last-reported HP > 0". The
freshness window is a defense against missing reports, not because dead
agents stop reporting. A startup grace treats never-reported agents as
alive for the first few ticks so early-episode logic doesn't see a phantom
empty team.
"""

from __future__ import annotations

from typing import Mapping

__all__ = ["TeamCensus"]


class TeamCensus:
    """Role roster + per-agent liveness reports.

    ``roster`` maps agent_id -> role name (fixed for the episode).
    ``freshness_window`` is how many ticks a report stays credible
    (the original stack derived ``max(20, claim_ttl * 5)`` = 125 at its
    production settings — made an explicit knob here).
    ``startup_grace``: through this step, agents that have never reported
    are assumed alive.
    """

    def __init__(
        self,
        roster: Mapping[int, str],
        freshness_window: int = 125,
        startup_grace: int = 5,
    ) -> None:
        self._roster: dict[int, str] = dict(roster)
        self._freshness_window = freshness_window
        self._startup_grace = startup_grace
        self._last_report_step: dict[int, int] = {}
        self._last_hp: dict[int, int] = {}

    @property
    def roster(self) -> dict[int, str]:
        return dict(self._roster)

    def role_of(self, agent_id: int) -> str | None:
        return self._roster.get(agent_id)

    def report_alive(self, agent_id: int, hp: int, step: int) -> None:
        """Each agent calls this for itself every tick with its current HP."""
        self._last_report_step[agent_id] = step
        self._last_hp[agent_id] = hp

    def is_alive(self, agent_id: int, step: int) -> bool:
        """Believed alive: fresh report with HP > 0 (or startup grace)."""
        last_step = self._last_report_step.get(agent_id, -1)
        if last_step < 0:
            return step <= self._startup_grace
        if (step - last_step) > self._freshness_window:
            return False
        return self._last_hp.get(agent_id, 0) > 0

    def alive_count(self, role: str, step: int) -> int:
        """Count agents we believe are alive *and* assigned ``role``."""
        return sum(
            1
            for agent_id, agent_role in self._roster.items()
            if agent_role == role and self.is_alive(agent_id, step)
        )

    def total_alive(self, step: int) -> int:
        """Total live agents across the whole roster."""
        return sum(
            1 for agent_id in self._roster if self.is_alive(agent_id, step)
        )
