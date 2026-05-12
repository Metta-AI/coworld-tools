"""Event detection skeleton — define your game's events here."""

from __future__ import annotations

from framework.base_memory import GameMemory, GameEvent
from framework.base_triggers import BaseEventDetector


TRIGGER_SCORE_CHANGE = "score_change"
TRIGGER_PHASE_CHANGE = "phase_change"

GAME_TRIGGER_PRIORITIES = {
  TRIGGER_SCORE_CHANGE: 60,
  TRIGGER_PHASE_CHANGE: 80,
}


class NewGameEventDetector(BaseEventDetector):
  """Event detection for the new game.

  Implement detect_game_events() to diff consecutive snapshots
  and return game-specific trigger/event pairs.
  """

  def get_trigger_priorities(self) -> dict[str, int]:
    return GAME_TRIGGER_PRIORITIES

  def detect_game_events(
    self, prev: dict, curr: dict, memory: GameMemory
  ) -> list[tuple[str, GameEvent]]:
    results: list[tuple[str, GameEvent]] = []
    tick = curr.get("tick", 0)

    # Example: detect phase changes
    if curr.get("phase") != prev.get("phase"):
      ev = memory.episodic.record(
        tick, "discovery",
        f"phase changed: {prev.get('phase')} -> {curr.get('phase')}",
        landmark=True,
      )
      results.append((TRIGGER_PHASE_CHANGE, ev))

    # TODO: Add game-specific event detection

    return results
