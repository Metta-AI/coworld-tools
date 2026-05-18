"""Server-side AI agent for policy editing and eval.

Uses OpenRouter API to chat with an LLM that has tools for reading policy files,
editing them, and running evals. Conversation state is kept in memory per session.
"""

import json
import os
import subprocess
import time
from pathlib import Path
from typing import Optional

ROBOT_DIR = Path(__file__).parent
PROJECT_DIR = ROBOT_DIR.parent

SYSTEM_PROMPT = """You are an expert AI agent for improving robot policies in the "Cogs vs Clips" game.

## Game Context
- Grid-based territory control game: Cogs (your team) vs Clips (automated opponents)
- Roles: miner (gather resources from extractors, deposit at hub), aligner (capture neutral junctions with hearts), scrambler (neutralize enemy junctions)
- Hearts are crafted at the hub from 4 resources (carbon, oxygen, germanium, silicon), 7 of each element = 1 heart
- Junctions control territory. Capturing junctions extends friendly territory.
- Scoring: agents earn reward based on junctions captured, resources gathered, territory controlled

## Policy Architecture
The robot policy lives in `robot/` with these key files:
- `robot/brain.py` (1280 lines) — Core decision engine. `RobotBrain.decide(snapshot)` returns a `MacroCommand`. Role-locked strategies for mining, aligning, scrambling. This is where most behavior bugs live.
- `robot/policy.py` — Control loop: PERCEIVE → LISTEN → UPDATE → DRAFT → SNAPSHOT → DECIDE → EXECUTE → RECORD
- `robot/memory.py` — Spatial memory, entity tracking
- `robot/pathfinding.py` — A* navigation, command execution
- `robot/roster.py` — Role negotiation (DraftBoard), teammate coordination
- `robot/state.py` — WorldSnapshot construction from observations
- `robot/perception.py` — Raw observation parsing

## Key Debugging Signals
- `congestion_ticks` 0-15: agent stuck in same spot. 15 = forced explore (very bad)
- `nav_status: STUCK/UNREACHABLE`: pathfinding failure
- Death spiral: agent dying repeatedly (lost gear, walks into enemy territory)
- Wasted hearts: carrying heart but can't reach a junction
- Resource starvation: miner not depositing for 100+ ticks

## Your Tools
You can read files, edit files, and run evals. When you identify a problem:
1. Read the relevant file to understand the current code
2. Propose and apply a targeted edit
3. Run a quick eval (single seed) to check if it helps
4. Run a full eval (5 seeds) to confirm no regressions

Always explain your reasoning before making edits. Show the before/after.
Keep edits minimal and surgical — change the least code necessary to fix the issue."""


def _tool_read_file(path: str) -> dict:
  target = (PROJECT_DIR / path).resolve()
  if not str(target).startswith(str(PROJECT_DIR.resolve())):
    return {"error": "path outside project"}
  if not target.exists():
    return {"error": f"file not found: {path}"}
  content = target.read_text()
  lines = content.count('\n') + 1
  return {"path": path, "lines": lines, "content": content}


def _tool_edit_file(path: str, old_str: str, new_str: str) -> dict:
  target = (PROJECT_DIR / path).resolve()
  if not str(target).startswith(str(PROJECT_DIR.resolve())):
    return {"error": "path outside project"}
  if not target.exists():
    return {"error": f"file not found: {path}"}
  content = target.read_text()
  if old_str not in content:
    return {"error": "old_str not found in file"}
  if content.count(old_str) > 1:
    return {"error": "old_str is ambiguous (multiple matches)"}
  new_content = content.replace(old_str, new_str, 1)
  target.write_text(new_content)
  return {"ok": True, "path": path}


def _tool_list_files() -> dict:
  files = []
  for f in sorted(ROBOT_DIR.glob("*.py")):
    lines = f.read_text().count('\n') + 1
    files.append({"path": f"robot/{f.name}", "lines": lines})
  return {"files": files}


def _tool_git_diff() -> dict:
  try:
    result = subprocess.run(
      ["git", "diff", "--", "robot/"],
      capture_output=True, text=True, cwd=str(PROJECT_DIR), timeout=10,
    )
    return {"diff": result.stdout or "(no changes)"}
  except Exception as e:
    return {"error": str(e)}


