"""Background game runner and multi-seed eval orchestrator.

Extends the launcher with:
- A game queue (run multiple games sequentially in a background thread)
- Multi-seed eval mode (run N seeds, collect aggregate results)
- Each game/eval gets a unique ID for tracking
- Games are launched as subprocesses via `cogames play` with ROBOT_DEBUG=1
  so tick data streams to the shared observability hub naturally.
"""

from __future__ import annotations

import math
import os
import subprocess
import sys
import threading
import time
import traceback
import uuid
from collections import deque
from dataclasses import dataclass, field
from typing import Any

from robot.observability import ObservabilityHub


@dataclass
class GameRequest:
  id: str
  mission: str = "arena"
  seed: int = 42
  steps: int = 2000
  policy: str = "class=robot.RobotPolicy,kw.debug=true"
  num_agents: int = 4
  variant: str = "talk"
  render: str = "none"
  status: str = "queued"
  result: dict | None = None
  replay_path: str | None = None
  started_at: float | None = None
  completed_at: float | None = None
  pid: int | None = None


@dataclass
class EvalRequest:
  id: str
  policy: str = "class=robot.RobotPolicy,kw.debug=true"
  mission: str = "arena"
  seeds: list[int] = field(default_factory=lambda: [42, 123, 456, 789, 1337])
  steps: int = 2000
  num_agents: int = 4
  variant: str = "talk"
  status: str = "running"
  completed: int = 0
  total: int = 0
  results: list[dict] = field(default_factory=list)
  aggregate: dict | None = None


