"""Fast headless eval engine for rapid policy iteration.

Runs `cogames run --format json` as subprocesses with no debug overhead.
Supports single-seed quick evals (~5-15s) and parallel multi-seed evals (~15-30s).
"""

import json
import math
import os
import re
import subprocess
import sys
import threading
import time
import uuid
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from agent_policies.policies.cyborg.cogsguard.cvc_debugger_robot.robot.policy_specs import ROBOT_POLICY_SPEC

POLICIES_DIR = str(Path(__file__).parent.parent)


@dataclass
class EvalResult:
  seed: int
  score: float
  stats: dict
  error: Optional[str] = None
  duration_s: float = 0


@dataclass
class EvalRun:
  id: str
  timestamp: float
  seeds: list[int]
  steps: int
  mission: str
  variant: str
  num_agents: int
  policy: str
  status: str = "running"
  results: list[EvalResult] = field(default_factory=list)
  aggregate: Optional[dict] = None
  diff: Optional[str] = None
  completed: int = 0
  total: int = 0
  duration_s: float = 0


def run_single_eval(
  seed: int,
  steps: int = 2000,
  num_agents: int = 8,
  mission: str = "machina_1",
  variant: str = "talk",
  policy: str = ROBOT_POLICY_SPEC,
) -> EvalResult:
  """Run a single headless eval episode. Returns parsed results. ~5-15s."""
  start = time.monotonic()

  cmd = [
    sys.executable, "-m", "cogames", "run",
    "-m", mission,
    "-c", str(num_agents),
    "-p", policy,
    "-e", "1",
    "-s", str(steps),
    "--seed", str(seed),
    "--action-timeout-ms", "50",
    "--format", "json",
  ]
  if variant:
    cmd.extend(["-v", variant])

  env = {k: v for k, v in os.environ.items() if k != "ROBOT_DEBUG"}

  try:
    proc = subprocess.run(
      cmd,
      capture_output=True,
      text=True,
      timeout=180,
      cwd=POLICIES_DIR,
      env=env,
    )

    duration = time.monotonic() - start

    if proc.returncode != 0:
      return EvalResult(
        seed=seed,
        score=0,
        stats={},
        error=f"exit code {proc.returncode}: {proc.stderr[-500:]}",
        duration_s=duration,
      )

    stdout = proc.stdout
    score = _parse_json_score(stdout)
    if score is not None:
      return EvalResult(seed=seed, score=score, stats={}, duration_s=duration)

    score = _parse_log_score(stdout)
    if score is not None:
      return EvalResult(seed=seed, score=score, stats={}, duration_s=duration)

    return EvalResult(
      seed=seed, score=0, stats={},
      error=f"Could not parse score from output ({len(stdout)} chars)",
      duration_s=duration,
    )

  except subprocess.TimeoutExpired:
    return EvalResult(
      seed=seed, score=0, stats={},
      error="timeout (180s)",
      duration_s=time.monotonic() - start,
    )
  except Exception as e:
    return EvalResult(
      seed=seed, score=0, stats={},
      error=str(e),
      duration_s=time.monotonic() - start,
    )


def _parse_json_score(stdout: str) -> Optional[float]:
  """Try to extract score from JSON output of cogames run --format json."""
  try:
    json_start = stdout.rfind('\n{')
    if json_start >= 0:
      text = stdout[json_start + 1:]
    elif stdout.lstrip()[:1] == '{':
      text = stdout.lstrip()
    else:
      json_start = stdout.find('{')
      if json_start < 0:
        return None
      text = stdout[json_start:]

    data = json.loads(text)
    missions = data.get("missions", [])
    if not missions:
      return None

    summary = missions[0].get("mission_summary", {})
    rewards = summary.get("per_episode_per_policy_avg_rewards", {})
    episode_rewards = rewards.get("0", [0])
    score = episode_rewards[0] if episode_rewards else 0
    if score is None:
      score = 0
    return round(float(score), 4)
  except (json.JSONDecodeError, ValueError, KeyError, IndexError, TypeError):
    return None


def _parse_log_score(stdout: str) -> Optional[float]:
  """Fallback: extract score from 'per cog' or reward lines in log output."""
  for line in reversed(stdout.split('\n')):
    lower = line.lower()
    if 'per cog' in lower or 'avg_reward' in lower or 'per_policy_avg_rewards' in lower:
      nums = re.findall(r'[-+]?\d*\.?\d+', line)
      if nums:
        try:
          return round(float(nums[-1]), 4)
        except ValueError:
          continue
  return None


