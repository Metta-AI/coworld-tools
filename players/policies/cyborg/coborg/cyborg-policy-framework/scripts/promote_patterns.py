#!/usr/bin/env python3
"""Pattern promotion pipeline — extract successful patterns from game-specific
evolution and integrate them into the default player policy (framework wiki).

The pipeline:
1. Scan learnings files for high-scoring games
2. Extract actionable rules and strategies that worked
3. Filter out patterns that also appear in failure lists
4. Append promoted patterns to framework/wiki/strategy/promoted-patterns.md
5. Update framework/wiki/strategy/common-mistakes.md with recurring failures
6. Record promotions in the fork manifest

Usage:
  python scripts/promote_patterns.py --game my_game
  python scripts/promote_patterns.py --game my_game --min-score 7 --min-frequency 2
  python scripts/promote_patterns.py --all
"""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
FRAMEWORK_DIR = PROJECT_ROOT / "framework"
RUNS_DIR = PROJECT_ROOT / "runs"
MANIFEST_FILE = RUNS_DIR / "fork_manifest.json"

PROMOTED_FILE = FRAMEWORK_DIR / "wiki" / "strategy" / "promoted-patterns.md"
MISTAKES_FILE = FRAMEWORK_DIR / "wiki" / "strategy" / "common-mistakes.md"


def load_learnings(game: str) -> list[dict]:
  search_dir = RUNS_DIR / game
  learnings = []
  if not search_dir.exists():
    return learnings
  for f in sorted(search_dir.glob("*_learnings.json")):
    try:
      with open(f) as fh:
        data = json.load(fh)
        data["_file"] = f.name
        learnings.append(data)
    except (json.JSONDecodeError, IOError):
      continue
  return learnings


def load_cross_game_memory() -> dict:
  mem_path = RUNS_DIR / "cross_game_memory.json"
  if mem_path.exists():
    with open(mem_path) as f:
      return json.load(f)
  return {}


def extract_candidates(
  learnings: list[dict],
  min_score: int = 7,
  min_frequency: int = 2,
) -> dict:
  """Extract promotion candidates from learnings.

  Returns dict with:
    successful_rules: list of (rule, count) tuples
    successful_strategies: list of unique strategy strings
    recurring_mistakes: list of (mistake, count) tuples
  """
  rule_counts: dict[str, int] = {}
  strategy_set: list[str] = []
  mistake_counts: dict[str, int] = {}

  for learn in learnings:
    score = learn.get("score", 0)

    mistake = learn.get("biggest_mistake", "")
    if mistake:
      key = mistake[:120].strip()
      mistake_counts[key] = mistake_counts.get(key, 0) + 1

    if score < min_score:
      continue

    for rule in learn.get("actionable_rules", []):
      rule_key = rule.strip()
      if rule_key:
        rule_counts[rule_key] = rule_counts.get(rule_key, 0) + 1

    strat = learn.get("recommended_next_game_strategy", "")
    if strat and strat not in strategy_set:
      strategy_set.append(strat[:200])

  successful = [(r, c) for r, c in rule_counts.items() if c >= min_frequency]
  successful.sort(key=lambda x: -x[1])

  recurring = [(m, c) for m, c in mistake_counts.items() if c >= min_frequency]
  recurring.sort(key=lambda x: -x[1])

  mistake_texts = {m for m, _ in recurring}
  promotable = [(r, c) for r, c in successful if r not in mistake_texts]

  return {
    "successful_rules": successful[:20],
    "promotable_rules": promotable[:10],
    "successful_strategies": strategy_set[:10],
    "recurring_mistakes": recurring[:10],
  }


def read_existing_promoted() -> set[str]:
  """Read already-promoted patterns to avoid duplicates."""
  if not PROMOTED_FILE.exists():
    return set()
  content = PROMOTED_FILE.read_text()
  existing = set()
  for line in content.split("\n"):
    line = line.strip()
    if line.startswith("- ") and not line.startswith("- Source:"):
      existing.add(line[2:].strip())
  return existing


def promote_rules(game: str, rules: list[tuple[str, int]], source: str = "auto") -> int:
  """Append new rules to the promoted patterns file. Returns count of new promotions."""
  PROMOTED_FILE.parent.mkdir(parents=True, exist_ok=True)

  if not PROMOTED_FILE.exists():
    with open(PROMOTED_FILE, "w") as f:
      f.write("# Promoted Patterns\n\n")
      f.write("Patterns promoted from game-specific evolution into the base policy.\n")
      f.write("Updated automatically by the promotion pipeline.\n\n")

  existing = read_existing_promoted()
  new_rules = [(r, c) for r, c in rules if r not in existing]

  if not new_rules:
    return 0

  with open(PROMOTED_FILE, "a") as f:
    f.write(f"\n## [{game}] {datetime.now().strftime('%Y-%m-%d %H:%M')}\n\n")
    for rule, count in new_rules:
      f.write(f"- {rule}\n")
      f.write(f"  - Frequency: {count}x across high-scoring games\n")
      f.write(f"  - Source: {source}\n")

  return len(new_rules)


