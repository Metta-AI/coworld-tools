"""Real-time observability server for the robot control loop.

Runs a FastAPI server in a daemon thread alongside the game process.
Each RobotAgent.step() pushes tick data to the ObservabilityHub, which
broadcasts it to connected WebSocket clients.

Activation (inline with game):
  ROBOT_DEBUG=1 cogames play -m arena -p class=robot.RobotPolicy

Standalone launcher (start game from debugger UI):
  python robot/launcher.py
"""

import asyncio
import atexit
import json
import logging
import os
import queue
import threading
import time
import uuid
from collections import deque
from pathlib import Path
from typing import Optional

logger = logging.getLogger("robot.observability")


def _new_game_id() -> str:
  """Generate a short unique game ID (8-char hex from uuid4)."""
  return uuid.uuid4().hex[:8]


class ObservabilityHub:
  """Thread-safe ring buffer that stores per-agent tick data and notifies listeners.

  Uses stdlib queue.Queue for cross-thread notification (game thread -> uvicorn
  asyncio thread). asyncio.Queue is NOT safe for cross-thread put/get.
  """

  def __init__(self, max_per_agent: int = 300):
    self._lock = threading.Lock()
    self._max = max_per_agent
    self._agents: dict[int, deque[dict]] = {}
    self._maps: dict[int, dict] = {}
    self._offsets: dict[int, list[int]] = {}
    self._listeners: list[queue.Queue] = []
    self._listener_lock = threading.Lock()
    self._start_time = time.monotonic()

    self._game_status: str = "waiting"
    self._game_config: dict = {}
    self._game_results: Optional[dict] = None
    self._game_id: str = _new_game_id()
    self._launch_queue: queue.Queue = queue.Queue(maxsize=1)
    self._launcher_mode: bool = False

    self._llm_calls: deque = deque(maxlen=100)
    self._llm_stats: dict = {
      "total_calls": 0,
      "total_tokens": 0,
      "total_cost_usd": 0.0,
      "total_latency_ms": 0,
      "budget_used": 0,
      "budget_total": 0,
      "calls_with_errors": 0,
      "calls_with_directives": 0,
    }

    self._anomaly_detector = None

    self._match_info: dict = {}

  # -- Game ID --

  @property
  def game_id(self) -> str:
    with self._lock:
      return self._game_id

  def set_game_id(self, game_id: str) -> None:
    """Override the auto-generated game_id (e.g. from GameRunner)."""
    with self._lock:
      self._game_id = game_id

  # -- Match info (map, teams, policies, agent assignments) --

  def set_match_info(self, info: dict) -> None:
    """Store rich match metadata: map, teams, policies, agent→policy mapping."""
    with self._lock:
      self._match_info = info
      gid = self._game_id
    self._broadcast({"type": "match_info", "game_id": gid, **info})

  def get_match_info(self) -> dict:
    with self._lock:
      return dict(self._match_info)

  def set_game_status(self, status: str) -> None:
    with self._lock:
      self._game_status = status
      gid = self._game_id
    self._broadcast({"type": "game_status", "game_id": gid, "status": status,
                     "config": self.get_game_config()})
    if status == "finished":
      self._auto_dump()

  def get_game_status(self) -> str:
    with self._lock:
      return self._game_status

  def set_game_config(self, config: dict) -> None:
    with self._lock:
      self._game_config = config
      gid = self._game_id
    self._broadcast({"type": "game_config", "game_id": gid, "config": config})

  def get_game_config(self) -> dict:
    with self._lock:
      return dict(self._game_config)

  def set_game_results(self, results: dict) -> None:
    with self._lock:
      self._game_results = results
    self._auto_dump()

  def get_game_results(self) -> Optional[dict]:
    with self._lock:
      return self._game_results

  def dump_game_data(self) -> dict:
    """Export all game data as a single JSON-serializable dict."""
    with self._lock:
      all_ticks: list[dict] = []
      for agent_id, buf in self._agents.items():
        for tick_data in buf:
          all_ticks.append(dict(tick_data))

      return {
        "game_id": self._game_id,
        "status": self._game_status,
        "config": dict(self._game_config),
        "match_info": dict(self._match_info),
        "results": self._game_results,
        "ticks": sorted(all_ticks, key=lambda t: (t.get("tick", 0), t.get("agent_id", 0))),
        "llm_calls": list(self._llm_calls),
        "llm_stats": dict(self._llm_stats),
        "maps": {str(k): v for k, v in self._maps.items()},
        "offsets": {str(k): v for k, v in self._offsets.items()},
        "dumped_at": time.time(),
      }

  def _auto_dump(self) -> None:
    """Auto-save game data to ~/.cvc-debugger/games/ on game completion."""
    try:
      data = self.dump_game_data()
      dump_dir = Path.home() / ".cvc-debugger" / "games"
      dump_dir.mkdir(parents=True, exist_ok=True)
      filename = f"{data['game_id']}.json"
      path = dump_dir / filename
      with open(path, "w") as f:
        json.dump(data, f, default=str)
      logger.warning("Game data dumped to %s (%d ticks)", path, len(data["ticks"]))
      print(f"\n  >>> Game data saved to {path} <<<\n")
    except Exception as e:
      logger.error("Failed to dump game data: %s", e)

  def get_status_payload(self) -> dict:
    with self._lock:
      latest_tick = 0
      for buf in self._agents.values():
        if buf:
          t = buf[-1].get("tick", 0)
          if t > latest_tick:
            latest_tick = t
      return {
        "game_id": self._game_id,
        "status": self._game_status,
        "config": dict(self._game_config),
        "uptime": round(time.monotonic() - self._start_time, 1),
        "agent_count": len(self._agents),
        "tick": latest_tick,
        "results": self._game_results,
        "launcher_mode": self._launcher_mode,
        "match_info": dict(self._match_info),
      }

  def request_launch(self, params: dict) -> bool:
    """Called by /api/launch — puts params on the queue for the launcher."""
    if not self._launcher_mode:
      return False
    try:
      self._launch_queue.put_nowait(params)
      return True
    except queue.Full:
      return False

  def wait_for_launch(self, timeout: Optional[float] = None) -> Optional[dict]:
    """Blocks until /api/launch is called. Returns the launch params."""
    try:
      return self._launch_queue.get(timeout=timeout)
    except queue.Empty:
      return None

  def reset_for_new_game(self) -> None:
    """Clear agent/map data between games while keeping the server alive."""
    with self._lock:
      self._game_id = _new_game_id()
      self._agents.clear()
      self._maps.clear()
      self._offsets.clear()
      self._game_config.clear()
      self._game_results = None
      self._game_status = "waiting"
      self._match_info.clear()
      self._llm_calls.clear()
      budget_total = self._llm_stats.get("budget_total", 0)
      self._llm_stats = {
        "total_calls": 0, "total_tokens": 0, "total_cost_usd": 0.0,
        "total_latency_ms": 0, "budget_used": 0, "budget_total": budget_total,
        "calls_with_errors": 0, "calls_with_directives": 0,
      }

  def push(self, agent_id: int, data: dict) -> None:
    with self._lock:
      if agent_id not in self._agents:
        self._agents[agent_id] = deque(maxlen=self._max)
      data["game_id"] = self._game_id
      self._agents[agent_id].append(data)

    self._broadcast(data)

    if self._anomaly_detector:
      try:
        self._anomaly_detector.process_tick(data)
      except Exception:
        pass

  def _broadcast(self, data: dict) -> None:
    with self._listener_lock:
      dead: list[queue.Queue] = []
      for q in self._listeners:
        try:
          q.put_nowait(data)
        except queue.Full:
          dead.append(q)
      for q in dead:
        self._listeners.remove(q)

  def get_latest(self, agent_id: int) -> Optional[dict]:
    with self._lock:
      buf = self._agents.get(agent_id)
      if buf:
        return buf[-1]
    return None

  def get_history(self, agent_id: int, n: int = 200) -> list[dict]:
    with self._lock:
      buf = self._agents.get(agent_id)
      if buf is None:
        return []
      items = list(buf)
      return items[-n:]

  def get_all_agents(self) -> dict[int, dict]:
    with self._lock:
      result = {}
      for aid, buf in self._agents.items():
        if buf:
          result[aid] = buf[-1]
      return result

  def subscribe(self) -> queue.Queue:
    q: queue.Queue = queue.Queue(maxsize=500)
    with self._listener_lock:
      self._listeners.append(q)
    return q

  def unsubscribe(self, q: queue.Queue) -> None:
    with self._listener_lock:
      try:
        self._listeners.remove(q)
      except ValueError:
        pass

  def push_map(self, agent_id: int, map_data: dict) -> None:
    """Store latest map snapshot (walls/entities/territory grid) per agent."""
    with self._lock:
      self._maps[agent_id] = map_data

  def push_offsets(self, offsets: dict[int, tuple[int, int]]) -> None:
    """Store the latest coordinate offsets from SharedMap."""
    with self._lock:
      self._offsets = {k: list(v) for k, v in offsets.items()}

  def get_map(self, agent_id: int) -> Optional[dict]:
    with self._lock:
      return self._maps.get(agent_id)

  def get_all_maps(self) -> dict[int, dict]:
    with self._lock:
      return dict(self._maps)

  def get_offsets(self) -> dict[int, list[int]]:
    with self._lock:
      return dict(self._offsets)

  def push_llm_call(self, record: dict) -> None:
    """Store, accumulate stats, and broadcast an LLM call record."""
    with self._lock:
      self._llm_calls.append(record)
      s = self._llm_stats
      s["total_calls"] += 1
      s["budget_used"] = record.get("call_number", s["total_calls"])
      usage = record.get("usage")
      if usage:
        s["total_tokens"] += usage.get("total_tokens", 0)
      s["total_cost_usd"] += record.get("cost_usd", 0)
      s["total_latency_ms"] += record.get("latency_ms", 0)
      if record.get("error"):
        s["calls_with_errors"] += 1
      directives = record.get("parsed_directives", {})
      has_real = any(
        d.get("steps") for d in directives.values()
      ) if isinstance(directives, dict) else False
      if has_real:
        s["calls_with_directives"] += 1
    self._broadcast({"type": "llm_call", **record})

  def get_llm_calls(self) -> list[dict]:
    with self._lock:
      return list(self._llm_calls)

  def get_llm_stats(self) -> dict:
    with self._lock:
      s = dict(self._llm_stats)
      s["total_cost_usd"] = round(s["total_cost_usd"], 4)
      total = s["total_calls"]
      s["avg_latency_ms"] = round(s["total_latency_ms"] / total) if total else 0
      del s["total_latency_ms"]
      return s

  def set_llm_budget(self, budget: int) -> None:
    with self._lock:
      self._llm_stats["budget_total"] = budget

  @property
  def uptime_seconds(self) -> float:
    return time.monotonic() - self._start_time


