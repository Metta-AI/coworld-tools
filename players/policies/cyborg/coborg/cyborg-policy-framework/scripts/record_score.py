"""Score tracking utility for the continuous game loop.

Records Opus analysis scores, computes rolling averages, and detects
when the agent is optimized enough to escalate step count.

Usage:
  python scripts/record_score.py --record --steps 1000
  python scripts/record_score.py --record --steps 1000 --game my_game
  python scripts/record_score.py --avg 5
  python scripts/record_score.py --check-escalation --current-steps 1000
  python scripts/record_score.py --history
"""

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
RUNS_DIR = PROJECT_ROOT / "runs"
SCORE_FILE = RUNS_DIR / "score_history.json"
ESCALATION_THRESHOLD = 8
ESCALATION_WINDOW = 5
STEP_INCREMENT = 1000


def _resolve_paths(game: str | None = None):
  """Return (runs_dir, score_file) for the given game, or defaults."""
  if game:
    runs = PROJECT_ROOT / "runs" / game
    score = runs / "score_history.json"
    return runs, score
  return RUNS_DIR, SCORE_FILE


def load_history(game: str | None = None) -> dict:
  _, score_file = _resolve_paths(game)
  if score_file.exists():
    with open(score_file) as f:
      return json.load(f)
  return {"games": [], "current_steps": 2500}


def save_history(data: dict, game: str | None = None) -> None:
  runs_dir, score_file = _resolve_paths(game)
  runs_dir.mkdir(parents=True, exist_ok=True)
  with open(score_file, "w") as f:
    json.dump(data, f, indent=2)


def _extract_llm_stats(game_id: str, game: str | None = None) -> dict:
  """Pull LLM usage stats from the memory dump and learnings files."""
  runs_dir, _ = _resolve_paths(game)
  stats = {}

  memory_path = runs_dir / f"{game_id}_memory.json"
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

  learnings_path = runs_dir / f"{game_id}_learnings.json"
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


def get_latest_learnings(game: str | None = None) -> tuple[str, dict] | None:
  runs_dir, _ = _resolve_paths(game)
  files = sorted(runs_dir.glob("*_learnings.json"), key=os.path.getmtime, reverse=True)
  if not files:
    return None
  path = files[0]
  game_id = path.stem.replace("_learnings", "")
  with open(path) as f:
    return game_id, json.load(f)


def record_score(steps: int, game: str | None = None) -> None:
  result = get_latest_learnings(game)
  if result is None:
    print("No learnings files found")
    return

  game_id, learnings = result
  score = learnings.get("score", 0)
  mistake = str(learnings.get("biggest_mistake", ""))[:100]

  llm_stats = _extract_llm_stats(game_id, game)
  history = load_history(game)

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
  save_history(history, game)

  calls = llm_stats.get("llm_calls", 0)
  tokens = llm_stats.get("total_tokens", 0)
  analysis_tokens = llm_stats.get("analysis_tokens", 0)
  print(f"  Score recorded: game={game_id} score={score}/10 steps={steps} "
        f"llm_calls={calls} tokens={tokens} analysis_tok={analysis_tokens}")


def get_avg(n: int, game: str | None = None) -> float:
  history = load_history(game)
  games = history.get("games", [])
  if not games:
    return 0.0
  recent = games[-n:]
  scores = [g.get("score", 0) for g in recent]
  return sum(scores) / len(scores)


def check_escalation(current_steps: int, game: str | None = None) -> int:
  history = load_history(game)
  games = history.get("games", [])
  if len(games) < ESCALATION_WINDOW:
    return current_steps

  recent = games[-ESCALATION_WINDOW:]
  scores = [g.get("score", 0) for g in recent]

  if all(s >= ESCALATION_THRESHOLD for s in scores):
    new_steps = current_steps + STEP_INCREMENT
    history["current_steps"] = new_steps
    save_history(history, game)
    return new_steps

  return current_steps


def print_history(game: str | None = None) -> None:
  history = load_history(game)
  games = history.get("games", [])
  if not games:
    print("No games recorded yet")
    return

  print(f"Total games: {len(games)} | Current steps: {history.get('current_steps', 2500)}")
  print(f"{'#':>4} {'Score':>5} {'Steps':>6} {'LLM':>4} {'Tokens':>7} {'Lat':>5} {'Analysis':>8} {'Game ID':>10}")
  print("-" * 65)

  total_tokens = 0
  total_analysis = 0
  for i, g in enumerate(games, 1):
    score = g.get("score", "?")
    steps = g.get("steps", "?")
    gid = g.get("game_id", "?")[:10]
    calls = g.get("llm_calls", 0)
    tokens = g.get("total_tokens", 0)
    lat = g.get("avg_latency_ms", 0)
    analysis = g.get("analysis_tokens", 0)
    total_tokens += tokens + analysis
    total_analysis += analysis
    print(f"{i:4d} {score:5}/10 {steps:6} {calls:4} {tokens:7} {lat:5} {analysis:8} {gid:>10}")

  print(f"\nTotal LLM tokens (in-game): {total_tokens - total_analysis:,}")
  print(f"Total analysis tokens: {total_analysis:,}")
  print(f"Total all tokens: {total_tokens:,}")

  if len(games) >= 5:
    recent_5 = [g.get("score", 0) for g in games[-5:]]
    print(f"\n5-game avg: {sum(recent_5)/len(recent_5):.1f}/10")
  if len(games) >= 10:
    recent_10 = [g.get("score", 0) for g in games[-10:]]
    print(f"10-game avg: {sum(recent_10)/len(recent_10):.1f}/10")


def main():
  parser = argparse.ArgumentParser(description="Score tracker")
  parser.add_argument("--record", action="store_true", help="Record latest game score")
  parser.add_argument("--steps", type=int, default=2500, help="Current step count")
  parser.add_argument("--game", type=str, default=None, help="Game name (scopes runs to a subdirectory)")
  parser.add_argument("--avg", type=int, metavar="N", help="Print N-game rolling average")
  parser.add_argument("--check-escalation", action="store_true", help="Check if steps should increase")
  parser.add_argument("--current-steps", type=int, default=2500, help="Current step count for escalation check")
  parser.add_argument("--history", action="store_true", help="Print full score history")

  args = parser.parse_args()

  if args.record:
    record_score(args.steps, args.game)
  elif args.avg is not None:
    avg = get_avg(args.avg, args.game)
    print(f"{avg:.1f}")
  elif args.check_escalation:
    new_steps = check_escalation(args.current_steps, args.game)
    print(new_steps)
  elif args.history:
    print_history(args.game)
  else:
    parser.print_help()


if __name__ == "__main__":
  main()
