#!/usr/bin/env python3
"""Policy fork/reset manager for the weekly evolution cycle.

Each week:
1. Fork from the base (default) policy to create a weekly working branch
2. Run games + evolution on the working branch
3. At week end: extract successful patterns, report changes, reset

Usage:
  python scripts/policy_manager.py fork --game my_game
  python scripts/policy_manager.py status --game my_game
  python scripts/policy_manager.py reset --game my_game
  python scripts/policy_manager.py promote --game my_game --pattern "rule text"
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
GAMES_DIR = PROJECT_ROOT / "games"
FRAMEWORK_DIR = PROJECT_ROOT / "framework"
RUNS_DIR = PROJECT_ROOT / "runs"
MANIFEST_FILE = RUNS_DIR / "fork_manifest.json"


def _git(cwd: str, *args: str) -> str:
  result = subprocess.run(
    ["git", *args],
    cwd=cwd, capture_output=True, text=True, timeout=30,
  )
  if result.returncode != 0:
    raise RuntimeError(f"git {' '.join(args)} failed: {result.stderr.strip()}")
  return result.stdout


def load_manifest() -> dict:
  if MANIFEST_FILE.exists():
    with open(MANIFEST_FILE) as f:
      return json.load(f)
  return {"forks": {}, "promotions": []}


def save_manifest(data: dict) -> None:
  RUNS_DIR.mkdir(parents=True, exist_ok=True)
  with open(MANIFEST_FILE, "w") as f:
    json.dump(data, f, indent=2, default=str)


def get_base_branch() -> str:
  """Detect the default/base branch."""
  try:
    return _git(str(PROJECT_ROOT), "symbolic-ref", "--short", "refs/remotes/origin/HEAD").strip().split("/")[-1]
  except Exception:
    try:
      _git(str(PROJECT_ROOT), "rev-parse", "--verify", "main")
      return "main"
    except Exception:
      return "master"


def fork_policy(game: str) -> None:
  """Create a weekly branch forked from the base policy."""
  root = str(PROJECT_ROOT)
  base = get_base_branch()
  week = datetime.now().strftime("%Y-W%W")
  branch_name = f"policy/{game}/{week}"

  current = _git(root, "branch", "--show-current").strip()

  try:
    _git(root, "rev-parse", "--verify", branch_name)
    print(f"Branch {branch_name} already exists. Switching to it.")
    _git(root, "checkout", branch_name)
  except RuntimeError:
    _git(root, "checkout", "-b", branch_name, base)
    print(f"Created weekly branch: {branch_name} (from {base})")

  manifest = load_manifest()
  manifest["forks"][game] = {
    "branch": branch_name,
    "base": base,
    "forked_at": datetime.now().isoformat(),
    "week": week,
    "games_played": 0,
    "evolutions": 0,
    "status": "active",
  }
  save_manifest(manifest)

  print(f"\nWeekly policy fork ready:")
  print(f"  Game: {game}")
  print(f"  Branch: {branch_name}")
  print(f"  Base: {base}")
  print(f"  Week: {week}")
  print(f"\nRun games with: ./scripts/continuous_loop.sh {game}")


def status(game: str | None = None) -> None:
  """Show the status of active policy forks."""
  manifest = load_manifest()
  forks = manifest.get("forks", {})

  if not forks:
    print("No active policy forks.")
    return

  games = [game] if game else list(forks.keys())

  for g in games:
    info = forks.get(g)
    if not info:
      print(f"No fork for game: {g}")
      continue

    print(f"\n[{g}]")
    print(f"  Branch: {info['branch']}")
    print(f"  Base: {info['base']}")
    print(f"  Week: {info['week']}")
    print(f"  Status: {info['status']}")
    print(f"  Forked: {info['forked_at']}")

    score_file = RUNS_DIR / g / "score_history.json"
    if score_file.exists():
      with open(score_file) as f:
        history = json.load(f)
      games_list = history.get("games", [])
      if games_list:
        recent = games_list[-5:]
        scores = [x.get("score", 0) for x in recent]
        avg = sum(scores) / len(scores) if scores else 0
        print(f"  Games played: {len(games_list)}")
        print(f"  Recent avg: {avg:.1f}/10")

  promotions = manifest.get("promotions", [])
  if promotions:
    print(f"\n[Promoted Patterns — {len(promotions)} total]")
    for p in promotions[-5:]:
      print(f"  [{p.get('game', '?')}] {p.get('pattern', '?')[:80]}")


def reset_policy(game: str) -> None:
  """Reset the game's policy branch back to the base.

  Before resetting, generates a change report and saves it.
  """
  root = str(PROJECT_ROOT)
  manifest = load_manifest()
  fork_info = manifest.get("forks", {}).get(game)

  if not fork_info:
    print(f"No active fork for {game}")
    return

  branch = fork_info["branch"]
  base = fork_info["base"]

  current = _git(root, "branch", "--show-current").strip()
  if current != branch:
    print(f"Not on the fork branch ({branch}), currently on {current}")
    print(f"Switch to the fork branch first: git checkout {branch}")
    return

  diff_stat = _git(root, "diff", "--stat", f"{base}...HEAD")
  log = _git(root, "log", "--oneline", f"{base}...HEAD")

  report = {
    "game": game,
    "branch": branch,
    "base": base,
    "week": fork_info.get("week"),
    "reset_at": datetime.now().isoformat(),
    "commits": log.strip().count("\n") + 1 if log.strip() else 0,
    "diff_stat": diff_stat.strip(),
    "commit_log": log.strip(),
  }

  report_path = RUNS_DIR / f"reset_report_{game}_{fork_info.get('week', 'unknown')}.json"
  with open(report_path, "w") as f:
    json.dump(report, f, indent=2, default=str)
  print(f"Reset report saved: {report_path}")

  _git(root, "checkout", base)
  print(f"\nPolicy reset to base branch: {base}")
  print(f"Working branch {branch} is preserved for reference.")

  fork_info["status"] = "reset"
  fork_info["reset_at"] = datetime.now().isoformat()
  save_manifest(manifest)


def promote_pattern(game: str, pattern: str, source: str = "manual") -> None:
  """Promote a successful pattern from a game into the framework wiki.

  Appends the pattern to framework/wiki/strategy/common-mistakes.md or a
  dedicated promoted-patterns file.
  """
  promoted_file = FRAMEWORK_DIR / "wiki" / "strategy" / "promoted-patterns.md"

  if not promoted_file.exists():
    promoted_file.parent.mkdir(parents=True, exist_ok=True)
    header = "# Promoted Patterns\n\nPatterns promoted from game-specific evolution into the base policy.\n\n"
    with open(promoted_file, "w") as f:
      f.write(header)

  entry = f"\n## [{game}] {datetime.now().strftime('%Y-%m-%d')}\n\n- {pattern}\n- Source: {source}\n"
  with open(promoted_file, "a") as f:
    f.write(entry)

  manifest = load_manifest()
  manifest.setdefault("promotions", []).append({
    "game": game,
    "pattern": pattern,
    "source": source,
    "promoted_at": datetime.now().isoformat(),
  })
  save_manifest(manifest)

  print(f"Pattern promoted to framework wiki:")
  print(f"  Game: {game}")
  print(f"  Pattern: {pattern[:100]}")
  print(f"  File: {promoted_file}")


def main():
  parser = argparse.ArgumentParser(description="Policy fork/reset manager")
  sub = parser.add_subparsers(dest="command")

  fork_p = sub.add_parser("fork", help="Fork a weekly policy branch")
  fork_p.add_argument("--game", required=True, help="Game name")

  status_p = sub.add_parser("status", help="Show fork status")
  status_p.add_argument("--game", default=None, help="Game name (all if omitted)")

  reset_p = sub.add_parser("reset", help="Reset policy to base")
  reset_p.add_argument("--game", required=True, help="Game name")

  promote_p = sub.add_parser("promote", help="Promote a pattern to base policy")
  promote_p.add_argument("--game", required=True, help="Source game")
  promote_p.add_argument("--pattern", required=True, help="Pattern text to promote")
  promote_p.add_argument("--source", default="manual", help="Source (manual, evolution, analysis)")

  args = parser.parse_args()

  if args.command == "fork":
    fork_policy(args.game)
  elif args.command == "status":
    status(args.game)
  elif args.command == "reset":
    reset_policy(args.game)
  elif args.command == "promote":
    promote_pattern(args.game, args.pattern, args.source)
  else:
    parser.print_help()


if __name__ == "__main__":
  main()