class GameRunner:
  """Manages a queue of games and eval runs, executing them sequentially."""

  def __init__(self, hub: ObservabilityHub):
    self.hub = hub
    self._queue: deque[GameRequest | EvalRequest] = deque()
    self._lock = threading.Lock()
    self._games: dict[str, GameRequest] = {}
    self._evals: dict[str, EvalRequest] = {}
    self._running = False
    self._thread: threading.Thread | None = None
    self._current_id: str | None = None

  def submit_game(self, params: dict) -> str:
    game_id = str(uuid.uuid4())[:8]
    req = GameRequest(
      id=game_id,
      mission=params.get("mission", params.get("map", "arena")),
      seed=int(params.get("seed", 42)),
      steps=int(params.get("steps", 2000)),
      policy=params.get("policy", "class=robot.RobotPolicy,kw.debug=true"),
      num_agents=int(params.get("num_agents", params.get("players", 4))),
      variant=params.get("variant", "talk"),
      render=params.get("render", "none"),
    )
    with self._lock:
      self._games[game_id] = req
      self._queue.append(req)
    self._ensure_worker()
    return game_id

  def submit_eval(self, params: dict) -> str:
    eval_id = str(uuid.uuid4())[:8]
    seeds = params.get("seeds", [42, 123, 456, 789, 1337])
    req = EvalRequest(
      id=eval_id,
      policy=params.get("policy", "class=robot.RobotPolicy,kw.debug=true"),
      mission=params.get("mission", params.get("map", "arena")),
      seeds=seeds,
      steps=int(params.get("steps", 2000)),
      num_agents=int(params.get("num_agents", params.get("players", 4))),
      variant=params.get("variant", "talk"),
      total=len(seeds),
    )
    with self._lock:
      self._evals[eval_id] = req
      self._queue.append(req)
    self._ensure_worker()
    return eval_id

  def get_game(self, game_id: str) -> dict | None:
    with self._lock:
      g = self._games.get(game_id)
      if not g:
        return None
      return _game_to_dict(g)

  def get_eval(self, eval_id: str) -> dict | None:
    with self._lock:
      e = self._evals.get(eval_id)
      if not e:
        return None
      return _eval_to_dict(e)

  def list_games(self) -> list[dict]:
    with self._lock:
      return [_game_to_dict(g) for g in reversed(list(self._games.values()))]

  def list_evals(self) -> list[dict]:
    with self._lock:
      return [_eval_to_dict(e) for e in reversed(list(self._evals.values()))]

  def _ensure_worker(self) -> None:
    if self._running:
      return
    self._running = True
    self._thread = threading.Thread(target=self._worker, daemon=True, name="game-runner")
    self._thread.start()

  def _worker(self) -> None:
    while True:
      with self._lock:
        if not self._queue:
          self._running = False
          self._current_id = None
          return
        req = self._queue.popleft()

      if isinstance(req, GameRequest):
        self._run_single_game(req)
      elif isinstance(req, EvalRequest):
        self._run_eval(req)

  def _run_single_game(self, req: GameRequest) -> None:
    with self._lock:
      req.status = "running"
      req.started_at = time.time()
      self._current_id = req.id

    self.hub.reset_for_new_game()
    self.hub.set_game_status("running")
    self.hub.set_game_config({
      "game_id": req.id,
      "map": req.mission,
      "max_steps": req.steps,
      "seed": req.seed,
      "num_agents": req.num_agents,
      "policy": req.policy,
    })

    self.hub._broadcast({
      "type": "game_started",
      "game_id": req.id,
      "config": {
        "mission": req.mission,
        "seed": req.seed,
        "steps": req.steps,
        "num_agents": req.num_agents,
        "policy": req.policy,
      },
    })

    try:
      result = _execute_game_subprocess(self.hub, req)
      with self._lock:
        req.status = "completed"
        req.result = result
        req.completed_at = time.time()
      self.hub.set_game_status("finished")
      self.hub.set_game_results(result)
      self.hub._broadcast({
        "type": "game_complete",
        "game_id": req.id,
        "results": result,
      })
    except Exception:
      tb = traceback.format_exc()
      with self._lock:
        req.status = "failed"
        req.result = {"error": tb}
        req.completed_at = time.time()
      self.hub.set_game_status("finished")
      self.hub.set_game_results(req.result)
      self.hub._broadcast({
        "type": "game_complete",
        "game_id": req.id,
        "results": req.result,
      })

  def _run_eval(self, req: EvalRequest) -> None:
    with self._lock:
      req.status = "running"

    for i, seed in enumerate(req.seeds):
      self.hub.reset_for_new_game()
      self.hub.set_game_status("running")
      self.hub.set_game_config({
        "eval_id": req.id,
        "map": req.mission,
        "max_steps": req.steps,
        "seed": seed,
        "num_agents": req.num_agents,
        "policy": req.policy,
      })

      game_req = GameRequest(
        id=f"{req.id}-s{seed}",
        mission=req.mission,
        seed=seed,
        steps=req.steps,
        policy=req.policy,
        num_agents=req.num_agents,
        variant=req.variant,
        render="none",
      )

      try:
        result = _execute_game_subprocess(self.hub, game_req)
        score = result.get("score", result.get("avg_reward", 0))
        seed_result = {
          "seed": seed,
          "score": score,
          "stats": result,
          "replay_path": None,
        }
      except Exception:
        seed_result = {
          "seed": seed,
          "score": 0,
          "stats": {"error": traceback.format_exc()},
          "replay_path": None,
        }

      with self._lock:
        req.results.append(seed_result)
        req.completed = i + 1

      self.hub.set_game_status("finished")
      self.hub._broadcast({
        "type": "eval_progress",
        "eval_id": req.id,
        "completed": req.completed,
        "total": req.total,
        "results": req.results,
      })

    with self._lock:
      req.status = "completed"
      scores = [r["score"] for r in req.results if isinstance(r.get("score"), (int, float))]
      if scores:
        mean = sum(scores) / len(scores)
        variance = sum((s - mean) ** 2 for s in scores) / len(scores) if len(scores) > 1 else 0
        req.aggregate = {
          "mean": round(mean, 2),
          "stdev": round(math.sqrt(variance), 2),
          "min": round(min(scores), 2),
          "max": round(max(scores), 2),
        }

    self.hub._broadcast({
      "type": "eval_complete",
      "eval_id": req.id,
      "results": req.results,
      "aggregate": req.aggregate,
    })


