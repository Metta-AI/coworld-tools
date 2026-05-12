"""Abstract decision engine.

Games subclass BaseBrain and implement the four required methods.
The framework never looks inside the snapshot or understands game rules.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from .types import Command, Directive, GameConfig


class BaseBrain(ABC):
  """Abstract base class for a per-tick decision engine.

  Each game implements a concrete brain. The framework calls:
    prepare() once before the first tick,
    decide() every tick,
    apply_directive() when an LLM directive arrives,
    debug_state() for observability.
  """

  @abstractmethod
  def prepare(self, config: GameConfig) -> None:
    """Initialize with game parameters before the first tick."""
    ...

  @abstractmethod
  def decide(self, snapshot: dict) -> Command:
    """Given the current game state, return an action command."""
    ...

  @abstractmethod
  def apply_directive(self, directive: Directive) -> None:
    """Apply an LLM strategic override to the brain's internal state."""
    ...

  @abstractmethod
  def debug_state(self) -> dict:
    """Return a dict of internal state for observability/debugging."""
    ...