_hub_instance: Optional[ObservabilityHub] = None


def get_hub() -> Optional[ObservabilityHub]:
  return _hub_instance


def _build_app(hub: ObservabilityHub):
  from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
  from fastapi.middleware.cors import CORSMiddleware
  from fastapi.responses import HTMLResponse, JSONResponse

  from robot.game_runner import GameRunner

  app = FastAPI(title="Robot Observability", docs_url=None, redoc_url=None)
  app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
  )

  runner = GameRunner(hub)
  app.state.runner = runner

  @app.get("/", response_class=HTMLResponse)
  async def dashboard():
    html_path = Path(__file__).parent / "dashboard.html"
    return HTMLResponse(html_path.read_text())

  @app.get("/api/status")
  async def api_status():
    return JSONResponse(hub.get_status_payload())

  @app.post("/api/launch")
  async def api_launch(request: Request):
    body = await request.json()
    if hub.get_game_status() != "waiting":
      return JSONResponse(
        {"ok": False, "error": "Game already running"},
        status_code=409,
      )
    ok = hub.request_launch(body)
    if not ok:
      return JSONResponse(
        {"ok": False, "error": "Launcher not available"},
        status_code=503,
      )
    return JSONResponse({"ok": True})

  @app.get("/api/state")
  async def api_state():
    agents = hub.get_all_agents()
    return JSONResponse({
      "uptime": round(hub.uptime_seconds, 1),
      "agents": {str(k): v for k, v in agents.items()},
    })

  @app.get("/api/history/{agent_id}")
  async def api_history(agent_id: int, n: int = 200):
    return JSONResponse(hub.get_history(agent_id, n))

  @app.get("/api/map/{agent_id}")
  async def api_map(agent_id: int):
    m = hub.get_map(agent_id)
    if m is None:
      return JSONResponse({})
    return JSONResponse(m)

  @app.get("/api/maps")
  async def api_maps():
    offsets = hub.get_offsets()
    return JSONResponse({
      "maps": {str(k): v for k, v in hub.get_all_maps().items()},
      "offsets": {str(k): v for k, v in offsets.items()},
    })

  @app.get("/api/llm")
  async def api_llm_calls():
    return JSONResponse({"calls": hub.get_llm_calls(), "stats": hub.get_llm_stats()})

  @app.get("/api/match")
  async def api_match():
    return JSONResponse(hub.get_match_info())

  @app.get("/api/dump")
  async def api_dump():
    """Export all game data as a single JSON payload for post-game debugging."""
    return JSONResponse(hub.dump_game_data())

  @app.get("/api/llm/stats")
  async def api_llm_stats():
    return JSONResponse(hub.get_llm_stats())

  @app.post("/api/games")
  async def api_games_create(request: Request):
    body = await request.json()
    game_id = runner.submit_game(body)
    return JSONResponse({"ok": True, "game_id": game_id})

  @app.get("/api/games")
  async def api_games_list():
    return JSONResponse({"games": runner.list_games()})

  @app.get("/api/games/{game_id}")
  async def api_game_detail(game_id: str):
    g = runner.get_game(game_id)
    if g is None:
      return JSONResponse({"error": "not found"}, status_code=404)
    return JSONResponse(g)

  @app.post("/api/eval")
  async def api_eval_create(request: Request):
    body = await request.json()
    eval_id = runner.submit_eval(body)
    return JSONResponse({"ok": True, "eval_id": eval_id})

  @app.get("/api/evals")
  async def api_evals_list():
    return JSONResponse({"evals": runner.list_evals()})

  @app.get("/api/eval/{eval_id}")
  async def api_eval_detail(eval_id: str):
    e = runner.get_eval(eval_id)
    if e is None:
      return JSONResponse({"error": "not found"}, status_code=404)
    return JSONResponse(e)

  @app.post("/api/anomaly/toggle")
  async def api_anomaly_toggle(request: Request):
    body = await request.json()
    enabled = body.get("enabled", True)
    if hub._anomaly_detector is None:
      from robot.anomaly_detector import AnomalyDetector
      hub._anomaly_detector = AnomalyDetector(hub)
    hub._anomaly_detector.set_enabled(enabled)
    return JSONResponse({"ok": True, "enabled": enabled})

  @app.post("/api/investigate")
  async def api_investigate(request: Request):
    body = await request.json()
    tick = body.get("tick", 0)
    agent_id = body.get("agent_id")
    question = body.get("question")

    from robot.investigator import Investigator
    investigator = Investigator(hub)
    result = investigator.investigate(tick, agent_id, question)
    return JSONResponse(result)

  # --- Policy file API ---

  @app.get("/api/policy/files")
  async def api_policy_files():
    robot_dir = Path(__file__).parent
    files = []
    for f in sorted(robot_dir.glob("*.py")):
      lines = f.read_text().count('\n') + 1
      files.append({"path": f"robot/{f.name}", "lines": lines})
    return JSONResponse({"files": files})

  @app.get("/api/policy/file")
  async def api_policy_file(path: str = "robot/brain.py"):
    base = Path(__file__).parent.parent
    target = (base / path).resolve()
    if not str(target).startswith(str(base.resolve())):
      return JSONResponse({"error": "path outside project"}, status_code=400)
    if not target.exists():
      return JSONResponse({"error": "file not found"}, status_code=404)
    return JSONResponse({"path": path, "content": target.read_text()})

  @app.post("/api/policy/edit")
  async def api_policy_edit(request: Request):
    body = await request.json()
    path = body.get("path", "")
    old_str = body.get("old_str", "")
    new_str = body.get("new_str", "")

    base = Path(__file__).parent.parent
    target = (base / path).resolve()
    if not str(target).startswith(str(base.resolve())):
      return JSONResponse({"error": "path outside project"}, status_code=400)
    if not target.exists():
      return JSONResponse({"error": "file not found"}, status_code=404)

    content = target.read_text()
    if old_str not in content:
      return JSONResponse({"error": "old_str not found in file"}, status_code=400)
    if content.count(old_str) > 1:
      return JSONResponse({"error": "old_str is ambiguous (multiple matches)"}, status_code=400)

    new_content = content.replace(old_str, new_str, 1)
    target.write_text(new_content)
    return JSONResponse({"ok": True, "path": path})

  @app.get("/api/policy/diff")
  async def api_policy_diff():
    import subprocess as sp
    base = Path(__file__).parent.parent
    try:
      result = sp.run(
        ["git", "diff", "--", "robot/"],
        capture_output=True, text=True, cwd=str(base), timeout=10,
      )
      return JSONResponse({"diff": result.stdout})
    except Exception as e:
      return JSONResponse({"diff": "", "error": str(e)})

  @app.post("/api/policy/reset")
  async def api_policy_reset():
    import subprocess as sp
    base = Path(__file__).parent.parent
    try:
      sp.run(
        ["git", "checkout", "--", "robot/"],
        cwd=str(base), timeout=10, check=True,
      )
      return JSONResponse({"ok": True})
    except Exception as e:
      return JSONResponse({"ok": False, "error": str(e)})

  # --- Eval engine API ---

  from robot.eval_engine import EvalEngine
  eval_engine = EvalEngine()
  app.state.eval_engine = eval_engine

  @app.post("/api/eval/quick")
  async def api_eval_quick(request: Request):
    body = await request.json()
    import asyncio
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, lambda: eval_engine.quick_eval(
      seed=body.get("seed", 42),
      steps=body.get("steps", 2000),
      mission=body.get("mission", "machina_1"),
      variant=body.get("variant", "talk"),
      num_agents=body.get("num_agents", 8),
    ))
    return JSONResponse({
      "seed": result.seed,
      "score": result.score,
      "error": result.error,
      "duration_s": round(result.duration_s, 1),
      "stats": result.stats,
    })

  @app.post("/api/eval/stream")
  async def api_eval_stream(request: Request):
    """Run a single-seed eval with SSE-streamed stdout lines and final result."""
    from starlette.responses import StreamingResponse
    from robot.eval_engine import POLICIES_DIR, _parse_json_score, _parse_log_score
    body = await request.json()
    seed = body.get("seed", 42)
    steps = body.get("steps", 2000)
    mission = body.get("mission", "machina_1")
    variant = body.get("variant", "talk")
    num_agents = body.get("num_agents", 8)
    policy = body.get("policy", "class=robot.RobotPolicy")

    async def event_stream():
      import subprocess as sp
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
      start_t = time.time()

      yield f"data: {json.dumps({'type': 'started', 'seed': seed, 'cmd': ' '.join(cmd)})}\n\n"

      try:
        proc = sp.Popen(
          cmd, stdout=sp.PIPE, stderr=sp.STDOUT,
          text=True, cwd=POLICIES_DIR, env=env,
        )

        full_output = []
        for line in iter(proc.stdout.readline, ''):
          stripped = line.rstrip('\n')
          full_output.append(stripped)
          yield f"data: {json.dumps({'type': 'log', 'line': stripped})}\n\n"

        proc.wait()
        duration = round(time.time() - start_t, 1)

        if proc.returncode != 0:
          yield f"data: {json.dumps({'type': 'done', 'seed': seed, 'score': 0, 'error': f'exit code {proc.returncode}', 'duration_s': duration})}\n\n"
          return

        stdout = '\n'.join(full_output)
        score = _parse_json_score(stdout)
        if score is None:
          score = _parse_log_score(stdout)

        if score is not None:
          yield f"data: {json.dumps({'type': 'done', 'seed': seed, 'score': score, 'duration_s': duration, 'stats': {}})}\n\n"
        else:
          yield f"data: {json.dumps({'type': 'done', 'seed': seed, 'score': 0, 'error': 'Could not parse score from output', 'duration_s': duration, 'raw_tail': chr(10).join(full_output[-20:])})}\n\n"

      except Exception as e:
        yield f"data: {json.dumps({'type': 'done', 'seed': seed, 'score': 0, 'error': str(e), 'duration_s': round(time.time() - start_t, 1)})}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")

  @app.post("/api/eval/full")
  async def api_eval_full(request: Request):
    body = await request.json()
    import asyncio
    loop = asyncio.get_event_loop()

    diff = None
    try:
      import subprocess as sp
      base = Path(__file__).parent.parent
      r = sp.run(["git", "diff", "--", "robot/"], capture_output=True, text=True, cwd=str(base), timeout=10)
      if r.stdout.strip():
        diff = r.stdout
    except Exception:
      pass

    run = await loop.run_in_executor(None, lambda: eval_engine.full_eval(
      seeds=body.get("seeds", [42, 123, 456, 789, 1337]),
      steps=body.get("steps", 1000),
      mission=body.get("mission", "arena"),
      variant=body.get("variant", "talk"),
      num_agents=body.get("num_agents", 4),
      diff=diff,
    ))
    from robot.eval_engine import _run_to_dict
    return JSONResponse(_run_to_dict(run))

  @app.get("/api/eval/history")
  async def api_eval_history():
    return JSONResponse({"runs": eval_engine.get_history()})

  # --- AI agent chat API ---

  @app.post("/api/agent/chat")
  async def api_agent_chat(request: Request):
    body = await request.json()
    message = body.get("message", "")
    session_id = body.get("session_id", "default")

    import asyncio
    from robot.policy_agent import PolicyAgent
    loop = asyncio.get_event_loop()

    if not hasattr(app.state, '_agents'):
      app.state._agents = {}
    if session_id not in app.state._agents:
      app.state._agents[session_id] = PolicyAgent(eval_engine)

    agent = app.state._agents[session_id]
    result = await loop.run_in_executor(None, agent.chat, message)
    return JSONResponse(result)

  @app.websocket("/ws")
  async def ws_stream(websocket: WebSocket):
    await websocket.accept()

    status_msg = json.dumps({
      "type": "game_status",
      "game_id": hub.game_id,
      "status": hub.get_game_status(),
      "config": hub.get_game_config(),
    })
    await websocket.send_text(status_msg)

    match_info = hub.get_match_info()
    if match_info:
      await websocket.send_text(json.dumps({"type": "match_info", "game_id": hub.game_id, **match_info}))

    q = hub.subscribe()
    loop = asyncio.get_event_loop()
    try:
      while True:
        try:
          data = await asyncio.wait_for(
            loop.run_in_executor(None, q.get, True, 5.0),
            timeout=10.0,
          )
          await websocket.send_text(json.dumps(data, default=str))
        except (asyncio.TimeoutError, queue.Empty):
          await websocket.send_text(json.dumps({"type": "heartbeat"}))
    except (WebSocketDisconnect, Exception):
      pass
    finally:
      hub.unsubscribe(q)

  return app