def _execute_game_subprocess(hub: ObservabilityHub, req: GameRequest) -> dict:
  """Run a game as a subprocess via `cogames play` with ROBOT_DEBUG=1.

  The subprocess inherits the current env with ROBOT_DEBUG=1 set, which
  causes the RobotPolicy to connect to the running observability hub.
  If we're in the same process (launcher mode), we fall back to in-process
  execution so the hub is shared directly.
  """
  if hub._launcher_mode:
    return _execute_game_inprocess(hub, req)

  env = {**os.environ, "ROBOT_DEBUG": "1"}

  cmd = [
    sys.executable, "-m", "cogames", "play",
    "-m", req.mission,
    "-v", req.variant,
    "-c", str(req.num_agents),
    "-p", req.policy,
    "-s", str(req.steps),
    "--seed", str(req.seed),
    "-r", req.render,
  ]

  print(f"\n  [{req.id}] Running: {' '.join(cmd)}\n")

  proc = subprocess.Popen(
    cmd,
    env=env,
    stdout=subprocess.PIPE,
    stderr=subprocess.STDOUT,
    text=True,
    cwd=os.getcwd(),
  )

  req.pid = proc.pid

  output_lines = []
  if proc.stdout:
    for line in proc.stdout:
      output_lines.append(line)

  returncode = proc.wait()
  output = "".join(output_lines)

  if returncode != 0:
    return {"error": f"Process exited with code {returncode}", "output": output[-2000:]}

  game_results = hub.get_game_results()
  result = game_results if game_results and isinstance(game_results, dict) else {}
  result["exit_code"] = returncode
  return result


def _execute_game_inprocess(hub: ObservabilityHub, req: GameRequest) -> dict:
  """In-process game execution for launcher mode (shared hub)."""
  import cogames  # noqa: F401
  from cogames.cli.mission import resolve_mission
  from cogames.cli.policy import parse_policy_spec
  from cogames.game import get_game
  from cogames.play import play as play_game
  from cogames.seed import seed_rollout_rng
  from mettagrid.policy.loader import discover_and_register_policies
  from rich.console import Console

  discover_and_register_policies()

  game = get_game("cogs_vs_clips")
  mission_name, env_cfg, _ = resolve_mission(game, req.mission)
  env_cfg.game.max_steps = req.steps

  policy_spec = parse_policy_spec(req.policy, device="cpu")
  seed_rollout_rng(req.seed)

  console = Console(stderr=True)
  hub.set_game_config({
    "game_id": req.id,
    "map": req.mission,
    "max_steps": req.steps,
    "seed": req.seed,
    "num_agents": env_cfg.game.num_agents,
    "policy": req.policy,
  })

  print(f"\n  [{req.id}] Starting game: {mission_name} ({req.steps} steps, seed={req.seed})\n")

  result = play_game(
    console,
    env_cfg=env_cfg,
    policy_specs=[policy_spec],
    seed=req.seed,
    device="cpu",
    render_mode=req.render,
    action_timeout_ms=10000,
    game_name=mission_name,
    autostart=True,
  )

  if result is None:
    result = {}
  if isinstance(result, (int, float)):
    result = {"score": result}

  game_results = hub.get_game_results()
  if game_results and isinstance(game_results, dict):
    result = {**game_results, **result}

  return result


def _game_to_dict(g: GameRequest) -> dict:
  return {
    "id": g.id,
    "config": {
      "mission": g.mission,
      "seed": g.seed,
      "steps": g.steps,
      "policy": g.policy,
      "num_agents": g.num_agents,
      "variant": g.variant,
    },
    "status": g.status,
    "result": g.result,
    "replay_path": g.replay_path,
    "started_at": g.started_at,
    "completed_at": g.completed_at,
  }


def _eval_to_dict(e: EvalRequest) -> dict:
  return {
    "id": e.id,
    "policy": e.policy,
    "mission": e.mission,
    "steps": e.steps,
    "seeds": e.seeds,
    "status": e.status,
    "completed": e.completed,
    "total": e.total,
    "results": e.results,
    "aggregate": e.aggregate,
  }