TOOLS = [
  {
    "type": "function",
    "function": {
      "name": "read_file",
      "description": "Read a policy source file",
      "parameters": {
        "type": "object",
        "properties": {
          "path": {"type": "string", "description": "File path relative to project root, e.g. robot/brain.py"}
        },
        "required": ["path"],
      },
    },
  },
  {
    "type": "function",
    "function": {
      "name": "edit_file",
      "description": "Edit a policy file by replacing old_str with new_str. old_str must be unique in the file.",
      "parameters": {
        "type": "object",
        "properties": {
          "path": {"type": "string", "description": "File path relative to project root"},
          "old_str": {"type": "string", "description": "Exact string to find and replace"},
          "new_str": {"type": "string", "description": "Replacement string"},
        },
        "required": ["path", "old_str", "new_str"],
      },
    },
  },
  {
    "type": "function",
    "function": {
      "name": "list_files",
      "description": "List all robot policy Python files with line counts",
      "parameters": {"type": "object", "properties": {}},
    },
  },
  {
    "type": "function",
    "function": {
      "name": "run_eval",
      "description": "Run a headless eval. Use seeds=[42] for quick check, seeds=[42,123,456,789,1337] for full eval.",
      "parameters": {
        "type": "object",
        "properties": {
          "seeds": {
            "type": "array",
            "items": {"type": "integer"},
            "description": "Seeds to evaluate. [42] for quick, [42,123,456,789,1337] for full.",
          },
          "steps": {"type": "integer", "description": "Max ticks per game. Default 1000."},
        },
        "required": ["seeds"],
      },
    },
  },
  {
    "type": "function",
    "function": {
      "name": "git_diff",
      "description": "Show the current git diff of robot/ policy files",
      "parameters": {"type": "object", "properties": {}},
    },
  },
]


def _execute_tool(name: str, args: dict, eval_engine) -> dict:
  if name == "read_file":
    return _tool_read_file(args["path"])
  elif name == "edit_file":
    return _tool_edit_file(args["path"], args["old_str"], args["new_str"])
  elif name == "list_files":
    return _tool_list_files()
  elif name == "run_eval":
    seeds = args.get("seeds", [42])
    steps = args.get("steps", 1000)
    if len(seeds) == 1:
      result = eval_engine.quick_eval(seed=seeds[0], steps=steps)
      return {
        "type": "quick_eval",
        "seed": result.seed,
        "score": result.score,
        "error": result.error,
        "duration_s": round(result.duration_s, 1),
      }
    else:
      run = eval_engine.full_eval(seeds=seeds, steps=steps)
      from policies.cyborg.cogsguard.cvc_debugger_robot.robot.eval_engine import _run_to_dict
      return {"type": "full_eval", **_run_to_dict(run)}
  elif name == "git_diff":
    return _tool_git_diff()
  else:
    return {"error": f"unknown tool: {name}"}


class PolicyAgent:
  """Conversational AI agent for policy editing."""

  def __init__(self, eval_engine):
    self.eval_engine = eval_engine
    self.messages: list[dict] = [{"role": "system", "content": SYSTEM_PROMPT}]
    self._api_key = os.environ.get("OPENROUTER_API_KEY", os.environ.get("OPENAI_API_KEY", ""))
    self._base_url = os.environ.get("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
    self._model = os.environ.get("AGENT_MODEL", "anthropic/claude-sonnet-4")

  def chat(self, user_message: str) -> dict:
    """Process a user message. Returns response with tool calls and text."""
    self.messages.append({"role": "user", "content": user_message})

    response_parts = []
    max_iterations = 10

    for _ in range(max_iterations):
      response = self._call_llm()

      msg = response["choices"][0]["message"]
      self.messages.append(msg)

      tool_calls = msg.get("tool_calls")
      if not tool_calls:
        response_parts.append({"type": "text", "content": msg.get("content", "")})
        break

      if msg.get("content"):
        response_parts.append({"type": "text", "content": msg["content"]})

      for tc in tool_calls:
        fn = tc["function"]
        name = fn["name"]
        try:
          args = json.loads(fn["arguments"])
        except json.JSONDecodeError:
          args = {}

        tool_result = _execute_tool(name, args, self.eval_engine)

        response_parts.append({
          "type": "tool_call",
          "name": name,
          "args": args,
          "result": tool_result,
        })

        result_str = json.dumps(tool_result, default=str)
        if len(result_str) > 8000:
          result_str = result_str[:8000] + "\n... (truncated)"

        self.messages.append({
          "role": "tool",
          "tool_call_id": tc["id"],
          "content": result_str,
        })

    return {"parts": response_parts}

  def _call_llm(self) -> dict:
    import httpx

    headers = {
      "Authorization": f"Bearer {self._api_key}",
      "Content-Type": "application/json",
    }

    payload = {
      "model": self._model,
      "messages": self.messages,
      "tools": TOOLS,
      "temperature": 0,
    }

    with httpx.Client(timeout=120.0) as client:
      resp = client.post(
        f"{self._base_url}/chat/completions",
        headers=headers,
        json=payload,
      )
      resp.raise_for_status()
      return resp.json()
