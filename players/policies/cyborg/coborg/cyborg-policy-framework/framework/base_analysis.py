"""Post-game analysis — game-agnostic base.

Provides the generic analysis pipeline: build prompt from memory dump,
call LLM, parse structured learnings, save to disk. Games provide
a custom system prompt and can override the prompt builder.
"""

from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path

logger = logging.getLogger("framework.analysis")

DEFAULT_ANALYSIS_SYSTEM_PROMPT = """\
You are analyzing a completed game to extract reusable strategic insights.

You will receive the full memory dump from one game. Your job:
1. Identify what WORKED — strategies, timings that led to success
2. Identify what FAILED — bottlenecks, wasted time, missed opportunities
3. Extract ACTIONABLE rules — concrete "if X then do Y" patterns
4. Score the overall game performance (0-10)

Focus on patterns that generalize, not one-off flukes.

Respond with JSON (no markdown fences):
{
  "score": 7,
  "what_worked": ["concrete insight 1", "concrete insight 2"],
  "what_failed": ["concrete failure 1", "concrete failure 2"],
  "actionable_rules": [
    "IF condition THEN action",
    "IF condition THEN action"
  ],
  "biggest_mistake": "the single most impactful error",
  "recommended_next_game_strategy": "one paragraph: what to do differently"
}
"""


def run_post_game_analysis(
  memory_dump: dict,
  provider,
  memory_dump_path: str | None = None,
  system_prompt: str | None = None,
  build_prompt_fn=None,
) -> dict | None:
  """Run LLM analysis on a completed game's memory dump.

  Args:
    memory_dump: the full memory dump dict
    provider: an LLM provider instance (analysis model)
    memory_dump_path: path to save learnings alongside
    system_prompt: custom system prompt (uses default if None)
    build_prompt_fn: callable(dump) -> str for custom prompt building

  Returns the analysis dict, or None on failure.
  """
  if build_prompt_fn:
    dump_summary = build_prompt_fn(memory_dump)
  else:
    dump_summary = build_analysis_prompt(memory_dump)

  sys_prompt = system_prompt or DEFAULT_ANALYSIS_SYSTEM_PROMPT
  messages = [{"role": "user", "content": dump_summary}]

  try:
    t0 = time.monotonic()
    resp = provider.complete(sys_prompt, messages, max_tokens=2048)
    latency = (time.monotonic() - t0) * 1000

    analysis = json.loads(resp.text.strip())
    analysis["_meta"] = {
      "model": resp.model,
      "latency_ms": round(latency),
      "input_tokens": resp.input_tokens,
      "output_tokens": resp.output_tokens,
      "game_id": memory_dump.get("meta", {}).get("game_id", "?"),
    }

    if memory_dump_path:
      learnings_path = memory_dump_path.replace("_memory.json", "_learnings.json")
      with open(learnings_path, "w") as f:
        json.dump(analysis, f, indent=2, default=str)
      print(f"  >>> Post-game learnings written to {learnings_path} <<<")

    print_analysis_summary(analysis)
    return analysis

  except Exception as e:
    logger.error("Post-game analysis failed: %s", e)
    return None


def build_analysis_prompt(dump: dict) -> str:
  """Compress the memory dump into a structured analysis prompt."""
  meta = dump.get("meta", {})
  parts = [
    "[GAME SUMMARY]",
    f"Game: {meta.get('game_name', meta.get('mission', '?'))}",
    f"Game ID: {meta.get('game_id', '?')}",
    f"Seed: {meta.get('seed', '?')}",
    f"Final tick: {meta.get('final_tick', '?')}/{meta.get('max_steps', '?')}",
    f"LLM calls: {meta.get('total_llm_calls', 0)}",
    "",
  ]

  wm = dump.get("working_memory", {})
  if wm:
    parts.append("[FINAL STATE]")
    snap = wm.get("snapshot", {})
    if snap:
      for key in ("position", "gear", "hp", "energy", "score"):
        if key in snap:
          parts.append(f"{key}: {snap[key]}")
      hr = snap.get("hub_resources", snap.get("resources", {}))
      if hr:
        parts.append(f"Resources: {json.dumps(hr)}")
    parts.append("")

  directives = dump.get("directive_history", [])
  if directives:
    parts.append(f"[DIRECTIVE HISTORY \u2014 {len(directives)} directives]")
    for d in directives:
      parts.append(
        f"t={d.get('tick')} role={d.get('role')} cmd={d.get('command')} "
        f"target={d.get('target')} | {str(d.get('reasoning', ''))[:100]}"
      )
    parts.append("")

  episodic = dump.get("episodic_memory", [])
  if episodic:
    parts.append(f"[EVENT LOG \u2014 {len(episodic)} events]")
    for ev in episodic[-50:]:
      landmark = " *LANDMARK*" if ev.get("landmark") else ""
      parts.append(f"t={ev.get('tick')} [{ev.get('hall', '?')}] {ev.get('text', '')}{landmark}")
    parts.append("")

  strategic = dump.get("strategic_memory", {})
  if strategic:
    current = strategic.get("current", [])
    if current:
      parts.append(f"[STRATEGIC FACTS \u2014 {len(current)} active]")
      for f in current[-20:]:
        parts.append(f"[{f.get('category')}] {f.get('fact', '')}")
      parts.append("")

  call_log = dump.get("llm_call_log", [])
  if call_log:
    parts.append(f"[LLM CALL LOG \u2014 {len(call_log)} calls]")
    for c in call_log:
      if not isinstance(c, dict):
        continue
      parts.append(
        f"#{c.get('call')} t={c.get('tick')} trigger={c.get('trigger')} "
        f"latency={c.get('latency_ms', 0):.0f}ms | {str(c.get('response', ''))[:80]}"
      )
    parts.append("")

  prior = dump.get("prior_learnings", "")
  if prior:
    parts.append("[PRIOR LEARNINGS USED THIS GAME]")
    parts.append(prior[:500])
    parts.append("")

  return "\n".join(parts)


