"""Policy skeleton — wire up the perceive->decide->execute loop."""

from __future__ import annotations

from typing import Any

from framework.base_policy import BasePolicy
from framework.base_brain import BaseBrain
from framework.base_harness import BaseHarness
from framework.types import Command, GameConfig

from .brain import NewGameBrain
from .harness import NewGameHarness


class NewGamePolicy(BasePolicy):
  """Per-agent policy for the new game.

  Implement perceive() and execute() for your game engine's interface.
  """

  def __init__(self, agent_id: int = 0, config: GameConfig | None = None,
               provider=None, analysis_provider=None):
    super().__init__(agent_id=agent_id, config=config)
    self._provider = provider
    self._analysis_provider = analysis_provider

  def create_brain(self) -> BaseBrain:
    return NewGameBrain(agent_id=self.agent_id)

  def create_harness(self) -> BaseHarness | None:
    if self._provider is None:
      return None
    return NewGameHarness(
      provider=self._provider,
      analysis_provider=self._analysis_provider,
      game_id=self.config.game_id,
      max_steps=self.config.max_steps,
      seed=self.config.seed,
      runs_dir=self.config.run_dir,
    )

  def perceive(self, raw_observation: Any) -> dict:
    # TODO: Parse your game engine's observation into a snapshot dict
    return {"raw": raw_observation}

  def execute(self, command: Command) -> Any:
    # TODO: Convert a Command into your game engine's action format
    return command.kind.name.lower()
