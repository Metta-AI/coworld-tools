"""Score tracking and escalation — game-agnostic.

Tracks game scores, computes rolling averages, and detects
when performance is good enough to escalate difficulty.
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path


class ScoreTracker:
  """Persistent score tracking with escalation logic."""

  def __init__(
    self,
    score_file: str | Path,
    runs_dir: str | Path,
    escalation_threshold: int = 8,
    escalation_window: int = 5,
    step_increment: int = 1000,
    default_steps: int = 2500,
  ):
    self.score_file = Path(score_file)
    self.runs_dir = Path(runs_dir)
    self.escalation_threshold = escalation_threshold
    self.escalation_window = escalation_window
    self.step_increment = step_increment
    self.default_steps = default_steps

  def load_history(self) -> dict:
    if self.score_file.exists():
      with open(self.score_file) as f:
        return json.load(f)
    return {"games": [], "current_steps": self.default_steps}

  def save_history(self, data: dict) -> None:
    self.runs_dir.mkdir(parents=True, exist_ok=True)
    with open(self.score_file, "w") as f:
      json.dump(data, f, indent=2)

  def extract_llm_stats(self, game_id: str) -> dict:
    stats = {}

    memory_path = self.runs_dir / f"{game_id}_memory.json"
    if memory_path.exists():
      try:
        with open(memory_path) as f:
          dump = json.load(f)
        meta = dump.get("meta", {})
        call_log = dump.get("llm_call_log", [])

        stats["llm_calls"] = meta.get("total_llm_calls", 0)
        stats["total_tokens"] = meta.get("total_tokens", 0)

        latencies = [c.get("latency_ms", 0) for c in call_log if isinstance(c, dict) and c.get("latency_ms")]
        stats["avg_latency_ms"] = round(sum(latencies) / len(latencies)) if latencies else 0
        stats["max_latency_ms"] = max(latencies) if latencies else 0

        input_tok = sum(c.get("input_tokens", 0) for c in call_log if isinstance(c, dict))
        output_tok = sum(c.get("output_tokens", 0) for c in call_log if isinstance(c, dict))
        stats["input_tokens"] = input_tok
        stats["output_tokens"] = output_tok
      except (json.JSONDecodeError, KeyError):
        pass

    learnings_path = self.runs_dir / f"{game_id}_learnings.json"
    if learnings_path.exists():
      try:
        with open(learnings_path) as f:
          learnings = json.load(f)
        analysis_meta = learnings.get("_meta", {})
        stats["analysis_tokens"] = analysis_meta.get("input_tokens", 0) + analysis_meta.get("output_tokens", 0)
        stats["analysis_latency_ms"] = analysis_meta.get("latency_ms", 0)
      except (json.JSONDecodeError, KeyError):
        pass

    return stats

  def get_latest_learnings(self) -> tuple[str, dict] | None:
    files = sorted(self.runs_dir.glob("*_learnings.json"), key=os.path.getmtime, reverse=True)
    if not files:
      return None
    path = files[0]
    game_id = path.stem.replace("_learnings", "")
    with open(path) as f:
      return game_id, json.load(f)

  def record_score(self, steps: int) -> None:
    result = self.get_latest_learnings()
    if result is None:
      print("No learnings files found")
      return

    game_id, learnings = result
    score = learnings.get("score", 0)
    mistake = str(learnings.get("biggest_mistake", ""))[:100]

    llm_stats = self.extract_llm_stats(game_id)
    history = self.load_history()

    if history["games"] and history["games"][-1].get("game_id") == game_id:
      print(f"  Score already recorded for {game_id}")
      return

    entry = {
      "game_id": game_id,
      "score": score,
      "steps": steps,
      "mistake": mistake,
      "timestamp": datetime.now().isoformat(),
      **llm_stats,
    }
    history["games"].append(entry)
    history["current_steps"] = steps
    self.save_history(history)

    calls = llm_stats.get("llm_calls", 0)
    tokens = llm_stats.get("total_tokens", 0)
    print(f"  Score recorded: game={game_id} score={score}/10 steps={steps} "
          f"llm_calls={calls} tokens={tokens}")

  def get_avg(self, n: int) -> float:
    history = self.load_history()
    games = history.get("games", [])
    if not games:
      return 0.0
    recent = games[-n:]
    scores = [g.get("score", 0) for g in recent]
    return sum(scores) / len(scores)

  def check_escalation(self, current_steps: int) -> int:
    history = self.load_history()
    games = history.get("games", [])
    if len(games) < self.escalation_window:
      return current_steps

    recent = games[-self.escalation_window:]
    scores = [g.get("score", 0) for g in recent]

    if all(s >= self.escalation_threshold for s in scores):
      new_steps = current_steps + self.step_increment
      history["current_steps"] = new_steps
      self.save_history(history)
      return new_steps

    return current_steps

  def print_history(self) -> None:
    history = self.load_history()
    games = history.get("games", [])
    if not games:
      print("No games recorded yet")
      return

    print(f"Total games: {len(games)} | Current steps: {history.get('current_steps', self.default_steps)}")
    print(f"{'#':>4} {'Score':>5} {'Steps':>6} {'LLM':>4} {'Tokens':>7} {'Game ID':>10}")
    print("-" * 50)

    for i, g in enumerate(games, 1):
      score = g.get("score", "?")
      steps = g.get("steps", "?")
      gid = g.get("game_id", "?")[:10]
      calls = g.get("llm_calls", 0)
      tokens = g.get("total_tokens", 0)
      print(f"{i:4d} {score:5}/10 {steps:6} {calls:4} {tokens:7} {gid:>10}")

    if len(games) >= 5:
      recent_5 = [g.get("score", 0) for g in games[-5:]]
      print(f"\n5-game avg: {sum(recent_5)/len(recent_5):.1f}/10")
