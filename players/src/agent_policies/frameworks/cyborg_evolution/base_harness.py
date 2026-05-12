"""Background LLM harness — game-agnostic base.

Runs as a daemon thread alongside the game loop. Monitors game state via a
LatestSlot, detects events, maintains structured memory, and consults the LLM
when triggers fire. Issues directives back to the policy via a mailbox queue.

Games subclass BaseHarness and implement:
  - parse_directive(): validate and parse LLM response into a Directive
  - build_context(): build narrator context string from memory
  - get_system_prompt(): return the LLM system prompt
"""

from __future__ import annotations

import atexit
import json
import logging
import os
import queue
import threading
import time
import uuid
from pathlib import Path

from .types import Directive
from .base_memory import GameMemory
from .base_triggers import BaseEventDetector

logger = logging.getLogger("framework.harness")


class LatestSlot:
  """Thread-safe single-value slot. Writers overwrite; reader takes-or-gets-None."""

  def __init__(self):
    self._value = None
    self._lock = threading.Lock()

  def put(self, value):
    with self._lock:
      self._value = value

  def take(self):
    with self._lock:
      v, self._value = self._value, None
      return v


class BaseHarness:
  """Background daemon thread that monitors the game and issues LLM directives.

  Subclasses must implement:
    - parse_directive(data, tick) -> Directive
    - build_context(memory, trigger, operator_notes) -> str
    - get_system_prompt(prior_learnings) -> str
  """

  def __init__(
    self,
    provider,
    game_id: str = "",
    game_name: str = "",
    max_steps: int = 10000,
    model_name: str = "scripted",
    seed: int = 0,
    mission: str = "",
    consult_interval: int = 200,
    poll_interval: float = 0.05,
    runs_dir: str | None = None,
    analysis_provider=None,
    event_detector: BaseEventDetector | None = None,
  ):
    self._provider = provider
    self._analysis_provider = analysis_provider
    self._consult_interval = consult_interval
    self._poll_interval = poll_interval
    self._runs_dir = runs_dir

    self.snapshot_slot = LatestSlot()
    self.directive_mailbox: queue.Queue[Directive] = queue.Queue(maxsize=8)

    gid = game_id or str(uuid.uuid4())[:8]
    self.memory = GameMemory(
      game_id=gid,
      game_name=game_name,
      max_steps=max_steps,
      model=model_name,
      seed=seed,
      mission=mission,
    )

    self._detector = event_detector
    self.game_surrendered: bool = False
    self._surrender_tick: int | None = None
    self._movement_verified: bool = False

    self._prior_learnings = self._load_prior_learnings(runs_dir)
    self._system_prompt = self.get_system_prompt(self._prior_learnings)

    self._conversation: list[dict] = []
    self._call_log: list[dict] = []
    self._calls_made = 0
    self._last_sync_tick = -consult_interval

    self._thread: threading.Thread | None = None
    self._shutdown_event = threading.Event()
    self._started = False
    self._post_game_thread: threading.Thread | None = None

    self._operator_messages: list[str] = []
    self._operator_lock = threading.Lock()

    atexit.register(self._atexit_dump)

  # ── Abstract methods — games must implement ────────────────────────

  def parse_directive(self, data: dict, tick: int) -> Directive:
    """Parse and validate an LLM response dict into a Directive.

    Override to validate game-specific roles, commands, resources, etc.
    """
    return Directive(
      role=data.get("role", ""),
      command=data.get("command"),
      target=self._parse_coord(data.get("target")),
      reasoning=data.get("reasoning", ""),
      params=data.get("params", {}),
      hold=bool(data.get("hold", False)),
      until=data.get("until") if isinstance(data.get("until"), str) else None,
      issued_tick=tick,
      expires_tick=tick + self._consult_interval + 100,
    )

  def build_context(self, memory: GameMemory, trigger: str,
                    operator_notes: list[str] | None = None) -> str:
    """Build the narrator context string from memory for LLM consultation.

    Override to include game-specific state in the context.
    """
    parts = [f"Trigger: {trigger}", f"Tick: {memory.working.snapshot_dict.get('tick', 0)}"]
    snap = memory.working.snapshot_dict
    if snap:
      parts.append(f"Snapshot keys: {list(snap.keys())}")
    if operator_notes:
      parts.append(f"Operator notes: {'; '.join(operator_notes)}")
    return "\n".join(parts)

  def get_system_prompt(self, prior_learnings: str = "") -> str:
    """Return the LLM system prompt. Override for game-specific prompts."""
    base = "You are a strategic advisor for a game AI agent."
    if prior_learnings:
      base += f"\n\n{prior_learnings}"
    return base

  def _load_prior_learnings(self, runs_dir: str | None) -> str:
    """Load prior game learnings for cross-game intelligence.

    Override for game-specific learning synthesis.
    """
    return ""

  # ── Public API (called from game loop thread) ──────────────────────

  def start(self) -> None:
    if self._started:
      return
    self._started = True
    self._thread = threading.Thread(
      target=self._run,
      daemon=True,
      name="llm-harness",
    )
    self._thread.start()
    logger.info("Harness thread started (game_id=%s)", self.memory.game_id)

  def push_snapshot(self, snapshot_dict: dict, brain_state: dict | None = None) -> None:
    """Push the current game state snapshot for the harness to process."""
    if brain_state:
      snapshot_dict.update(brain_state)
      if brain_state.get("movement_verified"):
        self._movement_verified = True
    self.snapshot_slot.put(snapshot_dict)

    directive_dict = None
    self.memory.working.update_from_snapshot(
      snapshot_dict,
      directive_dict,
      commands=snapshot_dict.get("command_history"),
    )

  def read_directive(self) -> Directive | None:
    try:
      return self.directive_mailbox.get_nowait()
    except queue.Empty:
      return None

  def add_operator_message(self, text: str) -> None:
    with self._operator_lock:
      self._operator_messages.append(text)

  def shutdown(self, timeout: float = 3.0) -> None:
    if not self._started:
      return
    self._shutdown_event.set()
    if self._thread and self._thread.is_alive():
      self._thread.join(timeout=timeout)
    logger.info("Harness thread stopped")

  def dump_memory(self, output_dir: str | None = None, trigger: str = "game_end") -> str | None:
    if self.memory.was_dumped and trigger != "manual":
      return None

    snap = self.memory.working.snapshot_dict
    final_tick = snap.get("tick", 0) if snap else 0

    total_tokens = sum(
      (r.get("input_tokens", 0) + r.get("output_tokens", 0))
      for r in self._call_log
      if isinstance(r, dict)
    )

    dump = self.memory.dump(
      trigger=trigger,
      final_tick=final_tick,
      llm_call_log=self._call_log,
      total_llm_calls=self._calls_made,
      total_tokens=total_tokens,
    )

    if self._prior_learnings:
      dump["prior_learnings"] = self._prior_learnings

    if output_dir is None:
      output_dir = self._runs_dir or str(
        Path(__file__).resolve().parent.parent / "runs"
      )

    os.makedirs(output_dir, exist_ok=True)
    filename = f"{self.memory.game_id}_memory.json"
    filepath = os.path.join(output_dir, filename)

    try:
      with open(filepath, "w") as f:
        json.dump(dump, f, indent=2, default=str)
      print(f"\n  >>> Memory dump written to {filepath} <<<\n")

      if self._analysis_provider and trigger in ("game_end", "atexit"):
        bg_thread = threading.Thread(
          target=self._run_post_game_background,
          args=(dump, filepath, trigger),
          daemon=False,
          name="post-game-analysis",
        )
        self._post_game_thread = bg_thread
        bg_thread.start()
        if trigger == "atexit":
          bg_thread.join(timeout=120)

      return filepath
    except Exception as e:
      logger.error("Failed to write memory dump: %s", e)
      return None

  def get_status(self) -> dict:
    return {
      "game_id": self.memory.game_id,
      "started": self._started,
      "thread_alive": self._thread.is_alive() if self._thread else False,
      "shutdown": self._shutdown_event.is_set(),
      "episodic_events": self.memory.episodic.count(),
      "strategic_facts": self.memory.strategic.count(),
      "llm_calls": self._calls_made,
      "directives_issued": len(self.memory._directive_history),
    }

  # ── Background thread ──────────────────────────────────────────────

  def _run(self) -> None:
    while not self._shutdown_event.is_set():
      try:
        self._tick()
      except Exception as e:
        logger.error("Harness tick error: %s", e, exc_info=True)
      self._shutdown_event.wait(timeout=self._poll_interval)
    logger.info("Harness thread exiting")

  def _tick(self) -> None:
    snap = self.snapshot_slot.take()
    if snap is None:
      return

    if self._detector:
      result = self._detector.evaluate(snap, self.memory)
    else:
      from .base_triggers import TriggerResult
      tick = snap.get("tick", 0)
      result = TriggerResult(
        trigger="periodic" if (tick % self._consult_interval == 0 and tick > 0) else None
      )

    with self._operator_lock:
      has_operator_msg = len(self._operator_messages) > 0
      operator_notes = list(self._operator_messages) if has_operator_msg else None

    should_consult = result.should_consult or has_operator_msg
    if not should_consult:
      return
    if self._provider is None:
      return

    trigger = result.trigger or "operator_message"
    tick = snap.get("tick", 0)

    context = self.build_context(self.memory, trigger=trigger, operator_notes=operator_notes)

    if has_operator_msg:
      with self._operator_lock:
        self._operator_messages.clear()

    directive = self._call_llm(tick, context, trigger)

    if directive:
      self.memory.record_directive(directive.to_dict(), tick)
      self.memory.episodic.record(
        tick,
        "decisions",
        f"LLM: {trigger} -> role={directive.role} cmd={directive.command} "
        f"target={directive.target} ({directive.reasoning[:60]})",
      )

      if directive.reasoning:
        strategy_expiry = max(500, self.memory.max_steps // 2)
        self.memory.strategic.set_fact(
          f"strategy:t{tick}",
          directive.reasoning,
          "strategy",
          tick,
          expires=tick + strategy_expiry,
        )

      try:
        self.directive_mailbox.put_nowait(directive)
      except queue.Full:
        logger.warning("Directive mailbox full, dropping directive at t=%d", tick)

      if self._detector:
        self._detector.mark_consulted(tick)

  def _call_llm(self, tick: int, context: str, trigger: str) -> Directive | None:
    user_content = f"[GAME STATE at tick {tick} — trigger: {trigger}]\n{context}"

    self._conversation.append({"role": "user", "content": user_content})
    if len(self._conversation) > 30:
      self._conversation = self._conversation[-30:]

    self._calls_made += 1
    record = {
      "tick": tick,
      "trigger": trigger,
      "call": self._calls_made,
      "prompt": user_content[:500],
      "response": "",
      "error": None,
      "latency_ms": 0,
      "input_tokens": 0,
      "output_tokens": 0,
    }

    directive = None
    try:
      resp = self._provider.complete(
        self._system_prompt,
        list(self._conversation),
        max_tokens=512,
      )
      record["latency_ms"] = resp.latency_ms
      record["response"] = resp.text[:500]
      record["model"] = resp.model
      record["input_tokens"] = resp.input_tokens
      record["output_tokens"] = resp.output_tokens

      self._conversation.append({"role": "assistant", "content": resp.text})

      raw = resp.text.strip()
      try:
        data = json.loads(raw)
      except json.JSONDecodeError:
        import re as _re
        _m = _re.search(r"\{.*\}", raw, _re.DOTALL)
        if _m:
          data = json.loads(_m.group())
        else:
          data = {"role": "", "command": "explore", "reasoning": "fallback: unparseable LLM response"}

      directive = self.parse_directive(data, tick)
      record["directive"] = directive.to_dict()

      print(
        f"\n  [HARNESS LLM #{self._calls_made} t={tick}] {trigger} "
        f"latency={resp.latency_ms:.0f}ms -> role={directive.role} "
        f"cmd={directive.command} target={directive.target}"
      )
      if directive.reasoning:
        print(f"    {directive.reasoning[:120]}")
      print()

      self._check_surrender(directive, tick)

    except Exception as e:
      record["error"] = str(e)
      logger.error("[HARNESS LLM t=%d] error: %s", tick, e)
      self._conversation.append({"role": "assistant", "content": f"[error: {e}]"})
    finally:
      self._call_log.append(record)

    return directive

  def _check_surrender(self, directive: Directive, tick: int) -> None:
    """Check if the LLM has declared the game lost."""
    MIN_SURRENDER_TICK = 200 if not self._movement_verified else 1000
    reasoning_lower = (directive.reasoning or "").lower()
    if tick >= MIN_SURRENDER_TICK and (
      "game lost" in reasoning_lower
      or "game over" in reasoning_lower
      or "surrender" in reasoning_lower
    ):
      self.game_surrendered = True
      self._surrender_tick = tick
      print(f"  [HARNESS] GAME SURRENDERED at tick {tick}")
      self.memory.episodic.record(
        tick, "decisions",
        f"GAME SURRENDERED: {directive.reasoning[:200]}",
        landmark=True,
      )

  def call_llm_sync(self, tick: int) -> Directive | None:
    """Synchronous LLM call from the game loop thread."""
    if self._provider is None:
      return None

    snap = self.memory.working.snapshot_dict
    if not snap:
      return None

    if self._detector:
      result = self._detector.evaluate(snap, self.memory)
      trigger = result.trigger or "sync_consult"
    else:
      trigger = "sync_consult"

    context = self.build_context(self.memory, trigger=trigger)
    directive = self._call_llm(tick, context, trigger)

    self._last_sync_tick = tick
    return directive

  def _run_post_game_background(self, dump: dict, filepath: str, trigger: str) -> None:
    """Run post-game analysis in a background thread. Override for game-specific behavior."""
    pass

  def _atexit_dump(self) -> None:
    if not self.memory.was_dumped and self._started:
      self.dump_memory(trigger="atexit")
    elif self._post_game_thread and self._post_game_thread.is_alive():
      print("  Waiting for post-game analysis to finish before exit...", flush=True)
      self._post_game_thread.join(timeout=180)

  @staticmethod
  def _parse_coord(raw) -> tuple[int, int] | None:
    if raw and isinstance(raw, (list, tuple)) and len(raw) == 2:
      try:
        return (int(raw[0]), int(raw[1]))
      except (ValueError, TypeError):
        pass
    return None
