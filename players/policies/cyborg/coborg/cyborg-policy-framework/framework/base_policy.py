"""Abstract policy control loop.

Games subclass BasePolicy and implement the game-specific hooks:
  - create_brain(): return a BaseBrain instance
  - create_harness(): return a BaseHarness instance (optional)
  - perceive(): parse raw observation into a snapshot dict
  - execute(): convert a Command into a game action
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from .types import Command, CommandKind, Directive, GameConfig
from .base_brain import BaseBrain
from .base_harness import BaseHarness


class BasePolicy(ABC):
  """Abstract per-agent policy with a perceive->decide->execute loop.

  Subclasses implement the game-specific hooks. The framework provides
  the LLM consultation scheduling and directive application.
  """

  def __init__(self, agent_id: int = 0, config: GameConfig | None = None):
    self.agent_id = agent_id
    self.config = config or GameConfig()
    self.brain: BaseBrain | None = None
    self.harness: BaseHarness | None = None
    self._tick = 0

  def initialize(self) -> None:
    """Called once before the first step. Sets up brain and harness."""
    self.brain = self.create_brain()
    self.brain.prepare(self.config)
    self.harness = self.create_harness()
    if self.harness:
      self.harness.start()

  @abstractmethod
  def create_brain(self) -> BaseBrain:
    """Create and return the game-specific brain."""
    ...

  def create_harness(self) -> BaseHarness | None:
    """Create and return the LLM harness. Return None for scripted-only mode."""
    return None

  @abstractmethod
  def perceive(self, raw_observation: Any) -> dict:
    """Parse a raw game observation into a snapshot dict."""
    ...

  @abstractmethod
  def execute(self, command: Command) -> Any:
    """Convert a Command into a game-engine action and return it."""
    ...

  def step(self, raw_observation: Any) -> Any:
    """Main per-tick control loop: perceive -> directive -> decide -> execute."""
    if self.brain is None:
      self.initialize()

    self._tick += 1
    snapshot = self.perceive(raw_observation)
    snapshot["tick"] = self._tick

    if self.harness:
      brain_state = self.brain.debug_state()
      self.harness.push_snapshot(snapshot, brain_state)

      directive = self.harness.read_directive()
      if directive:
        self.brain.apply_directive(directive)

      if self.harness.game_surrendered:
        return self.execute(Command(kind=CommandKind.IDLE, reason="surrendered"))

    command = self.brain.decide(snapshot)
    return self.execute(command)

  def shutdown(self) -> None:
    """Called at game end. Flushes harness and memory."""
    if self.harness:
      self.harness.shutdown()
      self.harness.dump_memory()
