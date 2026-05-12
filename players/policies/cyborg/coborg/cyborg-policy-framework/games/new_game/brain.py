"""Brain skeleton — implement your game's decision logic here."""

from __future__ import annotations

from framework.base_brain import BaseBrain
from framework.types import Command, CommandKind, Directive, GameConfig


class NewGameBrain(BaseBrain):
  """Per-tick decision engine for the new game.

  Replace this with your game's heuristics and decision logic.
  """

  def __init__(self, agent_id: int = 0):
    self.agent_id = agent_id
    self.role = "default"
    self._config: GameConfig | None = None

  def prepare(self, config: GameConfig) -> None:
    self._config = config

  def decide(self, snapshot: dict) -> Command:
    # TODO: Implement game-specific decision logic
    return Command(kind=CommandKind.EXPLORE, reason="default explore")

  def apply_directive(self, directive: Directive) -> None:
    if directive.role:
      self.role = directive.role

  def debug_state(self) -> dict:
    return {
      "role": self.role,
      "agent_id": self.agent_id,
    }