def print_analysis_summary(analysis: dict) -> None:
  score = analysis.get("score", "?")
  mistake = analysis.get("biggest_mistake", "?")
  print(f"\n  [POST-GAME ANALYSIS] Score: {score}/10")
  print(f"  Biggest mistake: {str(mistake)[:120]}")

  rules = analysis.get("actionable_rules", [])
  if rules:
    print(f"  New rules ({len(rules)}):")
    for r in rules[:3]:
      print(f"    - {str(r)[:100]}")

  meta = analysis.get("_meta", {})
  print(f"  Analysis: {meta.get('latency_ms', 0):.0f}ms, "
        f"{meta.get('input_tokens', 0)}+{meta.get('output_tokens', 0)} tokens")
  print()


def load_learnings_files(runs_dir: str | None = None, max_files: int = 10) -> list[dict]:
  """Load post-game learnings files for cross-game synthesis."""
  if runs_dir is None or not os.path.isdir(runs_dir):
    return []

  results = []
  files = sorted(Path(runs_dir).glob("*_learnings.json"), key=os.path.getmtime, reverse=True)

  for fpath in files[:max_files * 2]:
    try:
      with open(fpath) as f:
        data = json.load(f)
      results.append(data)
      if len(results) >= max_files:
        break
    except (json.JSONDecodeError, KeyError):
      pass

  return results


def synthesize_from_learnings(learnings: list[dict]) -> str:
  """Build a compact cross-game intelligence prompt from prior learnings."""
  if not learnings:
    return ""

  lines = [f"[CROSS-GAME INTELLIGENCE \u2014 {len(learnings)} games analyzed]"]

  scores = [l.get("score", 0) for l in learnings if l.get("score")]
  if scores:
    lines.append(f"Score range: {min(scores)}-{max(scores)}/10 (avg {sum(scores)/len(scores):.1f})")

  latest = learnings[0]
  latest_score = latest.get("score", "?")
  lines.append(f"\n[MOST RECENT GAME \u2014 score {latest_score}/10]")

  for field_name, label in [
    ("biggest_mistake", "Biggest mistake"),
    ("opening_assessment", "Opening"),
    ("recommended_next_game_strategy", "RECOMMENDED STRATEGY"),
  ]:
    val = latest.get(field_name, "")
    if val:
      lines.append(f"{label}: {val}")

  latest_rules = latest.get("actionable_rules", [])
  if latest_rules:
    lines.append("Rules from last game:")
    for rule in latest_rules:
      lines.append(f"  - {rule}")

  all_rules: dict[str, int] = {}
  for l in learnings:
    for rule in l.get("actionable_rules", []):
      key = rule.strip()
      all_rules[key] = all_rules.get(key, 0) + 1

  recurring = {r: c for r, c in all_rules.items() if c >= 2}
  if recurring:
    lines.append(f"\n[PROVEN RULES \u2014 seen across multiple games]")
    for rule, count in sorted(recurring.items(), key=lambda x: -x[1])[:6]:
      lines.append(f"  - {rule} ({count}x)")

  best = max(learnings, key=lambda l: l.get("score", 0))
  if best is not latest:
    rec = best.get("recommended_next_game_strategy", "")
    if rec:
      lines.append(f"\n[BEST GAME STRATEGY \u2014 score {best.get('score', '?')}/10]")
      lines.append(rec)

  return "\n".join(lines)