def update_mistakes(game: str, mistakes: list[tuple[str, int]]) -> int:
  """Append new recurring mistakes to the common mistakes wiki page."""
  if not MISTAKES_FILE.exists():
    return 0

  content = MISTAKES_FILE.read_text()
  existing_mistakes = set()
  for line in content.split("\n"):
    stripped = line.strip()
    if stripped.startswith("**Symptom**:"):
      existing_mistakes.add(stripped)

  new_mistakes = [(m, c) for m, c in mistakes if m[:80] not in {e[:80] for e in existing_mistakes}]

  if not new_mistakes:
    return 0

  with open(MISTAKES_FILE, "a") as f:
    f.write(f"\n## Auto-Detected [{game}] — {datetime.now().strftime('%Y-%m-%d')}\n\n")
    for idx, (mistake, count) in enumerate(new_mistakes[:5], start=1):
      f.write(f"### {len(existing_mistakes) + idx}. {mistake[:60]}\n")
      f.write(f"**Symptom**: {mistake}\n")
      f.write(f"**Frequency**: {count}x across games\n")
      f.write(f"**Fix**: *(pending — evolution agent should address this)*\n\n")

  return len(new_mistakes)


def record_promotions(game: str, count: int, mistakes_count: int) -> None:
  """Record the promotion run in the fork manifest."""
  manifest = {"forks": {}, "promotions": []}
  if MANIFEST_FILE.exists():
    with open(MANIFEST_FILE) as f:
      manifest = json.load(f)

  manifest.setdefault("promotions", []).append({
    "game": game,
    "rules_promoted": count,
    "mistakes_added": mistakes_count,
    "promoted_at": datetime.now().isoformat(),
  })

  RUNS_DIR.mkdir(parents=True, exist_ok=True)
  with open(MANIFEST_FILE, "w") as f:
    json.dump(manifest, f, indent=2, default=str)


def run_promotion(game: str, min_score: int = 7, min_frequency: int = 2) -> None:
  learnings = load_learnings(game)
  if not learnings:
    print(f"No learnings found for {game}")
    return

  print(f"Scanning {len(learnings)} learnings for {game}...")
  candidates = extract_candidates(learnings, min_score, min_frequency)

  print(f"  Successful rules: {len(candidates['successful_rules'])}")
  print(f"  Promotable (no overlap with failures): {len(candidates['promotable_rules'])}")
  print(f"  Strategies from high-scoring games: {len(candidates['successful_strategies'])}")
  print(f"  Recurring mistakes: {len(candidates['recurring_mistakes'])}")

  rules_promoted = promote_rules(game, candidates["promotable_rules"])
  mistakes_added = update_mistakes(game, candidates["recurring_mistakes"])

  record_promotions(game, rules_promoted, mistakes_added)

  print(f"\nResults:")
  print(f"  Rules promoted to framework wiki: {rules_promoted}")
  print(f"  Mistakes added to common-mistakes: {mistakes_added}")

  if rules_promoted > 0:
    print(f"  → {PROMOTED_FILE}")
  if mistakes_added > 0:
    print(f"  → {MISTAKES_FILE}")


def main():
  parser = argparse.ArgumentParser(description="Pattern promotion pipeline")
  parser.add_argument("--game", default=None, help="Game name (or --all)")
  parser.add_argument("--all", action="store_true", help="Promote from all games")
  parser.add_argument("--min-score", type=int, default=7, help="Minimum score to consider (default: 7)")
  parser.add_argument("--min-frequency", type=int, default=2, help="Minimum rule frequency (default: 2)")

  args = parser.parse_args()

  if args.all:
    games_dir = PROJECT_ROOT / "games"
    if games_dir.exists():
      for game_dir in sorted(games_dir.iterdir()):
        if game_dir.is_dir() and game_dir.name != "new_game":
          run_promotion(game_dir.name, args.min_score, args.min_frequency)
  elif args.game:
    run_promotion(args.game, args.min_score, args.min_frequency)
  else:
    parser.print_help()


if __name__ == "__main__":
  main()
