"""Self-improving code evolution loop — game-agnostic base.

Provides the str_replace tool executor, git workflow, tool-use loop,
and cross-game memory accumulation. Games provide config via a GameEvolutionConfig.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger("framework.evolution")


@dataclass
class GameEvolutionConfig:
  """Per-game evolution configuration."""
  game_name: str = ""
  editable_files: list[str] = field(default_factory=list)
  system_prompt_template: str = ""
  policy_dir_glob: str = ""

  def format_system_prompt(self, game_id: str = "") -> str:
    return self.system_prompt_template.format(
      editable_files="\n".join(f"   - {f}" for f in self.editable_files),
      game_id=game_id,
      game_name=self.game_name,
    )


STR_REPLACE_TOOL = {
  "name": "str_replace",
  "description": (
    "Replace an exact string in a file. old_str must match EXACTLY "
    "(including whitespace and indentation). The replacement is applied once."
  ),
  "inputSchema": {
    "json": {
      "type": "object",
      "properties": {
        "path": {
          "type": "string",
          "description": "Relative file path from project root",
        },
        "old_str": {
          "type": "string",
          "description": "Exact string to find in the file (must match exactly, including whitespace)",
        },
        "new_str": {
          "type": "string",
          "description": "Replacement string",
        },
      },
      "required": ["path", "old_str", "new_str"],
    }
  },
}


def execute_str_replace(tool_call, root: str, editable_files: set[str]):
  """Execute a str_replace tool call locally. Returns a ToolResult."""
  from .providers import ToolResult

  inp = tool_call.input
  path = inp.get("path", "")
  old_str = inp.get("old_str", "")
  new_str = inp.get("new_str", "")

  if not path:
    return ToolResult(tool_use_id=tool_call.tool_use_id, content="Error: path is required", is_error=True)

  if path not in editable_files:
    return ToolResult(
      tool_use_id=tool_call.tool_use_id,
      content=f"Error: {path} is not in the editable files list",
      is_error=True,
    )

  abs_path = os.path.join(root, path)
  if not os.path.exists(abs_path):
    return ToolResult(
      tool_use_id=tool_call.tool_use_id,
      content=f"Error: file not found: {path}",
      is_error=True,
    )

  try:
    with open(abs_path) as f:
      content = f.read()
  except Exception as e:
    return ToolResult(tool_use_id=tool_call.tool_use_id, content=f"Error reading file: {e}", is_error=True)

  if old_str not in content:
    snippet = old_str[:80].replace("\n", "\\n")
    return ToolResult(
      tool_use_id=tool_call.tool_use_id,
      content=f"Error: old_str not found in {path}. Searched for: {snippet}...",
      is_error=True,
    )

  count = content.count(old_str)
  if count > 1:
    return ToolResult(
      tool_use_id=tool_call.tool_use_id,
      content=f"Error: old_str appears {count} times in {path}. Must be unique.",
      is_error=True,
    )

  new_content = content.replace(old_str, new_str, 1)
  try:
    with open(abs_path, "w") as f:
      f.write(new_content)
  except Exception as e:
    return ToolResult(tool_use_id=tool_call.tool_use_id, content=f"Error writing file: {e}", is_error=True)

  return ToolResult(tool_use_id=tool_call.tool_use_id, content=f"Successfully edited {path}")


def run_tool_use_evolution(
  provider, system_prompt: str, user_prompt: str,
  editable_files: list[str], root: str, log: dict,
) -> None:
  """Execute evolution via Bedrock converse tool-use loop."""
  editable_set = set(editable_files)

  def tool_executor(tc):
    if tc.name == "str_replace":
      result = execute_str_replace(tc, root, editable_set)
      symbol = "FAIL" if result.is_error else "ok"
      print(f"    | [{symbol}] {tc.name}: {tc.input.get('path', '?')} — {result.content[:100]}", flush=True)
      return result
    from .providers import ToolResult
    return ToolResult(tool_use_id=tc.tool_use_id, content=f"Unknown tool: {tc.name}", is_error=True)

  print(f"    Mode: Direct API (tool_use loop)", flush=True)
  print(f"    Model: {provider._model}", flush=True)

  t0 = time.monotonic()
  result = provider.complete_with_tools(
    system=system_prompt,
    messages=[{"role": "user", "content": user_prompt}],
    tools=[STR_REPLACE_TOOL],
    tool_executor=tool_executor,
    max_tokens=4096,
    max_rounds=10,
  )
  elapsed = time.monotonic() - t0

  print(f"    --- Agent finished ({elapsed:.0f}s, {result.rounds} rounds, "
        f"{result.input_tokens + result.output_tokens} tokens) ---", flush=True)

  if result.text:
    print(f"    Summary: {result.text[:200]}", flush=True)

  log["elapsed_s"] = round(elapsed, 1)
  log["rounds"] = result.rounds
  log["input_tokens"] = result.input_tokens
  log["output_tokens"] = result.output_tokens
  log["summary"] = result.text[:500].strip() if result.text else ""
  log["tool_calls"] = len(result.tool_calls_made)


def run_json_evolution(
  provider, system_prompt: str, user_prompt: str,
  editable_files: list[str], root: str, log: dict,
) -> None:
  """Single-shot JSON mode: one API call returns all edits as JSON."""
  print(f"    Mode: Direct API (single-shot JSON)", flush=True)
  print(f"    Model: {provider._model}", flush=True)

  t0 = time.monotonic()
  resp = provider.complete(system=system_prompt, messages=[{"role": "user", "content": user_prompt}], max_tokens=4096)
  elapsed = time.monotonic() - t0

  editable_set = set(editable_files)
  edits_applied = 0
  edits_failed = 0

  try:
    raw_text = resp.text.strip()
    if raw_text.startswith("```"):
      import re
      m = re.match(r"^```(?:json)?\s*\n?(.*?)\n?```\s*$", raw_text, re.DOTALL)
      if m:
        raw_text = m.group(1).strip()

    edits = json.loads(raw_text)
    if not isinstance(edits, list):
      edits = [edits]

    for edit in edits:
      path = edit.get("path", "")
      old_str = edit.get("old_str", "")
      new_str = edit.get("new_str", "")
      reason = edit.get("reason", "")

      if path not in editable_set:
        print(f"    | [FAIL] {path}: not in editable files list", flush=True)
        edits_failed += 1
        continue

      abs_path = os.path.join(root, path)
      if not os.path.exists(abs_path):
        print(f"    | [FAIL] {path}: file not found", flush=True)
        edits_failed += 1
        continue

      with open(abs_path) as f:
        content = f.read()

      if old_str not in content:
        print(f"    | [FAIL] {path}: old_str not found", flush=True)
        edits_failed += 1
        continue

      if content.count(old_str) > 1:
        print(f"    | [FAIL] {path}: old_str not unique", flush=True)
        edits_failed += 1
        continue

      with open(abs_path, "w") as f:
        f.write(content.replace(old_str, new_str, 1))

      print(f"    | [ok] {path}: {reason[:80]}", flush=True)
      edits_applied += 1

  except (json.JSONDecodeError, KeyError, TypeError) as e:
    print(f"    | [FAIL] JSON parse error: {e}", flush=True)
    edits_failed += 1

  print(f"    --- Agent finished ({elapsed:.0f}s, {edits_applied} edits applied, "
        f"{edits_failed} failed) ---", flush=True)

  log["elapsed_s"] = round(elapsed, 1)
  log["rounds"] = 1
  log["input_tokens"] = resp.input_tokens
  log["output_tokens"] = resp.output_tokens
  log["summary"] = f"{edits_applied} edits applied, {edits_failed} failed"
  log["tool_calls"] = edits_applied + edits_failed


# ── Git operations ────────────────────────────────────────────────────

def git(cwd: str, *args: str) -> str:
  result = subprocess.run(
    ["git", *args],
    cwd=cwd, capture_output=True, text=True, timeout=30,
  )
  if result.returncode != 0:
    raise RuntimeError(f"git {' '.join(args)} failed: {result.stderr.strip()}")
  return result.stdout


def commit_and_track(
  root: str, game_id: str, score, mistake, strategy, rules: list,
  files_edited: list, current_branch: str, pr_title_prefix: str | None,
  log: dict, policy_dir_glob: str = "policies/",
) -> None:
  """Commit edits, push to remote evolution branch, create/merge PR."""
  git(root, "add", "--", policy_dir_glob)
  commit_msg = f"evolution({game_id}): score {score}/10\n\n{str(mistake)[:200]}"
  git(root, "commit", "-m", commit_msg)

  remote_branch = f"evolution/{game_id}"
  try:
    git(root, "push", "origin", f"HEAD:refs/heads/{remote_branch}", "--force")

    pr_body = build_pr_body(game_id, score, mistake, strategy, rules, files_edited, log)
    pr_title = (f"{pr_title_prefix} \u2014 {str(mistake)[:60]}" if pr_title_prefix
                else f"evolution({game_id}): {str(mistake)[:60]}")
    pr_url = create_pr(root, remote_branch, current_branch, title=pr_title, body=pr_body)
    log["pr_url"] = pr_url

    if pr_url:
      pr_num = pr_url.rstrip("/").split("/")[-1]
      try:
        merge_result = subprocess.run(
          ["gh", "pr", "merge", pr_num, "--rebase", "--delete-branch"],
          cwd=root, capture_output=True, text=True, timeout=30,
        )
        if merge_result.returncode == 0:
          print(f"    PR #{pr_num} merged (tracking)", flush=True)
          log["merged"] = True
          try:
            git(root, "pull", "--rebase", "origin", current_branch)
          except Exception:
            pass
        else:
          log["merged"] = False
      except Exception:
        log["merged"] = False
  except Exception as e:
    logger.warning("Remote PR tracking failed: %s", e)
    log["pr_url"] = None

  try:
    git(root, "pull", "--rebase", "origin", current_branch)
    git(root, "push", "origin", current_branch)
    log["pushed"] = True
  except Exception as e:
    logger.warning("Push to %s failed: %s", current_branch, e)
    log["pushed"] = False


def build_pr_body(
  game_id: str, score, mistake, strategy, rules: list, files: list, log: dict,
) -> str:
  lines = [
    f"## Game {game_id} \u2014 Score {score}/10",
    "",
    f"**Biggest mistake:** {mistake}",
    "",
    f"**Recommended strategy:** {str(strategy)[:300]}",
    "",
    "**Actionable rules:**",
  ]
  for r in rules[:5]:
    lines.append(f"- {r}")
  lines.append("")
  lines.append("**Files changed:**")
  for f in files:
    lines.append(f"- `{f}`")
  lines.append("")
  summary = log.get("summary", "")
  if summary:
    lines.append(f"**Agent summary:** {str(summary)[:500]}")
    lines.append("")
  elapsed = log.get("elapsed_s", 0)
  mode = log.get("mode", "unknown")
  cost = log.get("cost_usd", 0)
  tokens = log.get("input_tokens", 0) + log.get("output_tokens", 0)
  if cost:
    lines.append(f"*Evolution: {elapsed:.0f}s, ${cost:.2f} ({mode})*")
  else:
    lines.append(f"*Evolution: {elapsed:.0f}s, {tokens} tokens ({mode})*")
  return "\n".join(lines)


def create_pr(cwd: str, branch: str, base: str, title: str, body: str) -> str | None:
  try:
    result = subprocess.run(
      ["gh", "pr", "create", "--base", base, "--head", branch, "--title", title, "--body", body],
      cwd=cwd, capture_output=True, text=True, timeout=30,
    )
    if result.returncode == 0:
      pr_url = result.stdout.strip()
      print(f"    PR created: {pr_url}")
      return pr_url
    else:
      logger.error("gh pr create failed: %s", result.stderr.strip())
      return None
  except (FileNotFoundError, subprocess.TimeoutExpired) as e:
    logger.error("gh CLI error: %s", e)
    return None


def accumulate_cross_game_memory(learnings: dict, root: str, runs_subdir: str = "policies/runs") -> None:
  """Accumulate learnings into persistent cross-game memory."""
  import datetime
  mem_path = os.path.join(root, runs_subdir, "cross_game_memory.json")

  try:
    if os.path.exists(mem_path):
      with open(mem_path) as f:
        memory = json.load(f)
    else:
      memory = {
        "version": 1, "total_games": 0, "recent_scores": [],
        "recurring_failures": [], "successful_strategies": [],
        "failure_counts": {}, "last_updated": "",
      }
  except Exception:
    memory = {
      "version": 1, "total_games": 0, "recent_scores": [],
      "recurring_failures": [], "successful_strategies": [],
      "failure_counts": {}, "last_updated": "",
    }

  memory["total_games"] = memory.get("total_games", 0) + 1

  score = learnings.get("score", 0)
  recent = memory.get("recent_scores", [])
  recent.append(score)
  memory["recent_scores"] = recent[-20:]

  mistake = learnings.get("biggest_mistake", "")
  if mistake:
    failure_key = mistake[:100].strip()
    counts = memory.get("failure_counts", {})
    counts[failure_key] = counts.get(failure_key, 0) + 1
    memory["failure_counts"] = counts
    sorted_failures = sorted(counts.items(), key=lambda x: x[1], reverse=True)
    memory["recurring_failures"] = [f"[{c}x] {f}" for f, c in sorted_failures[:10]]

  strategy = learnings.get("recommended_next_game_strategy", "")
  if strategy and score >= 6:
    successful = memory.get("successful_strategies", [])
    successful.append(strategy[:200])
    memory["successful_strategies"] = successful[-10:]

  rules = learnings.get("actionable_rules", [])
  if rules:
    existing_rules = memory.get("accumulated_rules", [])
    for rule in rules[:3]:
      if rule not in existing_rules:
        existing_rules.append(rule)
    memory["accumulated_rules"] = existing_rules[-30:]

  memory["last_updated"] = datetime.datetime.now().isoformat()

  try:
    os.makedirs(os.path.dirname(mem_path), exist_ok=True)
    with open(mem_path, "w") as f:
      json.dump(memory, f, indent=2, default=str)
  except Exception as e:
    logger.warning("Failed to write cross-game memory: %s", e)
