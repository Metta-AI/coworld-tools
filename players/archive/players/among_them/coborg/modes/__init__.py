"""Symbolic modes for the coborg Among Them agent.

P0 ships only :class:`IdleMode`. Subsequent phases add navigation, task
completion, meetings, voting, body reporting, and imposter behavior — see
PLAN §4 and §6 for the schedule.
"""

from __future__ import annotations

from players.among_them.coborg.modes.idle import (
    IdleMode,
)

__all__ = ["IdleMode"]
