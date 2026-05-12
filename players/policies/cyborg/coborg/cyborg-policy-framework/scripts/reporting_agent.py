#!/usr/bin/env python3
"""Reporting agent — auto-documents changes between policy versions.

Compares the current policy branch to the base, generates a structured
change report, and appends it to the weekly changelog.

Usage:
  python scripts/reporting_agent.py --game my_game
  python scripts/reporting_agent.py --game my_game --base main --format markdown
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
RUNS_DIR = PROJECT_ROOT / "runs"
REPORTS_DIR = RUNS_DIR / "reports"


def _git(*args: str) -> str:
  result = subprocess.run(
    ["git", *args],
    cwd=str(PROJECT_ROOT), capture_output=True, text=True, timeout=30,
  )
  if result.returncode != 0:
    raise RuntimeError(f"git {' '.join(args)} failed: {result.stderr.strip()}")
  return result.stdout


def detect_base_branch() -> str:
  try:
    return _git("symbolic-ref", "--short", "refs/remotes/origin/HEAD").strip().split("/")[-1]
  except Exception:
    return "main"


def get_current_branch() -> str:
  return _git("branch", "--show-current").strip()


def get_commit_log(base: str) -> list[dict]:
  """Structured commit log since divergence from base."""
  try:
    raw = _git("log", f"{base}...HEAD", "--format=%H|%ai|%an|%s")
  except RuntimeError:
    return []

  commits = []
  for line in raw.strip().split("\n"):
    if not line.strip():
      continue
    parts = line.split("|", 3)
    if len(parts) == 4:
      commits.append({
        "hash": parts[0][:8],
        "date": parts[1],
        "author": parts[2],
        "subject": parts[3],
      })
  return commits


def get_diff_stat(base: str) -> str:
  try:
    return _git("diff", "--stat", f"{base}...HEAD").strip()
  except RuntimeError:
    return ""


def get_changed_files(base: str) -> list[str]:
  try:
    raw = _git("diff", "--name-only", f"{base}...HEAD")
    return [f for f in raw.strip().split("\n") if f.strip()]
  except RuntimeError:
    return []


def categorize_changes(files: list[str]) -> dict[str, list[str]]:
  """Group changed files by category."""
  categories: dict[str, list[str]] = {
    "brain": [],
    "wiki/skills": [],
    "wiki/strategy": [],
    "wiki/mechanics": [],
    "harness": [],
    "triggers": [],
    "config": [],
    "framework": [],
    "scripts": [],
    "other": [],
  }

  for f in files:
    if "brain" in f:
      categories["brain"].append(f)
    elif "wiki/skills" in f:
      categories["wiki/skills"].append(f)
    elif "wiki/strategy" in f:
      categories["wiki/strategy"].append(f)
    elif "wiki/mechanics" in f:
      categories["wiki/mechanics"].append(f)
    elif "harness" in f:
      categories["harness"].append(f)
    elif "trigger" in f:
      categories["triggers"].append(f)
    elif "config" in f:
      categories["config"].append(f)
    elif "framework/" in f:
      categories["framework"].append(f)
    elif "scripts/" in f:
      categories["scripts"].append(f)
    else:
      categories["other"].append(f)

  return {k: v for k, v in categories.items() if v}


def load_score_history(game: str) -> dict:
  """Load score history for the given game."""
  score_file = RUNS_DIR / game / "score_history.json"

  if not score_file.exists():
    return {}

  with open(score_file) as f:
    return json.load(f)


def load_learnings(game: str) -> list[dict]:
  """Load all learnings files for the game."""
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


def generate_report(game: str, base: str | None = None) -> dict:
  """Generate a full change report."""
  if base is None:
    base = detect_base_branch()

  current = get_current_branch()
  commits = get_commit_log(base)
  diff_stat = get_diff_stat(base)
  changed_files = get_changed_files(base)
  categories = categorize_changes(changed_files)
  scores = load_score_history(game)
  learnings = load_learnings(game)

  games_list = scores.get("games", [])
  recent_scores = [g.get("score", 0) for g in games_list[-10:]]
  avg = sum(recent_scores) / len(recent_scores) if recent_scores else 0

  recurring_mistakes = {}
  successful_patterns = []
  for learn in learnings:
    mistake = learn.get("biggest_mistake", "")
    if mistake:
      key = mistake[:80].strip()
      recurring_mistakes[key] = recurring_mistakes.get(key, 0) + 1
    if learn.get("score", 0) >= 7:
      for rule in learn.get("actionable_rules", []):
        if rule not in successful_patterns:
          successful_patterns.append(rule)

  report = {
    "game": game,
    "branch": current,
    "base": base,
    "generated_at": datetime.now().isoformat(),
    "summary": {
      "total_commits": len(commits),
      "files_changed": len(changed_files),
      "games_played": len(games_list),
      "recent_avg_score": round(avg, 2),
    },
    "commits": commits,
    "diff_stat": diff_stat,
    "changed_files_by_category": categories,
    "recurring_mistakes": sorted(recurring_mistakes.items(), key=lambda x: -x[1])[:10],
    "successful_patterns": successful_patterns[:10],
    "promotable_patterns": [p for p in successful_patterns if recurring_mistakes.get(p, 0) == 0][:5],
  }

  return report


def format_markdown(report: dict) -> str:
  """Convert a report dict to readable markdown."""
  lines = []
  lines.append(f"# Policy Change Report — {report['game']}")
  lines.append(f"")
  lines.append(f"**Branch:** {report['branch']} (base: {report['base']})")
  lines.append(f"**Generated:** {report['generated_at']}")
  lines.append(f"")

  s = report["summary"]
  lines.append(f"## Summary")
  lines.append(f"")
  lines.append(f"| Metric | Value |")
  lines.append(f"|---|---|")
  lines.append(f"| Commits | {s['total_commits']} |")
  lines.append(f"| Files changed | {s['files_changed']} |")
  lines.append(f"| Games played | {s['games_played']} |")
  lines.append(f"| Recent avg score | {s['recent_avg_score']}/10 |")
  lines.append(f"")

  cats = report.get("changed_files_by_category", {})
  if cats:
    lines.append(f"## Changes by Category")
    lines.append(f"")
    for cat, files in cats.items():
      lines.append(f"### {cat} ({len(files)} files)")
      for f in files:
        lines.append(f"- `{f}`")
      lines.append(f"")

  commits = report.get("commits", [])
  if commits:
    lines.append(f"## Commit Log")
    lines.append(f"")
    for c in commits[:20]:
      lines.append(f"- `{c['hash']}` {c['subject']}")
    lines.append(f"")

  mistakes = report.get("recurring_mistakes", [])
  if mistakes:
    lines.append(f"## Recurring Mistakes")
    lines.append(f"")
    for mistake, count in mistakes:
      lines.append(f"- [{count}x] {mistake}")
    lines.append(f"")

  patterns = report.get("successful_patterns", [])
  if patterns:
    lines.append(f"## Successful Patterns")
    lines.append(f"")
    for p in patterns:
      lines.append(f"- {p}")
    lines.append(f"")

  promotable = report.get("promotable_patterns", [])
  if promotable:
    lines.append(f"## Recommended for Promotion")
    lines.append(f"")
    lines.append(f"These patterns worked well and don't appear in failure lists:")
    lines.append(f"")
    for p in promotable:
      lines.append(f"- {p}")
    lines.append(f"")

  return "\n".join(lines)


def save_report(report: dict, fmt: str = "json") -> Path:
  """Save the report to the reports directory."""
  REPORTS_DIR.mkdir(parents=True, exist_ok=True)
  game = report["game"]
  ts = datetime.now().strftime("%Y%m%d_%H%M%S")

  if fmt == "markdown":
    path = REPORTS_DIR / f"{game}_{ts}.md"
    with open(path, "w") as f:
      f.write(format_markdown(report))
  else:
    path = REPORTS_DIR / f"{game}_{ts}.json"
    with open(path, "w") as f:
      json.dump(report, f, indent=2, default=str)

  return path


def main():
  parser = argparse.ArgumentParser(description="Policy reporting agent")
  parser.add_argument("--game", required=True, help="Game name")
  parser.add_argument("--base", default=None, help="Base branch (auto-detected if omitted)")
  parser.add_argument("--format", choices=["json", "markdown"], default="markdown", help="Output format")
  parser.add_argument("--stdout", action="store_true", help="Print to stdout instead of saving")

  args = parser.parse_args()

  report = generate_report(args.game, args.base)

  if args.stdout:
    if args.format == "markdown":
      print(format_markdown(report))
    else:
      print(json.dumps(report, indent=2, default=str))
  else:
    path = save_report(report, args.format)
    print(f"Report saved: {path}")

    if args.format == "json":
      md_path = save_report(report, "markdown")
      print(f"Markdown copy: {md_path}")


if __name__ == "__main__":
  main()
