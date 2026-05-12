"""Per-agent LLM tactical advisor for miner agents.

Each miner agent gets its own LLMCoordinator instance that periodically
consults Claude Opus 4.6 (via OpenRouter) to decide whether the agent
should switch from mining to capturing/scrambling a junction.

The coordinator only sees THIS agent's WorldSnapshot -- no shared state.

Usage:
  Activated by passing llm_model to RobotPolicy:
    class=robot.RobotPolicy,kw.llm_model=anthropic/claude-opus-4.6
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

try:
  from dotenv import load_dotenv
except ModuleNotFoundError:
  load_dotenv = None

from agent_policies.policies.cyborg.cogsguard.cvc_debugger_robot.robot.types import Coord, manhattan

logger = logging.getLogger("robot.llm_coordinator")

VALID_STEP_ACTIONS = frozenset({
  "switch_gear", "collect_heart", "capture_junction",
  "scramble_junction", "explore_area",
})

import re
_CODE_FENCE_RE = re.compile(r"^```(?:json)?\s*\n?(.*?)\n?```\s*$", re.DOTALL)

CONSULT_INTERVAL_DEFAULT = 300
MIN_CONSULT_GAP = 100
BUDGET_DEFAULT = 7
FIRST_CONSULT_TICK = 50


@dataclass
class DirectiveStep:
  action: str
  target: Coord | None = None
  params: dict = field(default_factory=dict)

  def to_dict(self) -> dict:
    d: dict = {"action": self.action}
    if self.target is not None:
      d["target"] = list(self.target)
    if self.params:
      d["params"] = self.params
    return d


@dataclass
class FlexDirective:
  steps: list[DirectiveStep]
  reasoning: str
  issued_tick: int
  current_step: int = 0

  @property
  def active_step(self) -> DirectiveStep | None:
    if self.current_step < len(self.steps):
      return self.steps[self.current_step]
    return None

  @property
  def is_complete(self) -> bool:
    return self.current_step >= len(self.steps)

  def advance(self) -> None:
    self.current_step += 1

  def summary(self) -> str:
    if not self.steps:
      return "keep_mining"
    actions = []
    for i, s in enumerate(self.steps):
      mark = ">>>" if i == self.current_step else "   "
      t = f"@{s.target}" if s.target else ""
      p = f" {s.params}" if s.params else ""
      actions.append(f"{mark} {s.action}{t}{p}")
    status = "complete" if self.is_complete else f"step {self.current_step + 1}/{len(self.steps)}"
    return f"[{status}]\n" + "\n".join(actions)

  def to_dict(self) -> dict:
    return {
      "steps": [s.to_dict() for s in self.steps],
      "reasoning": self.reasoning,
      "issued_tick": self.issued_tick,
      "current_step": self.current_step,
      "is_complete": self.is_complete,
    }


_SYSTEM_PROMPT_TEMPLATE = """\
You are a tactical advisor for a single miner agent in the Cogs vs Clips game.

## Game Overview
- Your team has {num_agents} agents on a {grid_size} grid, game lasts {max_steps} ticks
- SCORE = junctions held * time held. Junctions captured EARLY compound score
- You advise ONE miner. Other agents (aligners, scramblers) act autonomously

## Roles
- **Miner** (you): Gathers resources at extractors, deposits at hub -> hearts
- **Aligner**: Uses 1 heart to capture a neutral junction (must be "alignable")
- **Scrambler**: Uses 1 heart to neutralize an enemy junction

## Key Mechanics
- Hearts require 7 of each of 4 elements deposited at hub
- Junctions project territory (AOE = HP/energy regen)
- After you finish a capture/scramble, you continue autonomously in that role for ~100 ticks before reverting to miner -- one directive often leads to 2-3 autonomous captures

## Your Job
Decide whether THIS miner should keep mining or take a special action.
Return empty steps to keep mining (the default correct choice).

capture_junction and scramble_junction auto-handle gear switching and heart collection.

## Response Format
```json
{{
  "steps": [{{"action": "capture_junction", "target": [row, col]}}],
  "reasoning": "brief explanation"
}}
```

To keep mining, return empty steps:
```json
{{
  "steps": [],
  "reasoning": "no actionable targets nearby"
}}
```