def _compute_aggregate(results: list[EvalResult]) -> dict:
  scores = [r.score for r in results if r.error is None]
  if not scores:
    return {"mean": 0, "stdev": 0, "min": 0, "max": 0, "n": 0}
  mean = sum(scores) / len(scores)
  variance = sum((s - mean) ** 2 for s in scores) / len(scores) if len(scores) > 1 else 0
  return {
    "mean": round(mean, 3),
    "stdev": round(math.sqrt(variance), 3),
    "min": round(min(scores), 3),
    "max": round(max(scores), 3),
    "n": len(scores),
  }


def run_multi_seed_eval(
  seeds: list[int],
  steps: int = 2000,
  num_agents: int = 8,
  mission: str = "machina_1",
  variant: str = "talk",
  policy: str = ROBOT_POLICY_SPEC,
  on_progress: Optional[callable] = None,
) -> EvalRun:
  """Run evals across seeds in parallel. Returns aggregated results."""
  eval_id = str(uuid.uuid4())[:8]
  start = time.monotonic()

  run = EvalRun(
    id=eval_id,
    timestamp=time.time(),
    seeds=seeds,
    steps=steps,
    mission=mission,
    variant=variant,
    num_agents=num_agents,
    policy=policy,
    total=len(seeds),
  )

  max_workers = min(len(seeds), 5)

  with ProcessPoolExecutor(max_workers=max_workers) as pool:
    futures = {
      pool.submit(run_single_eval, seed, steps, num_agents, mission, variant, policy): seed
      for seed in seeds
    }

    for future in as_completed(futures):
      result = future.result()
      run.results.append(result)
      run.completed += 1
      if on_progress:
        on_progress(run)

  run.results.sort(key=lambda r: r.seed)
  run.aggregate = _compute_aggregate(run.results)
  run.duration_s = time.monotonic() - start
  run.status = "completed"

  return run


class EvalEngine:
  """Manages eval runs with history tracking."""

  def __init__(self):
    self._lock = threading.Lock()
    self._history: list[EvalRun] = []
    self._running: Optional[EvalRun] = None

  def quick_eval(
    self,
    seed: int = 42,
    steps: int = 2000,
    mission: str = "machina_1",
    variant: str = "talk",
    num_agents: int = 8,
    policy: str = ROBOT_POLICY_SPEC,
  ) -> EvalResult:
    """Run a single quick eval synchronously."""
    return run_single_eval(seed, steps, num_agents, mission, variant, policy)

  def full_eval(
    self,
    seeds: Optional[list[int]] = None,
    steps: int = 2000,
    mission: str = "machina_1",
    variant: str = "talk",
    num_agents: int = 8,
    policy: str = ROBOT_POLICY_SPEC,
    diff: Optional[str] = None,
  ) -> EvalRun:
    """Run multi-seed eval synchronously. Stores result in history."""
    if seeds is None:
      seeds = [42, 123, 456, 789, 1337]

    run = run_multi_seed_eval(seeds, steps, num_agents, mission, variant, policy)
    run.diff = diff

    with self._lock:
      self._history.append(run)

    return run

  def get_history(self) -> list[dict]:
    with self._lock:
      return [_run_to_dict(r) for r in reversed(self._history)]

  def get_baseline(self) -> Optional[dict]:
    with self._lock:
      if not self._history:
        return None
      return _run_to_dict(self._history[0])

  def get_latest(self) -> Optional[dict]:
    with self._lock:
      if not self._history:
        return None
      return _run_to_dict(self._history[-1])


def _result_to_dict(r: EvalResult) -> dict:
  return {
    "seed": r.seed,
    "score": r.score,
    "error": r.error,
    "duration_s": round(r.duration_s, 1),
    "stats": r.stats,
  }


def _run_to_dict(r: EvalRun) -> dict:
  return {
    "id": r.id,
    "timestamp": r.timestamp,
    "seeds": r.seeds,
    "steps": r.steps,
    "mission": r.mission,
    "variant": r.variant,
    "num_agents": r.num_agents,
    "policy": r.policy,
    "status": r.status,
    "results": [_result_to_dict(res) for res in r.results],
    "aggregate": r.aggregate,
    "diff": r.diff,
    "completed": r.completed,
    "total": r.total,
    "duration_s": round(r.duration_s, 1),
  }