def start_server(
  hub: ObservabilityHub,
  port: int = 8777,
  open_browser: bool = False,
) -> None:
  """Launch uvicorn in a daemon thread. Non-blocking.

  After the game finishes, an atexit handler keeps the process alive
  so the debugger can fetch data post-game. Press Ctrl-C to exit.
  """
  global _hub_instance
  _hub_instance = hub

  app = _build_app(hub)

  def _run():
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="warning")

  t = threading.Thread(target=_run, daemon=True, name="robot-obs-server")
  t.start()
  hub._server_thread = t

  url = f"http://localhost:{port}"
  logger.warning("Dashboard running at %s", url)
  print(f"\n  >>> Robot Dashboard running at {url} <<<\n")

  if open_browser:
    import webbrowser
    threading.Timer(0.8, webbrowser.open, args=(url,)).start()

  def _stay_alive():
    status = hub.get_game_status()
    if status in ("finished", "waiting") and len(hub._agents) > 0:
      print(f"\n  >>> Game finished. Server staying alive at {url} for post-game debugging <<<")
      print(f"  >>> Press Ctrl-C to shut down <<<\n")
      try:
        while True:
          time.sleep(1)
      except KeyboardInterrupt:
        print("\n  Shutting down...")

  atexit.register(_stay_alive)



def is_debug_enabled(**kwargs) -> bool:
  """Check if observability is activated via env var or policy kwarg."""
  if os.environ.get("ROBOT_DEBUG", "").strip() in ("1", "true", "yes"):
    return True
  debug_val = kwargs.get("debug", "")
  if isinstance(debug_val, bool):
    return debug_val
  if isinstance(debug_val, str):
    return debug_val.strip().lower() in ("1", "true", "yes")
  return False


def build_tick_payload(
  snapshot_dict: dict,
  action: str,
  brain_debug: Optional[dict] = None,
  memory_stats: Optional[dict] = None,
  nav_path_len: int = 0,
) -> dict:
  """Assemble the enriched tick payload for the hub."""
  payload = dict(snapshot_dict)
  payload["action"] = action
  payload["ts"] = time.time()

  if brain_debug:
    payload["brain"] = brain_debug

  if memory_stats:
    payload["memory"] = memory_stats

  payload["nav_path_len"] = nav_path_len
  return payload
