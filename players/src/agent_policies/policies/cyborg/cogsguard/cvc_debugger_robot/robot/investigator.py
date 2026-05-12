"""AI-powered game moment investigator.

Given a tick and optional agent_id, pulls surrounding context from the hub,
constructs a prompt, and sends it to an LLM for analysis. Returns a structured
investigation with narrative, root cause, and suggested fix.

Uses OpenRouter API (same as llm_coordinator.py).
"""

from __future__ import annotations

import json
import os
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
  from agent_policies.policies.cyborg.cogsguard.cvc_debugger_robot.robot.observability import ObservabilityHub


SYSTEM_PROMPT = """You are an expert AI debugger analyzing a game replay from "Cogs vs Clips" — a territory-control game where robot agents (Cogs) compete against automated opponents (Clips) on a grid-based map.

Roles:
- Miner: gathers resources (carbon, oxygen, germanium, silicon) from extractors and deposits at hub
- Aligner: collects hearts from hub and captures neutral junctions
- Scrambler: collects hearts and neutralizes enemy junctions

Key signals:
- congestion_ticks: 0-15, hitting 15 means forced explore (agent is stuck)
- nav_status: STUCK/UNREACHABLE = pathfinding failure
- death with low HP = agent was killed in hostile territory
- has_heart + no nav_target = carrying heart with nowhere to go
- gearless = agent lost gear (died and respawned)

You will be given tick-by-tick state for agents around a specific moment. Analyze what happened and why.

Respond in JSON:
{
  "narrative": "2-4 sentence plain-English description of what happened at this moment",
  "root_cause": "1-2 sentence hypothesis for WHY this behavior occurred",
  "suggested_fix": "optional: 1-2 sentence description of a code change that would prevent this",
  "code_diff": "optional: a minimal Python code snippet showing the fix (before/after)"
}"""


class Investigator:
  """Sends investigation requests to an LLM and returns structured analysis."""

  def __init__(self, hub: ObservabilityHub):
    self.hub = hub
    self._api_key = os.environ.get("OPENROUTER_API_KEY", os.environ.get("OPENAI_API_KEY", ""))
    self._base_url = os.environ.get("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
    self._model = os.environ.get("INVESTIGATOR_MODEL", "anthropic/claude-sonnet-4")

  def investigate(
    self,
    tick: int,
    agent_id: int | None = None,
    question: str | None = None,
  ) -> dict:
    """Investigate a specific game moment. Returns structured analysis."""
    context = self._gather_context(tick, agent_id)
    if not context:
      return {
        "narrative": "No game data available for this tick.",
        "root_cause": "No tick history found in the hub.",
        "suggested_fix": None,
        "code_diff": None,
      }

    user_prompt = self._build_prompt(tick, agent_id, question, context)

    try:
      result = self._call_llm(user_prompt)
      return result
    except Exception as e:
      return {
        "narrative": f"Investigation failed: {e}",
        "root_cause": "LLM API error",
        "suggested_fix": None,
        "code_diff": None,
      }

  def _gather_context(self, tick: int, agent_id: int | None) -> list[dict]:
    """Pull surrounding tick data from the hub."""
    all_agents = self.hub.get_all_agents()
    if not all_agents:
      return []

    context = []
    agent_ids = [agent_id] if agent_id is not None else list(all_agents.keys())

    for aid in agent_ids:
      history = self.hub.get_history(aid, 300)
      if not history:
        continue

      window = [t for t in history if abs(t.get("tick", 0) - tick) <= 50]
      if not window:
        closest = min(history, key=lambda t: abs(t.get("tick", 0) - tick))
        window = [closest]

      for t in window:
        context.append({
          "agent_id": t.get("agent_id"),
          "tick": t.get("tick"),
          "position": t.get("position"),
          "role": t.get("role"),
          "gear": t.get("gear"),
          "hp": t.get("hp"),
          "energy": t.get("energy"),
          "cargo_total": t.get("cargo_total"),
          "has_heart": t.get("has_heart"),
          "nav_status": t.get("nav_status"),
          "nav_target": t.get("nav_target"),
          "nav_distance": t.get("nav_distance"),
          "threat_level": t.get("threat_level"),
          "enemy_count": t.get("enemy_count"),
          "action": t.get("action"),
          "active_command": t.get("active_command"),
          "in_friendly_territory": t.get("in_friendly_territory"),
          "brain": t.get("brain"),
          "phase": t.get("phase"),
        })

    context.sort(key=lambda t: (t.get("tick", 0), t.get("agent_id", 0)))
    return context[:100]

  def _build_prompt(
    self,
    tick: int,
    agent_id: int | None,
    question: str | None,
    context: list[dict],
  ) -> str:
    parts = [f"Investigating tick {tick}"]
    if agent_id is not None:
      parts.append(f" for agent {agent_id}")
    parts.append(".\n\n")

    if question:
      parts.append(f"User question: {question}\n\n")

    parts.append("Tick-by-tick context (surrounding ticks):\n")
    parts.append(json.dumps(context, indent=2, default=str))

    return "".join(parts)

  def _call_llm(self, user_prompt: str) -> dict:
    """Call the LLM API and parse the response."""
    import httpx

    headers = {
      "Authorization": f"Bearer {self._api_key}",
      "Content-Type": "application/json",
    }

    payload = {
      "model": self._model,
      "messages": [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
      ],
      "temperature": 0,
      "response_format": {"type": "json_object"},
    }

    with httpx.Client(timeout=60.0) as client:
      resp = client.post(
        f"{self._base_url}/chat/completions",
        headers=headers,
        json=payload,
      )
      resp.raise_for_status()
      data = resp.json()

    content = data["choices"][0]["message"]["content"]

    try:
      result = json.loads(content)
    except json.JSONDecodeError:
      idx = content.find("{")
      if idx >= 0:
        result = json.loads(content[idx:])
      else:
        result = {
          "narrative": content,
          "root_cause": "Could not parse structured response",
          "suggested_fix": None,
          "code_diff": None,
        }

    return {
      "narrative": result.get("narrative", ""),
      "root_cause": result.get("root_cause", ""),
      "suggested_fix": result.get("suggested_fix"),
      "code_diff": result.get("code_diff"),
    }
