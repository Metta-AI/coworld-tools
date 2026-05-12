"""Harness skeleton — wire up game-specific LLM behavior."""

from __future__ import annotations

from framework.base_harness import BaseHarness
from framework.base_memory import GameMemory
from framework.types import Directive

from .triggers import NewGameEventDetector
from .game_config import ANALYSIS_SYSTEM_PROMPT


class NewGameHarness(BaseHarness):
  """LLM harness for the new game."""

  def __init__(self, provider, analysis_provider=None, **kwargs):
    detector = NewGameEventDetector(
      consult_interval=kwargs.get("consult_interval", 200),
    )
    super().__init__(
      provider=provider,
      analysis_provider=analysis_provider,
      event_detector=detector,
      game_name="new_game",
      **kwargs,
    )

  def parse_directive(self, data: dict, tick: int) -> Directive:
    # TODO: Validate game-specific roles and commands
    return Directive(
      role=data.get("role", "default"),
      command=data.get("command"),
      target=self._parse_coord(data.get("target")),
      reasoning=data.get("reasoning", ""),
      issued_tick=tick,
      expires_tick=tick + self._consult_interval + 100,
    )

  def build_context(self, memory: GameMemory, trigger: str,
                    operator_notes: list[str] | None = None) -> str:
    # TODO: Build game-specific context for the LLM
    snap = memory.working.snapshot_dict
    parts = [
      f"Trigger: {trigger}",
      f"Tick: {snap.get('tick', 0)}",
    ]
    if operator_notes:
      parts.append(f"Operator: {'; '.join(operator_notes)}")
    return "\n".join(parts)

  def get_system_prompt(self, prior_learnings: str = "") -> str:
    # TODO: Add game-specific system prompt
    base = "You are a strategic advisor for a game AI agent."
    if prior_learnings:
      base += f"\n\n{prior_learnings}"
    return base

  def _run_post_game_background(self, dump: dict, filepath: str, trigger: str) -> None:
    from framework.base_analysis import run_post_game_analysis
    try:
      run_post_game_analysis(
        dump, self._analysis_provider,
        memory_dump_path=filepath,
        system_prompt=ANALYSIS_SYSTEM_PROMPT,
      )
    except Exception:
      pass