## Valid Actions
| Action | Target | Effect |
|--------|--------|--------|
| capture_junction | [row, col] | Capture neutral alignable junction (auto gear+heart) |
| scramble_junction | [row, col] | Neutralize enemy junction (auto gear+heart) |
| explore_area | [row, col] | Move to area (complete within 3 tiles) |

## Decision Rules
1. ACT only if a neutral alignable junction or enemy junction is nearby (distance < {close_threshold})
2. PREFER acting when aligners/scramblers are far away or heartless
3. Do NOT act if distance > {max_mission_dist} -- travel wastes too many ticks
4. Do NOT act if you have cargo > 0 -- deposit first
5. PREFER targets you are close to (minimize travel)
6. Gear switching requires travel to hub area. Only act if hub_dist < {hub_close} or you already have the right gear
7. Total mission cost = hub_dist + hub->junction distance. If > {max_total_cost}, too expensive
8. Mining is the DEFAULT correct choice. Only intervene when clearly beneficial
"""


class LLMCoordinator:
  """Per-agent tactical advisor that issues directives to a single miner."""

  def __init__(
    self,
    agent_id: int,
    model: str = "anthropic/claude-opus-4.6",
    budget: int = BUDGET_DEFAULT,
    consult_interval: int = CONSULT_INTERVAL_DEFAULT,
    obs_hub=None,
    num_agents: int = 4,
    max_steps: int = 10000,
  ):
    self._agent_id = agent_id
    self._model = model
    self._budget = budget
    self._consult_interval = consult_interval
    self._obs_hub = obs_hub
    self._num_agents = num_agents
    self._max_steps = max_steps
    self._inferred_grid_size: str | None = None
    self._calls_made = 0
    self._last_consult_tick = -consult_interval
    self._directive: FlexDirective | None = None
    self._call_log: list[dict] = []
    self._last_phase: str | None = None
    self._last_junction_counts: dict[str, int] = {}
    self._peak_own_junctions: int = 0
    self._peak_enemy_junctions: int = 0
    self._total_tokens: int = 0
    self._total_cost: float = 0.0
    self._client = None
    self._system_prompt_cache: str | None = None

    if load_dotenv is not None:
      env_path = Path(__file__).resolve().parent.parent / ".env.local"
      if env_path.exists():
        load_dotenv(env_path)

  def _get_client(self):
    if self._client is None:
      from openai import OpenAI
      api_key = os.getenv("OPENROUTER_API_KEY")
      if not api_key:
        logger.error("OPENROUTER_API_KEY not set")
        return None
      self._client = OpenAI(
        base_url="https://openrouter.ai/api/v1",
        api_key=api_key,
      )
    return self._client

  @property
  def directive(self) -> FlexDirective | None:
    return self._directive

  def get_call_log(self) -> list[dict]:
    return list(self._call_log)

  def get_stats(self) -> dict:
    return {
      "agent_id": self._agent_id,
      "calls_made": self._calls_made,
      "budget": self._budget,
      "total_tokens": self._total_tokens,
      "total_cost_usd": round(self._total_cost, 4),
      "model": self._model,
    }

  def _infer_grid_size(self, snapshot) -> str:
    if self._inferred_grid_size is not None:
      return self._inferred_grid_size

    max_r, max_c = 0, 0
    r, c = snapshot.position
    max_r, max_c = max(max_r, abs(r)), max(max_c, abs(c))
    for e in snapshot.nearby_entities:
      r, c = e.position
      max_r, max_c = max(max_r, abs(r)), max(max_c, abs(c))
    for j in snapshot.known_junctions:
      r, c = j.position
      max_r, max_c = max(max_r, abs(r)), max(max_c, abs(c))

    if max_r > 10 or max_c > 10:
      self._inferred_grid_size = f"~{max_r + 10}x{max_c + 10}"
    return self._inferred_grid_size or "unknown"

  def _build_system_prompt(self, snapshot) -> str:
    if self._system_prompt_cache is not None:
      return self._system_prompt_cache

    grid_size = self._infer_grid_size(snapshot)
    grid_dim = 88
    try:
      dim_str = grid_size.replace("~", "").split("x")[0]
      grid_dim = int(dim_str)
    except (ValueError, IndexError):
      pass

    scale = grid_dim / 88.0
    close_threshold = max(10, round(20 * scale))
    max_mission_dist = max(15, round(30 * scale))
    hub_close = max(8, round(15 * scale))
    max_total_cost = max(20, round(40 * scale))

    prompt = _SYSTEM_PROMPT_TEMPLATE.format(
      num_agents=self._num_agents,
      grid_size=grid_size,
      max_steps=self._max_steps,
      close_threshold=close_threshold,
      max_mission_dist=max_mission_dist,
      hub_close=hub_close,
      max_total_cost=max_total_cost,
    )
    self._system_prompt_cache = prompt
    return prompt

  def maybe_consult(self, tick: int, snapshot, brain_state: dict) -> None:
    if self._calls_made >= self._budget:
      return
    if tick < FIRST_CONSULT_TICK:
      return

    if self._directive is not None:
      if not self._directive.is_complete and (tick - self._directive.issued_tick) > 400:
        print(f"  [LLM A{self._agent_id}] Directive EXPIRED after 400 ticks "
              f"(issued t={self._directive.issued_tick}, "
              f"step {self._directive.current_step + 1}/{len(self._directive.steps)})",
              flush=True)
        self._directive = None
      elif self._directive.is_complete:
        self._directive = None

    if tick - self._last_consult_tick < MIN_CONSULT_GAP:
      return

    trigger = self._check_trigger(tick, snapshot)
    if trigger is None:
      return

    self._calls_made += 1
    self._last_consult_tick = tick

    result = self._consult_sync(tick, snapshot, brain_state, trigger)
    if result is not None:
      new_directive, record = result

      usage = record.get("usage")
      if usage:
        self._total_tokens += usage.get("total_tokens", 0)
        self._total_cost += record.get("cost_usd", 0)

      if new_directive is not None:
        self._directive = new_directive

      self._call_log.append(record)
      self._log_to_console(record)
      if self._obs_hub is not None:
        try:
          self._obs_hub.push_llm_call(record)
        except Exception:
          pass

  def _check_trigger(self, tick: int, snapshot) -> str | None:
    if tick - self._last_consult_tick >= self._consult_interval:
      return "periodic"

    phase = snapshot.phase
    if phase != self._last_phase and self._last_phase is not None:
      self._last_phase = phase
      return f"phase_change:{phase}"
    self._last_phase = phase

    junction_counts = {"own": 0, "neutral_alignable": 0, "enemy": 0}
    for j in snapshot.known_junctions:
      if j.owner == "own":
        junction_counts["own"] += 1
      elif j.owner == "neutral" and j.alignable:
        junction_counts["neutral_alignable"] += 1
      elif j.owner in ("enemy", "clips"):
        junction_counts["enemy"] += 1

    cur_own = junction_counts["own"]
    cur_enemy = junction_counts["enemy"]
    cur_neutral = junction_counts["neutral_alignable"]
    self._peak_own_junctions = max(self._peak_own_junctions, cur_own)
    self._peak_enemy_junctions = max(self._peak_enemy_junctions, cur_enemy)

    if self._last_junction_counts:
      if cur_enemy > self._peak_enemy_junctions - 1 and cur_enemy > self._last_junction_counts.get("enemy", 0):
        self._last_junction_counts = junction_counts
        return "reactive:new_enemy_junction"

      prev_own = self._last_junction_counts.get("own", 0)
      if cur_own < prev_own and cur_own < self._peak_own_junctions:
        self._last_junction_counts = junction_counts
        return "reactive:lost_junction"

      prev_neutral = self._last_junction_counts.get("neutral_alignable", 0)
      if cur_neutral > prev_neutral and cur_neutral >= 2:
        self._last_junction_counts = junction_counts
        return "reactive:new_alignable_junctions"

    self._last_junction_counts = junction_counts
    return None

  def _consult_sync(
    self,
    tick: int,
    snapshot,
    brain_state: dict,
    trigger: str,
  ) -> tuple[FlexDirective | None, dict] | None:
    client = self._get_client()
    if client is None:
      return None

    user_prompt = self._build_user_prompt(tick, snapshot, brain_state)
    call_number = self._calls_made

    system_prompt = self._build_system_prompt(snapshot)

    record = {
      "tick": tick,
      "call_number": call_number,
      "agent_id": self._agent_id,
      "trigger": trigger,
      "model": self._model,
      "system_prompt": system_prompt,
      "prompt_summary": user_prompt[:500],
      "full_prompt": user_prompt,
      "raw_response": "",
      "parsed_action": "",
      "parsed_directives": {},
      "reasoning": "",
      "latency_ms": 0,
      "error": None,
    }

    new_directive: FlexDirective | None = None
    t0 = time.monotonic()
    try:
      response = client.chat.completions.create(
        model=self._model,
        messages=[
          {"role": "system", "content": system_prompt},
          {"role": "user", "content": user_prompt},
        ],
        response_format={"type": "json_object"},
        temperature=0,
        timeout=30,
      )
      raw = response.choices[0].message.content or "{}"
      m = _CODE_FENCE_RE.match(raw.strip())
      if m:
        raw = m.group(1).strip()
      record["raw_response"] = raw
      record["latency_ms"] = round((time.monotonic() - t0) * 1000)

      usage = getattr(response, 'usage', None)
      if usage:
        record["usage"] = {
          "prompt_tokens": getattr(usage, 'prompt_tokens', 0) or 0,
          "completion_tokens": getattr(usage, 'completion_tokens', 0) or 0,
          "total_tokens": getattr(usage, 'total_tokens', 0) or 0,
        }
        record["cost_usd"] = round(
          (record["usage"]["prompt_tokens"] * 15
           + record["usage"]["completion_tokens"] * 75) / 1_000_000, 6
        )

      try:
        data = json.loads(raw)
      except json.JSONDecodeError:
        decoder = json.JSONDecoder()
        data, _ = decoder.raw_decode(raw.strip())
        record["parse_note"] = "used raw_decode to extract first JSON object"

      reasoning = data.get("reasoning", "")
      record["reasoning"] = reasoning

      steps_raw = data.get("steps", [])
      if not steps_raw:
        record["parsed_action"] = "keep_mining"
      else:
        steps = self._parse_steps(steps_raw)
        if steps:
          new_directive = FlexDirective(
            steps=steps,
            reasoning=reasoning,
            issued_tick=tick,
          )
          record["parsed_action"] = steps[0].action
          record["parsed_directives"] = new_directive.to_dict()
        else:
          record["parsed_action"] = "keep_mining"
          record["parse_note"] = "all steps invalid"

    except Exception as e:
      record["latency_ms"] = round((time.monotonic() - t0) * 1000)
      record["error"] = str(e)
      logger.error("LLM call failed (A%d): %s", self._agent_id, e)

    return (new_directive, record)

  def _parse_steps(self, steps_raw: list[dict]) -> list[DirectiveStep]:
    steps: list[DirectiveStep] = []
    for s in steps_raw:
      action = s.get("action", "")
      if action not in VALID_STEP_ACTIONS:
        continue
      target = None
      raw_target = s.get("target")
      if raw_target and isinstance(raw_target, (list, tuple)) and len(raw_target) == 2:
        try:
          target = (int(raw_target[0]), int(raw_target[1]))
        except (ValueError, TypeError):
          pass
      params = s.get("params", {})
      if not isinstance(params, dict):
        params = {}
      steps.append(DirectiveStep(action=action, target=target, params=params))
    return steps

  def _build_user_prompt(self, tick: int, snapshot, brain_state: dict) -> str:
    max_steps = snapshot.max_steps
    phase = snapshot.phase
    ss = snapshot.self_state

    hub_pos = None
    for e in snapshot.nearby_entities:
      if 'type:hub' in e.tags:
        hub_pos = e.position
        break
    if hub_pos is None:
      hub_pos = snapshot.shared_hub or (0, 0)

    hub_dist = manhattan(snapshot.position, hub_pos)

    lines = [f"Tick {tick}/{max_steps} (phase: {phase}), hub~{hub_pos}", ""]

    # This agent's state
    lines.append("== Your Status (Miner) ==")
    parts = [f"agent_id={self._agent_id}", f"pos={snapshot.position}"]
    gear = ss.gear or "none"
    parts.append(f"gear={gear}")
    if ss.has_heart:
      parts.append(f"heart={ss.heart_count}")
    if ss.cargo_total > 0:
      cargo_str = "+".join(f"{v}{k[0]}" for k, v in ss.cargo.items() if v > 0)
      parts.append(f"cargo={ss.cargo_total}({cargo_str})")
    parts.append(f"hub_dist={hub_dist}")
    parts.append(f"hp={ss.hp}")

    if snapshot.active_command:
      parts.append(f"doing=\"{snapshot.active_command.reason}\"")

    if brain_state.get("deposit_count"):
      parts.append(f"deposits={brain_state['deposit_count']}")

    if self._directive and not self._directive.is_complete:
      step = self._directive.active_step
      step_desc = f"{step.action}" + (f"@{step.target}" if step.target else "") if step else "?"
      parts.append(f"active_directive={self._directive.current_step + 1}/{len(self._directive.steps)}:{step_desc}")
    else:
      parts.append("directive=none")

    lines.append(" | ".join(parts))

    # Teammates (from snapshot.teammates -- what we know via talk)
    if snapshot.teammates:
      lines.append("")
      lines.append("== Known Teammates ==")
      for aid, role in sorted(snapshot.teammates.items()):
        teammate_pos = None
        if snapshot.teammate_positions:
          idx = list(snapshot.teammates.keys()).index(aid)
          if idx < len(snapshot.teammate_positions):
            teammate_pos = snapshot.teammate_positions[idx]
        pos_str = f"pos={teammate_pos}" if teammate_pos else "pos=unknown"
        lines.append(f"[A{aid} {role}] {pos_str}")

    # Junctions visible to this agent
    lines.append("")
    lines.append("== Junctions ==")
    own = []
    neutral_alignable = []
    neutral_other = []
    enemy = []
    for j in snapshot.known_junctions:
      pos_str = f"({j.position[0]},{j.position[1]})"
      dist = manhattan(snapshot.position, j.position)
      if j.owner == "own":
        own.append(pos_str)
      elif j.owner == "neutral" and j.alignable:
        neutral_alignable.append(f"{pos_str} [d={dist}]")
      elif j.owner == "neutral":
        neutral_other.append(pos_str)
      elif j.owner in ("enemy", "clips"):
        enemy.append(f"{pos_str} [d={dist}]")

    lines.append(f"Own ({len(own)}): {', '.join(own) or 'none'}")
    lines.append(f"Neutral alignable ({len(neutral_alignable)}): {', '.join(neutral_alignable) or 'none'}")
    lines.append(f"Neutral other ({len(neutral_other)}): {', '.join(neutral_other) or 'none'}")
    lines.append(f"Enemy ({len(enemy)}): {', '.join(enemy) or 'none'}")

    # Previous directive result
    if self._call_log:
      last = self._call_log[-1]
      lines.append("")
      lines.append("== Previous Decision ==")
      lines.append(f"Call #{last['call_number']} at tick {last['tick']}: {last.get('reasoning', 'N/A')[:200]}")

    lines.append("")
    lines.append('Respond with JSON: {"steps": [...], "reasoning": "..."}')

    return "\n".join(lines)

  def _log_to_console(self, record: dict) -> None:
    error = record.get("error")
    aid = record.get("agent_id", self._agent_id)
    if error:
      print(f"\n  [LLM A{aid} #{record['call_number']} t={record['tick']}] "
            f"ERROR latency={record['latency_ms']}ms: {error}\n", flush=True)
      return

    action = record.get("parsed_action", "?")
    print(f"\n  [LLM A{aid} #{record['call_number']} t={record['tick']}] "
          f"trigger={record['trigger']} latency={record['latency_ms']}ms -> {action}")

    if action != "keep_mining":
      directives = record.get("parsed_directives", {})
      steps = directives.get("steps", [])
      if steps:
        step_summary = ", ".join(
          s.get("action", "?") + (f"@{s.get('target')}" if s.get("target") else "")
          for s in steps
        )
        print(f"    Steps: [{step_summary}]")

    reasoning = record.get("reasoning", "")
    if reasoning:
      short = reasoning[:200] + ("..." if len(reasoning) > 200 else "")
      print(f"    Reasoning: \"{short}\"")
    print(flush=True)
