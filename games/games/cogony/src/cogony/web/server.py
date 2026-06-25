"""Cogony web server: streams game state to browser MettaScope via WebSocket."""

from __future__ import annotations

import asyncio
import atexit
import concurrent.futures
import html
import json
import logging
import os
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from contextlib import suppress
from pathlib import Path

import aiohttp.web
import numpy as np
from mettagrid.renderer.renderer import Renderer
from mettagrid.simulator.monologue_projection import strip_monologue_transcript_tail
from mettagrid.types import Action
from mettagrid.util.grid_object_formatter import format_grid_object
from toolsy_policy.goals import active_goals_text as _active_goals_text
from toolsy_policy.goals import normalize_goal_tasks as _normalize_goal_tasks

logger = logging.getLogger(__name__)
_WEB_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _WEB_DIR.parents[2]
_DISABLED_BROWSER_VALUES = {"0", "false", "none", "off"}
_CODEX_ENV_VARS = ("CODEX_SHELL", "CODEX_THREAD_ID", "CODEX_INTERNAL_ORIGINATOR_OVERRIDE")


def _new_session_id() -> str:
    return f"{time.strftime('%Y%m%d-%H%M%S')}-{os.getpid()}-{uuid.uuid4().hex[:8]}"


def _current_vibe_name(vibe_names: list[str], vibe_id) -> str | None:
    if vibe_id is None:
        return None
    try:
        idx = int(vibe_id)
    except (TypeError, ValueError):
        return str(vibe_id)
    if 0 <= idx < len(vibe_names):
        return vibe_names[idx]
    return str(vibe_id)


def _mettascope_asset_dir() -> Path | None:
    mg_root = Path(sys.modules["mettagrid"].__file__).parent
    editable_data = mg_root.parent.parent.parent / "nim" / "mettascope" / "data"
    if editable_data.is_dir():
        return editable_data
    packaged_data = mg_root / "nim" / "mettascope" / "data"
    if packaged_data.is_dir():
        return packaged_data
    repo_assets = _REPO_ROOT / "assets" / "mettascope"
    if repo_assets.is_dir():
        return repo_assets
    return None


def build_initial_replay(sim):
    game_config = sim.config.game
    game_config_dict = game_config.model_dump(mode="json", exclude_none=True)
    agent_inv_limits = game_config.agents[0].inventory.limits if game_config.agents else {}
    capacity_names = sorted(agent_inv_limits.keys())
    resource_to_capacity_id = {}
    for cap_id, cap_name in enumerate(capacity_names):
        for resource_name in agent_inv_limits[cap_name].resources:
            resource_id = sim.resource_names.index(resource_name)
            resource_to_capacity_id[resource_id] = cap_id
    id_map = game_config.id_map()
    tag_name_to_id = {name: idx for idx, name in enumerate(id_map.tag_names())}
    initial_replay = {
        "version": 2,
        "action_names": list(sim.action_ids.keys()),
        "item_names": sim.resource_names,
        "type_names": sim.object_type_names,
        "vibe_names": list(getattr(game_config, "vibe_names", []) or []),
        "capacity_names": capacity_names,
        "tags": tag_name_to_id,
        "map_size": [sim.map_width, sim.map_height],
        "num_agents": sim.num_agents,
        "max_steps": 0,
        "mg_config": {"label": "MettaGrid Replay", "game": game_config_dict},
        "objects": [],
    }
    return initial_replay, capacity_names, resource_to_capacity_id


def build_step_replay(sim, capacity_names, resource_to_capacity_id):
    grid_objects = []
    total_rewards = sim.episode_rewards
    placeholder_actions = np.zeros((sim.num_agents, 2), dtype=np.int32)
    placeholder_rewards = np.zeros(sim.num_agents)
    ignore_types = ["wall"] if sim.current_step > 0 else []
    all_policy_infos = sim._context.get("policy_infos", {})
    vibe_names = list(getattr(sim.config.game, "vibe_names", []) or [])
    for grid_object in sim.grid_objects(ignore_types=ignore_types).values():
        agent_id = grid_object.get("agent_id")
        policy_infos = _websocket_policy_infos(strip_monologue_transcript_tail(all_policy_infos.get(agent_id)))
        formatted = format_grid_object(
            grid_object, placeholder_actions, sim.action_success,
            placeholder_rewards, total_rewards, policy_infos=policy_infos,
        )
        raw = formatted.pop("inventory_capacities_raw", {})
        group_caps = {}
        for resource_id, eff_limit in raw.items():
            cap_id = resource_to_capacity_id.get(resource_id)
            if cap_id is not None and cap_id not in group_caps:
                group_caps[cap_id] = eff_limit
        formatted["inventory_capacities"] = sorted(group_caps.items())
        if formatted.get("is_agent") or formatted.get("type_name") == "agent":
            current_vibe = _current_vibe_name(vibe_names, formatted.get("vibe_id"))
            if current_vibe is not None:
                formatted["current_vibe"] = current_vibe
        grid_objects.append(formatted)
    return {
        "step": sim.current_step,
        "objects": grid_objects,
        "episode_stats": sim._c_sim.get_episode_stats(),
    }


def build_panel_step_replay(step_replay: dict, *, last_actions: dict[int, str] | None = None) -> dict:
    last_actions = last_actions or {}
    objects = []
    for obj in step_replay.get("objects", []):
        if obj.get("type_name") == "wall":
            continue
        panel_obj = dict(obj)
        if panel_obj.get("is_agent") or panel_obj.get("type_name") == "agent":
            if "policy_infos" in panel_obj:
                panel_obj["policy_infos"] = _websocket_policy_infos(panel_obj.get("policy_infos"))
            agent_id = panel_obj.get("agent_id")
            if agent_id in last_actions and last_actions[agent_id] is not None:
                panel_obj["last_action"] = last_actions[agent_id]
        else:
            panel_obj.pop("policy_infos", None)
        objects.append(panel_obj)
    return {
        "step": step_replay["step"],
        "objects": objects,
        "episode_stats": step_replay.get("episode_stats", {}),
    }


def _websocket_policy_infos(policy_infos) -> dict:
    safe_infos = dict(policy_infos or {})
    safe_infos.pop("policy_widgets", None)
    safe_infos.pop("__policy_widgets__", None)
    return safe_infos


def _llm_log_delta(previous: str, current: str) -> str:
    if not current:
        return ""
    if not previous:
        return current
    if current == previous:
        return ""
    if current.startswith(previous):
        return current[len(previous):].lstrip("\n")
    return current


def _agent_object(step_replay: dict, agent_id: int) -> dict | None:
    for obj in step_replay.get("objects", []):
        if (obj.get("is_agent") or obj.get("type_name") == "agent") and obj.get("agent_id") == agent_id:
            return obj
    return None


def build_agent_state_replay(
    step_replay: dict,
    agent_id: int,
    *,
    last_action: str | None = None,
    agent_log: list[dict] | None = None,
) -> dict:
    raw_agent = _agent_object(step_replay, agent_id)
    agent = dict(raw_agent) if raw_agent is not None else None
    if agent is not None and "policy_infos" in agent:
        agent["policy_infos"] = _websocket_policy_infos(agent.get("policy_infos"))
    policy_infos = _websocket_policy_infos((agent or {}).get("policy_infos"))
    obs = policy_infos.get("obs_grid") or {}
    state = {
        "type": "agent_state",
        "agent_id": agent_id,
        "step": step_replay.get("step"),
        "agent": agent,
        "obs": obs,
        "last_obs": obs,
        "last_action": last_action,
        "policy_infos": policy_infos,
        "llm_log": policy_infos.get("llm_log", ""),
        "llm_system": policy_infos.get("llm_system", ""),
        "agent_log": list(agent_log or []),
        "episode_stats": step_replay.get("episode_stats", {}),
    }
    return state


def build_policy_agent_state_replay(agent_state: dict) -> dict:
    policy_infos = agent_state.get("policy_infos") or {}
    control_infos = {
        key: policy_infos[key]
        for key in ("current_goals", "goal_tasks", "__policy_name__", "__agent_name__")
        if key in policy_infos
    }
    agent = agent_state.get("agent")
    if isinstance(agent, dict):
        agent = dict(agent)
        if control_infos:
            agent["policy_infos"] = dict(control_infos)
        else:
            agent.pop("policy_infos", None)
    return {
        "type": "agent_state",
        "agent_id": agent_state.get("agent_id"),
        "step": agent_state.get("step"),
        "agent": agent,
        "obs": agent_state.get("obs") or {},
        "last_obs": agent_state.get("last_obs") or agent_state.get("obs") or {},
        "last_action": agent_state.get("last_action"),
        "policy_infos": control_infos,
        "episode_stats": agent_state.get("episode_stats", {}),
    }


def next_websocket_agent_id(next_agent_id: int, num_agents: int) -> int:
    return next_agent_id % max(1, num_agents)


def _browser_name(base_command: list[str]) -> tuple[str, str]:
    return Path(base_command[0]).name.lower(), " ".join(base_command).lower()


def _browser_command(base_command: list[str], url: str, profile_dir: Path) -> list[str]:
    executable, full_name = _browser_name(base_command)
    if any(name in executable or name in full_name for name in ["chrome", "chromium", "edge", "brave"]):
        return [
            *base_command,
            "--new-window",
            f"--app={url}",
            f"--user-data-dir={profile_dir}",
            "--no-first-run",
            "--no-default-browser-check",
        ]
    if "firefox" in executable or "firefox" in full_name:
        return [*base_command, "-new-instance", "-profile", str(profile_dir), "-new-window", url]
    return [*base_command, url]


def _browser_policy_domain(base_command: list[str]) -> str | None:
    executable, full_name = _browser_name(base_command)
    if "google chrome" in full_name or "chrome" in executable:
        return "com.google.Chrome"
    if "chromium" in full_name or "chromium" in executable:
        return "org.chromium.Chromium"
    if "microsoft edge" in full_name or "edge" in executable:
        return "com.microsoft.Edge"
    if "brave" in full_name or "brave" in executable:
        return "com.brave.Browser"
    return None


class _MacQuitWarningOverride:
    def __init__(self, domain: str, previous: str | None):
        self._domain = domain
        self._previous = previous
        self._restored = False

    def restore(self) -> None:
        if self._restored:
            return
        self._restored = True
        if self._previous is None:
            subprocess.run(
                ["defaults", "delete", self._domain, "WarnBeforeQuittingEnabled"],
                capture_output=True,
                text=True,
                check=False,
            )
            return
        enabled = self._previous.strip().lower() not in {"0", "false", "no"}
        subprocess.run(
            ["defaults", "write", self._domain, "WarnBeforeQuittingEnabled", "-bool", str(enabled).lower()],
            capture_output=True,
            text=True,
            check=False,
        )


def _disable_macos_quit_warning(base_command: list[str]) -> _MacQuitWarningOverride | None:
    if sys.platform != "darwin":
        return None
    domain = _browser_policy_domain(base_command)
    if domain is None:
        return None
    previous_result = subprocess.run(
        ["defaults", "read", domain, "WarnBeforeQuittingEnabled"],
        capture_output=True,
        text=True,
        check=False,
    )
    previous = previous_result.stdout.strip() if previous_result.returncode == 0 else None
    write_result = subprocess.run(
        ["defaults", "write", domain, "WarnBeforeQuittingEnabled", "-bool", "false"],
        capture_output=True,
        text=True,
        check=False,
    )
    if write_result.returncode != 0:
        return None
    return _MacQuitWarningOverride(domain, previous)


def _find_browser_command() -> list[str] | None:
    configured = os.environ.get("COGONY_BROWSER") or os.environ.get("BROWSER")
    if configured:
        if configured.strip().lower() in _DISABLED_BROWSER_VALUES:
            return None
        return shlex.split(configured)

    mac_candidates = [
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "/Applications/Chromium.app/Contents/MacOS/Chromium",
        "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
        "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
    ]
    for candidate in mac_candidates:
        if Path(candidate).is_file():
            return [candidate]

    for executable in [
        "google-chrome",
        "google-chrome-stable",
        "chromium",
        "chromium-browser",
        "microsoft-edge",
        "brave-browser",
        "firefox",
    ]:
        resolved = shutil.which(executable)
        if resolved:
            return [resolved]
    return None


def _running_under_codex() -> bool:
    return any(os.environ.get(name) for name in _CODEX_ENV_VARS)


class _ManagedBrowser:
    def __init__(
        self,
        process: subprocess.Popen,
        profile_dir: tempfile.TemporaryDirectory,
        quit_warning_override: _MacQuitWarningOverride | None = None,
    ):
        self._process = process
        self._profile_dir = profile_dir
        self._quit_warning_override = quit_warning_override

    def close(self) -> None:
        profile_path = self._profile_dir.name
        if self._process.poll() is None:
            self._process.terminate()
            try:
                self._process.wait(timeout=2.0)
            except subprocess.TimeoutExpired:
                self._process.kill()
                self._process.wait(timeout=2.0)
        _terminate_browser_profile_processes(profile_path)
        if self._quit_warning_override is not None:
            self._quit_warning_override.restore()
        self._profile_dir.cleanup()


def _browser_profile_pids(profile_path: str) -> set[int]:
    result = subprocess.run(
        ["pgrep", "-f", "--", f"--user-data-dir={profile_path}"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode not in {0, 1}:
        return set()
    current_pid = os.getpid()
    return {int(line) for line in result.stdout.splitlines() if line.strip().isdigit() and int(line) != current_pid}


def _terminate_browser_profile_processes(profile_path: str) -> None:
    pids = _browser_profile_pids(profile_path)
    for pid in pids:
        with suppress(ProcessLookupError, PermissionError):
            os.killpg(os.getpgid(pid), signal.SIGTERM)

    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline:
        remaining = _browser_profile_pids(profile_path)
        if not remaining:
            return
        time.sleep(0.05)

    for pid in _browser_profile_pids(profile_path):
        with suppress(ProcessLookupError, PermissionError):
            os.killpg(os.getpgid(pid), signal.SIGKILL)


def _launch_managed_browser(url: str) -> _ManagedBrowser | None:
    import webbrowser

    configured = os.environ.get("COGONY_BROWSER") or os.environ.get("BROWSER")
    if configured and configured.strip().lower() in _DISABLED_BROWSER_VALUES:
        return None

    base_command = _find_browser_command()
    if base_command is None:
        webbrowser.open(url)
        return None

    profile_dir = tempfile.TemporaryDirectory(prefix="cogony-browser-")
    command = _browser_command(base_command, url, Path(profile_dir.name))
    quit_warning_override = _disable_macos_quit_warning(base_command)
    try:
        process = subprocess.Popen(
            command,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except OSError:
        if quit_warning_override is not None:
            quit_warning_override.restore()
        profile_dir.cleanup()
        webbrowser.open(url)
        return None
    return _ManagedBrowser(process, profile_dir, quit_warning_override)


@aiohttp.web.middleware
async def _coop_coep_middleware(request, handler):
    resp = await handler(request)
    resp.headers["Cross-Origin-Opener-Policy"] = "same-origin"
    resp.headers["Cross-Origin-Embedder-Policy"] = "require-corp"
    return resp


class WebRenderer(Renderer):
    """Streams game state to browser MettaScope via aiohttp WebSocket."""

    def __init__(
        self,
        wasm_dir,
        port=0,
        tick_rate=5.0,
        autoplay: bool = False,
        codex_browser: bool = False,
        launch_path: str = "/",
        log_dir: Path | str = "logs",
        player_tokens: list[str] | None = None,
    ):
        super().__init__()
        self._wasm_dir = wasm_dir
        self._port = port
        self._tick_rate = tick_rate
        self._tick_interval = 1.0 / tick_rate
        self._session_id = _new_session_id()
        self._log_dir = Path(log_dir)
        self._session_log_path = self._log_dir / f"{self._session_id}.out"
        self._player_tokens = list(player_tokens or [])
        self._access_logger: logging.Logger | None = None
        self._access_log_handler: logging.FileHandler | None = None

        self._clients: list[aiohttp.web.WebSocketResponse] = []
        self._global_clients: list[aiohttp.web.WebSocketResponse] = []
        self._agent_clients: dict[int, list[aiohttp.web.WebSocketResponse]] = {}
        self._policy_clients: dict[int, list[aiohttp.web.WebSocketResponse]] = {}
        self._policy_debug_clients: dict[int, list[aiohttp.web.WebSocketResponse]] = {}
        self._external_policy_infos: dict[int, dict] = {}
        self._pending_actions: dict[int, str] = {}
        self._last_actions: dict[int, str] = {}
        self._llm_trigger_requests: dict[int, int] = {}
        self._lock = threading.Lock()
        self._playing = autoplay
        self._codex_browser = codex_browser
        self._launch_path = self._normalize_launch_path(launch_path)
        self._input_mode = "step-on-action"
        self._frame_requests = 0
        self._next_agent_id = 0
        self._initial_replay: dict = {}
        self._capacity_names: list[str] = []
        self._resource_to_capacity_id: dict[int, int] = {}
        self._latest_step_msg: str | None = None
        self._latest_panel_step_msg: str | None = None
        self._latest_agent_state_msgs: dict[int, str] = {}
        self._agent_logs: dict[int, list[dict]] = {}
        self._last_agent_log_snapshot: dict[int, str] = {}
        self._walls_msg: str | None = None
        self._last_render_time = 0.0
        self._heartbeat_interval = 1.0
        self._loop: asyncio.AbstractEventLoop | None = None
        self._heartbeat_task: asyncio.Task[None] | None = None
        self._server_stop_event: asyncio.Event | None = None
        self._browser = None
        self._browser_atexit_registered = False
        self._shutdown_requested = threading.Event()
        self._ui_client_seen = False
        self._ui_disconnect_grace_seconds = 1.0
        self._ui_disconnect_shutdown_timer: threading.Timer | None = None
        self._ready = threading.Event()
        self._status_provider = None

        app = aiohttp.web.Application(middlewares=[_coop_coep_middleware])
        app.router.add_get("/", self._serve_global_client)
        app.router.add_get("/favicon.ico", self._serve_favicon)
        app.router.add_get("/healthz", self._serve_healthz)
        app.router.add_get("/admin", self._serve_admin)
        app.router.add_get("/status", self._serve_status)
        app.router.add_post("/admin", self._handle_admin)
        app.router.add_get("/global", self._handle_global)
        app.router.add_get("/global-client", self._serve_global_client)
        app.router.add_get("/agent/{agent_id}", self._handle_agent_ws)
        app.router.add_get("/policy/{agent_id}", self._handle_policy_ws)
        app.router.add_get("/policy-debug/{agent_id}", self._handle_policy_debug_ws)
        app.router.add_get("/player", self._handle_player)
        app.router.add_get("/policy-debugger", self._serve_agent_client)
        app.router.add_get("/ws", self._handle_ws)
        asset_dir = _mettascope_asset_dir()
        if asset_dir:
            app.router.add_static("/mettascope-assets/", asset_dir, append_version=True)
        if wasm_dir and wasm_dir.is_dir():
            app.router.add_get("/wasm/mettascope.html", self._serve_patched_wasm_html)
            app.router.add_static("/wasm/", wasm_dir)
        self._app = app

    @property
    def session_id(self) -> str:
        return self._session_id

    @property
    def session_log_path(self) -> Path:
        return self._session_log_path

    def set_status_provider(self, provider) -> None:
        self._status_provider = provider

    def set_player_tokens(self, player_tokens: list[str]) -> None:
        with self._lock:
            self._player_tokens = list(player_tokens)

    def agent_ws_url(self, agent_id: int) -> str:
        return f"ws://127.0.0.1:{self._port}/agent/{agent_id}"

    def policy_ws_url(self, agent_id: int) -> str:
        return f"ws://127.0.0.1:{self._port}/policy/{agent_id}"

    async def _serve_client_file(self, filename: str):
        html = (_WEB_DIR / filename).read_text()
        return aiohttp.web.Response(text=html, content_type="text/html", headers={"Cache-Control": "no-store"})

    async def _serve_global_client(self, request):
        return await self._serve_client_file("global-client.html")

    async def _serve_agent_client(self, request):
        return await self._serve_client_file("agent-client.html")

    async def _serve_index(self, request):
        return await self._serve_global_client(request)

    async def _serve_healthz(self, request):
        return aiohttp.web.json_response({"ok": True})

    async def _serve_favicon(self, request):
        return aiohttp.web.Response(status=204)

    async def _serve_admin(self, request):
        if request.query.get("format") == "json" or "application/json" in request.headers.get("Accept", ""):
            return aiohttp.web.json_response(self.admin_state())
        return aiohttp.web.Response(text=self._admin_html(), content_type="text/html")

    async def _serve_status(self, request):
        status = self.status_state()
        if request.query.get("format") == "json" or "application/json" in request.headers.get("Accept", ""):
            return aiohttp.web.json_response(status)
        return aiohttp.web.Response(text=self._status_html(status), content_type="text/html")

    def status_state(self) -> dict:
        if self._status_provider is not None:
            return self._status_provider()
        return {
            "ok": True,
            "runner": "cogony_web_renderer",
            "session_id": self._session_id,
            "components": [
                {"name": "server", "state": "running", "detail": f"http://localhost:{self._port}"},
            ],
            "endpoints": {
                "healthz": f"http://127.0.0.1:{self._port}/healthz",
                "status": f"http://127.0.0.1:{self._port}/status",
                "admin": f"http://127.0.0.1:{self._port}/admin",
                "global_client": f"http://127.0.0.1:{self._port}/global-client",
                "policy_debugger_0": f"http://127.0.0.1:{self._port}/policy-debugger?agent=0",
                "global": f"ws://127.0.0.1:{self._port}/global",
                "player": f"ws://127.0.0.1:{self._port}/player",
                "agent_template": f"ws://127.0.0.1:{self._port}/agent/{{id}}",
                "policy_template": f"ws://127.0.0.1:{self._port}/policy/{{id}}",
                "policy_debug_template": f"ws://127.0.0.1:{self._port}/policy-debug/{{id}}",
            },
            "admin": self.admin_state(),
        }

    async def _handle_admin(self, request):
        payload = await request.json() if request.can_read_body else {}
        try:
            state = self.handle_admin_command(payload)
        except ValueError as exc:
            return aiohttp.web.json_response({"ok": False, "error": str(exc)}, status=400)
        return aiohttp.web.json_response(state)

    async def _handle_global(self, request):
        if request.headers.get("Upgrade", "").lower() == "websocket":
            return await self._handle_global_ws(request)
        return await self._serve_global_client(request)

    async def _handle_player(self, request):
        if request.headers.get("Upgrade", "").lower() == "websocket":
            return await self._handle_ws(request, require_player_auth=True)
        return await self._serve_agent_client(request)

    async def _serve_patched_wasm_html(self, request):
        html = (self._wasm_dir / "mettascope.html").read_text()
        version = self._wasm_asset_version()
        html = html.replace(
            'src="mettascope.js"',
            f'src="mettascope.js?v={version}"',
        )
        html = html.replace(
            "var Module = {",
            "var Module = {\n"
            f"        locateFile: function(path, prefix) {{ return prefix + path + '?v={version}'; }},",
        )
        return aiohttp.web.Response(text=html, content_type="text/html", headers={"Cache-Control": "no-store"})

    def _wasm_asset_version(self) -> str:
        parts = []
        for name in ("mettascope.js", "mettascope.wasm", "mettascope.data"):
            path = self._wasm_dir / name
            if path.exists():
                stat = path.stat()
                parts.append(f"{name}:{stat.st_mtime_ns}:{stat.st_size}")
        return str(abs(hash("|".join(parts))))

    def supports_pending_render(self) -> bool:
        return True

    def render_pending(self) -> None:
        self._drain_pending_inputs()

    def apply_deferred_user_actions(self) -> None:
        self._drain_pending_inputs()
        super().apply_deferred_user_actions()

    def queue_player_action(self, agent_id: int, action_name: str, *, grant_step_on_action: bool = True) -> bool:
        granted_step = False
        with self._lock:
            self._pending_actions[agent_id] = action_name
            self._last_actions[agent_id] = action_name
            if grant_step_on_action and self._input_mode == "step-on-action" and not self._playing:
                self._frame_requests += 1
                granted_step = True
        return granted_step

    def request_llm_trigger(self, agent_id: int) -> int:
        with self._lock:
            trigger_id = self._llm_trigger_requests.get(agent_id, 0) + 1
            self._llm_trigger_requests[agent_id] = trigger_id
            return trigger_id

    def start(self) -> dict:
        with self._lock:
            self._playing = True
            return self._admin_state_unlocked()

    def stop(self) -> dict:
        with self._lock:
            self._playing = False
            self._frame_requests = 0
            self._pending_actions.clear()
            return self._admin_state_unlocked()

    def step(self, frames: int = 1) -> dict:
        if frames < 1:
            raise ValueError("frames must be >= 1")
        with self._lock:
            self._playing = False
            self._frame_requests += frames
            return self._admin_state_unlocked()

    def goto(self, frame: int) -> dict:
        if frame < 0:
            raise ValueError("frame must be >= 0")
        with self._lock:
            current_step = getattr(getattr(self, "_sim", None), "current_step", 0)
            if current_step is None:
                current_step = 0
            if frame < current_step:
                raise ValueError(f"cannot goto past frame {frame}; current frame is {current_step}")
            self._playing = False
            self._frame_requests = frame - current_step
            return self._admin_state_unlocked()

    def set_ticks_per_second(self, ticks_per_second: float) -> dict:
        if ticks_per_second <= 0:
            raise ValueError("ticks_per_second must be > 0")
        with self._lock:
            self._tick_rate = ticks_per_second
            self._tick_interval = 1.0 / ticks_per_second
            return self._admin_state_unlocked()

    def set_mode(self, mode: str) -> dict:
        normalized = mode.strip().lower().replace("_", "-")
        if normalized in {"play", "playing", "start"}:
            return self.start()
        if normalized in {"pause", "paused", "stop", "stopped"}:
            return self.stop()
        if normalized == "manual":
            with self._lock:
                self._playing = False
                self._input_mode = "manual"
                self._frame_requests = 0
                self._pending_actions.clear()
                return self._admin_state_unlocked()
        if normalized != "step-on-action":
            raise ValueError(f"unknown mode: {mode or '<empty>'}")
        with self._lock:
            self._playing = False
            self._input_mode = "step-on-action"
            self._frame_requests = 0
            return self._admin_state_unlocked()

    def quit(self) -> dict:
        with self._lock:
            self._playing = False
            self._input_mode = "manual"
            self._frame_requests = 0
            self._pending_actions.clear()
        self.request_shutdown()
        return self.admin_state()

    def admin_state(self) -> dict:
        with self._lock:
            return self._admin_state_unlocked()

    def handle_admin_command(self, payload: dict) -> dict:
        command, payload = self._parse_admin_command(payload)
        if command in {"start", "play"}:
            return self.start()
        if command == "stop":
            return self.stop()
        if command in {"step", "frame"}:
            return self.step(int(payload.get("frames", 1)))
        if command == "goto":
            return self.goto(int(payload.get("frame")))
        if command in {"set_ticks_per_second", "speed"}:
            ticks_per_second = payload.get(
                "ticks_per_second",
                payload.get("tps", payload.get("speed", payload.get("tick_rate", self._tick_rate))),
            )
            return self.set_ticks_per_second(float(ticks_per_second))
        if command in {"set_mode", "mode"}:
            return self.set_mode(str(payload.get("mode", "")))
        if command == "step-on-action":
            return self.set_mode(command)
        if command in {"quit", "shutdown", "exit"}:
            return self.quit()
        raise ValueError(f"unknown admin command: {command or '<empty>'}")

    @staticmethod
    def _parse_admin_command(payload: dict) -> tuple[str, dict]:
        command = str(payload.get("command", "")).strip().lower()
        if command.endswith(")") and "(" in command:
            name, _, raw_arg = command.partition("(")
            payload = dict(payload)
            command = name.strip()
            arg = raw_arg[:-1].strip()
            if arg:
                if command == "goto":
                    payload.setdefault("frame", arg)
                elif command == "set_ticks_per_second":
                    payload.setdefault("ticks_per_second", arg)
                elif command in {"set_mode", "mode"}:
                    payload.setdefault("mode", arg)
        return command, payload

    def shutdown_requested(self) -> bool:
        return self._shutdown_requested.is_set()

    def request_shutdown(self) -> None:
        self._cancel_ui_disconnect_shutdown()
        self._shutdown_requested.set()
        if self._loop is not None and self._server_stop_event is not None:
            self._loop.call_soon_threadsafe(self._server_stop_event.set)

    def wait_until_step_allowed(self) -> bool:
        while not self.shutdown_requested() and not self._consume_step_permission():
            time.sleep(0.02)
        return not self.shutdown_requested()

    def _consume_step_permission(self) -> bool:
        with self._lock:
            if self._playing:
                return True
            if self._frame_requests > 0:
                self._frame_requests -= 1
                return True
            return False

    def on_episode_start(self) -> None:
        self._initial_replay, self._capacity_names, self._resource_to_capacity_id = build_initial_replay(self._sim)
        self._walls_msg = None

        t = threading.Thread(target=self._run_server, daemon=True)
        t.start()
        self._ready.wait()
        logger.info("Web server ready at http://localhost:%d/", self._port)
        self._launch_browser()

    def _launch_browser(self) -> None:
        url = f"http://localhost:{self._port}{self._launch_path}"
        if self._codex_browser:
            logger.info("Codex browser mode requested for %s", url)
            return
        self._browser = _launch_managed_browser(url)
        if self._browser is not None and not self._browser_atexit_registered:
            atexit.register(self._close_browser)
            self._browser_atexit_registered = True

    def _close_browser(self) -> None:
        browser = self._browser
        self._browser = None
        if browser is not None:
            browser.close()

    @staticmethod
    def _normalize_launch_path(launch_path: str) -> str:
        path = str(launch_path or "/")
        if not path.startswith("/"):
            path = f"/{path}"
        return path

    def _run_server(self):
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self._loop.run_until_complete(self._serve())

    async def _serve(self):
        runner = aiohttp.web.AppRunner(self._app, access_log=self._open_access_log())
        await runner.setup()
        site = aiohttp.web.TCPSite(runner, "0.0.0.0", self._port)
        await site.start()
        bound_port = self._site_bound_port(site)
        if bound_port is not None:
            with self._lock:
                self._port = bound_port
        self._heartbeat_task = asyncio.create_task(self._send_heartbeats())
        self._server_stop_event = asyncio.Event()
        self._ready.set()
        try:
            await self._server_stop_event.wait()
        finally:
            if self._heartbeat_task is not None:
                self._heartbeat_task.cancel()
                with suppress(asyncio.CancelledError):
                    await self._heartbeat_task
            self._cancel_ui_disconnect_shutdown()
            await runner.cleanup()
            self._close_browser()
            self._close_access_log()

    @staticmethod
    def _site_bound_port(site: aiohttp.web.TCPSite) -> int | None:
        server = getattr(site, "_server", None)
        sockets = getattr(server, "sockets", None) or []
        if not sockets:
            return None
        return int(sockets[0].getsockname()[1])

    def _open_access_log(self) -> logging.Logger:
        if self._access_logger is not None:
            return self._access_logger
        self._log_dir.mkdir(parents=True, exist_ok=True)
        access_logger = logging.getLogger(f"cogony.web.access.{self._session_id}")
        access_logger.handlers.clear()
        access_logger.propagate = False
        access_logger.setLevel(logging.INFO)
        handler = logging.FileHandler(self._session_log_path, encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(message)s"))
        access_logger.addHandler(handler)
        self._access_logger = access_logger
        self._access_log_handler = handler
        return access_logger

    def _close_access_log(self) -> None:
        handler = self._access_log_handler
        access_logger = self._access_logger
        self._access_log_handler = None
        self._access_logger = None
        if handler is None:
            return
        if access_logger is not None:
            access_logger.removeHandler(handler)
        handler.close()

    def render(self) -> None:
        now = time.monotonic()
        with self._lock:
            tick_interval = self._tick_interval
        if self._last_render_time > 0:
            remaining = tick_interval - (now - self._last_render_time)
            if remaining > 0:
                time.sleep(remaining)
        self._last_render_time = time.monotonic()

        if self._walls_msg is None:
            self._walls_msg = self._build_walls_msg()
            self._broadcast(self._walls_msg)

        self._merge_external_policy_infos()
        step_replay = build_step_replay(self._sim, self._capacity_names, self._resource_to_capacity_id)
        step_msg = json.dumps({"type": "step", **step_replay}, allow_nan=False)
        with self._lock:
            last_actions = dict(self._last_actions)
        panel_step_msg = json.dumps(
            {"type": "step", **build_panel_step_replay(step_replay, last_actions=last_actions)},
            allow_nan=False,
        )
        agent_state_msgs, policy_state_msgs = self._build_agent_state_messages(step_replay)
        with self._lock:
            self._latest_step_msg = step_msg
            self._latest_panel_step_msg = panel_step_msg
            self._latest_agent_state_msgs = agent_state_msgs
        self._broadcast(step_msg, include_global=False)
        self._broadcast(panel_step_msg, include_players=False)
        self._broadcast_agent_states(agent_state_msgs, policy_messages=policy_state_msgs)
        self._drain_pending_inputs()

    def on_episode_end(self) -> None:
        done_msg = json.dumps({"type": "done", "episode_stats": self._sim._c_sim.get_episode_stats()})
        future = self._broadcast(done_msg)
        if future is not None:
            with suppress(TimeoutError, ConnectionError, concurrent.futures.TimeoutError, RuntimeError):
                future.result(timeout=2.0)
        self._close_browser()
        self.request_shutdown()

    def _build_walls_msg(self) -> str:
        wall_objects = [
            {
                "id": obj["id"],
                "alive": True,
                "type_name": "wall",
                "location": obj["location"],
                "orientation": 0,
                "inventory": [],
                "inventory_max": 0,
                "color": 0,
                "tag_ids": [],
                "vibe_id": 0,
                "inventory_capacities": [],
            }
            for obj in self._sim.grid_objects(ignore_types=[]).values()
            if obj["type_name"] == "wall"
        ]
        return json.dumps({"type": "walls", "step": 0, "objects": wall_objects}, allow_nan=False)

    def _build_agent_state_messages(self, step_replay: dict) -> tuple[dict[int, str], dict[int, str]]:
        messages = {}
        policy_messages = {}
        with self._lock:
            for obj in step_replay.get("objects", []):
                if not (obj.get("is_agent") or obj.get("type_name") == "agent"):
                    continue
                agent_id = obj.get("agent_id")
                if agent_id is None:
                    continue
                policy_infos = obj.get("policy_infos") or {}
                log = str(policy_infos.get("llm_log") or "")
                log_delta = _llm_log_delta(self._last_agent_log_snapshot.get(agent_id, ""), log)
                if log_delta:
                    entry = {
                        "step": step_replay.get("step"),
                        "log": log_delta,
                        "system": policy_infos.get("llm_system", ""),
                        "delta": True,
                    }
                    self._agent_logs.setdefault(agent_id, []).append(entry)
                    self._agent_logs[agent_id] = self._agent_logs[agent_id][-200:]
                    self._last_agent_log_snapshot[agent_id] = log
                state = build_agent_state_replay(
                    step_replay,
                    agent_id,
                    last_action=self._last_actions.get(agent_id),
                    agent_log=self._agent_logs.get(agent_id, []),
                )
                messages[agent_id] = json.dumps(state, allow_nan=False)
                policy_messages[agent_id] = json.dumps(build_policy_agent_state_replay(state), allow_nan=False)
        return messages, policy_messages

    async def _handle_global_ws(self, request):
        ws = aiohttp.web.WebSocketResponse(compress=False)
        await ws.prepare(request)

        with self._lock:
            self._global_clients.append(ws)
            self._ui_client_seen = True
            latest = self._latest_panel_step_msg
            walls = self._walls_msg
        self._cancel_ui_disconnect_shutdown()

        if not await self._send_ws_message(ws, json.dumps({"type": "hello"}, allow_nan=False)):
            self._remove_global_client(ws)
            return ws
        if walls:
            if not await self._send_ws_message(ws, walls):
                self._remove_global_client(ws)
                return ws
        if latest:
            if not await self._send_ws_message(ws, latest):
                self._remove_global_client(ws)
                return ws
        if not await self._send_ws_message(ws, self.heartbeat_message()):
            self._remove_global_client(ws)
            return ws

        async for msg in ws:
            if msg.type == aiohttp.WSMsgType.TEXT:
                continue

        self._remove_global_client(ws)
        return ws

    def _player_agent_id_from_query(self, query) -> int | None:
        if not self._player_tokens:
            return None
        try:
            slot = int(query.get("slot", ""))
        except (TypeError, ValueError):
            return None
        token = str(query.get("token", ""))
        if slot < 0 or slot >= len(self._player_tokens):
            return None
        if self._player_tokens[slot] != token:
            return None
        return slot

    async def _handle_ws(self, request, *, require_player_auth: bool = False):
        authenticated_agent_id = self._player_agent_id_from_query(request.query)
        if require_player_auth and self._player_tokens and authenticated_agent_id is None:
            return aiohttp.web.Response(status=403, text="invalid player token")
        ws = aiohttp.web.WebSocketResponse(compress=False)
        await ws.prepare(request)

        with self._lock:
            if authenticated_agent_id is None:
                agent_id = next_websocket_agent_id(self._next_agent_id, self._initial_replay.get("num_agents", 1))
                self._next_agent_id += 1
            else:
                agent_id = authenticated_agent_id
            self._clients.append(ws)

        assign_msg = json.dumps({
            "type": "assign",
            "agent_id": agent_id,
            "initial_replay": self._initial_replay,
            "admin": self.admin_state(),
            "debug_url": f"/policy-debug/{agent_id}",
        }, allow_nan=False)
        if not await self._send_ws_message(ws, assign_msg):
            self._remove_player_client(ws)
            return ws

        with self._lock:
            walls = self._walls_msg
            latest = self._latest_step_msg
        if walls:
            if not await self._send_ws_message(ws, walls):
                self._remove_player_client(ws)
                return ws
        if latest:
            if not await self._send_ws_message(ws, latest):
                self._remove_player_client(ws)
                return ws

        ignored_step_controls = 0
        async for msg in ws:
            if msg.type == aiohttp.WSMsgType.TEXT:
                data = json.loads(msg.data)
                ignored_step_controls = self.handle_player_message(
                    data,
                    ignored_step_controls,
                    authenticated_agent_id=authenticated_agent_id,
                )

        self._remove_player_client(ws)
        return ws

    async def _handle_agent_ws(self, request):
        return await self._handle_agent_scoped_ws(request, self._agent_clients, scope="agent")

    async def _handle_policy_ws(self, request):
        return await self._handle_agent_scoped_ws(request, self._policy_clients, scope="policy")

    async def _handle_policy_debug_ws(self, request):
        return await self._handle_agent_scoped_ws(request, self._policy_debug_clients, scope="policy-debug")

    async def _handle_agent_scoped_ws(self, request, clients: dict[int, list[aiohttp.web.WebSocketResponse]], *, scope: str):
        try:
            agent_id = int(request.match_info["agent_id"])
        except ValueError:
            return aiohttp.web.Response(status=404, text="agent_id must be an integer")
        if agent_id < 0:
            return aiohttp.web.Response(status=404, text="agent_id must be >= 0")

        ws = aiohttp.web.WebSocketResponse(compress=False)
        await ws.prepare(request)

        with self._lock:
            clients.setdefault(agent_id, []).append(ws)
            self._ui_client_seen = True
        self._cancel_ui_disconnect_shutdown()

        hello = json.dumps({
            "type": "hello",
            "scope": scope,
            "agent_id": agent_id,
            "admin": self.admin_state(),
        }, allow_nan=False)
        if not await self._send_ws_message(ws, hello):
            self._remove_agent_client(clients, agent_id, ws)
            return ws
        initial_state = self.policy_agent_state_message(agent_id) if scope == "policy" else self.agent_state_message(agent_id)
        if not await self._send_ws_message(ws, initial_state):
            self._remove_agent_client(clients, agent_id, ws)
            return ws

        ignored_step_controls = 0
        async for msg in ws:
            if msg.type != aiohttp.WSMsgType.TEXT:
                continue
            try:
                data = json.loads(msg.data)
                response = self.handle_agent_request(agent_id, data, ignored_step_controls)
            except (json.JSONDecodeError, ValueError) as exc:
                await self._send_ws_message(ws, json.dumps({"type": "error", "error": str(exc)}, allow_nan=False))
                continue
            ignored_step_controls = response["ignored_step_controls"]
            for payload in response["messages"]:
                if scope == "policy" and payload.get("type") == "agent_state":
                    payload = build_policy_agent_state_replay(payload)
                if not await self._send_ws_message(ws, json.dumps(payload, allow_nan=False)):
                    self._remove_agent_client(clients, agent_id, ws)
                    return ws
            if response["broadcast_state"]:
                await self._async_broadcast_agent_states(
                    {agent_id: self.agent_state_message(agent_id)},
                    exclude=ws,
                    policy_messages={agent_id: self.policy_agent_state_message(agent_id)},
                )

        self._remove_agent_client(clients, agent_id, ws)
        return ws

    def handle_player_message(
        self,
        data: dict,
        ignored_step_controls: int = 0,
        *,
        grant_step_on_action: bool = True,
        authenticated_agent_id: int | None = None,
    ) -> int:
        message_type = data.get("type")
        if message_type == "action":
            agent_id = authenticated_agent_id if authenticated_agent_id is not None else data["agent_id"]
            if self.queue_player_action(
                agent_id,
                data["action_name"],
                grant_step_on_action=grant_step_on_action,
            ):
                ignored_step_controls += 1
        elif message_type == "control":
            if ignored_step_controls > 0 and self._is_single_step_control(data):
                return ignored_step_controls - 1
            try:
                self.handle_admin_command(data)
            except ValueError:
                return ignored_step_controls
        return ignored_step_controls

    def handle_agent_message(self, agent_id: int, data: dict, ignored_step_controls: int = 0) -> int:
        policy_infos = data.get("policy_infos", data.get("infos"))
        if isinstance(policy_infos, dict):
            self.set_external_policy_infos(agent_id, policy_infos)
        message_type = data.get("type")
        if message_type == "action":
            action_name = data.get("action_name", data.get("action"))
            if not action_name:
                raise ValueError("agent action requires action_name")
            return self.handle_player_message(
                {"type": "action", "agent_id": agent_id, "action_name": str(action_name)},
                ignored_step_controls,
                grant_step_on_action=bool(data.get("client_action")),
            )
        return self.handle_player_message(data, ignored_step_controls)

    def set_external_policy_infos(self, agent_id: int, policy_infos: dict) -> None:
        with self._lock:
            existing = dict(self._external_policy_infos.get(agent_id, {}))
            existing.update(_websocket_policy_infos(policy_infos))
            self._external_policy_infos[agent_id] = existing

    def _merge_external_policy_infos(self) -> None:
        with self._lock:
            external_policy_infos = {
                agent_id: dict(policy_infos)
                for agent_id, policy_infos in self._external_policy_infos.items()
            }
        if not external_policy_infos:
            return
        policy_infos_by_agent = self._sim._context.setdefault("policy_infos", {})
        for agent_id, policy_infos in external_policy_infos.items():
            merged = dict(policy_infos_by_agent.get(agent_id, {}))
            merged.update(policy_infos)
            policy_infos_by_agent[agent_id] = merged

    def handle_agent_request(self, agent_id: int, data: dict, ignored_step_controls: int = 0) -> dict:
        message_type = data.get("type", "get_state")
        request_id = data.get("request_id")
        messages = []
        broadcast_state = message_type != "action" and isinstance(data.get("policy_infos", data.get("infos")), dict)
        if message_type in {"get", "get_state", "state"}:
            messages.append(self.agent_state(agent_id))
        elif message_type in {"get_log", "log"}:
            messages.append(self.agent_log_message(agent_id))
        elif message_type == "add_goal":
            goal_tasks = _normalize_goal_tasks(data.get("goal_tasks", data.get("goals", [])))
            current_goals = _active_goals_text(goal_tasks)
            policy_infos = {"current_goals": current_goals, "goal_tasks": goal_tasks}
            self.set_external_policy_infos(agent_id, policy_infos)
            message = {
                "type": "add_goal",
                "agent_id": agent_id,
                "current_goals": current_goals,
                "goal_tasks": goal_tasks,
            }
            messages.append(message)
        elif message_type in {"trigger_llm", "run_llm", "llm_trigger"}:
            trigger_id = self.request_llm_trigger(agent_id)
            messages.append({
                "type": "llm_trigger",
                "agent_id": agent_id,
                "llm_trigger_id": trigger_id,
            })
            broadcast_state = True
        else:
            ignored_step_controls = self.handle_agent_message(agent_id, data, ignored_step_controls)
        if request_id is not None:
            for message in messages:
                message.setdefault("request_id", request_id)
        return {"ignored_step_controls": ignored_step_controls, "messages": messages, "broadcast_state": broadcast_state}

    def agent_log_message(self, agent_id: int) -> dict:
        with self._lock:
            agent_log = list(self._agent_logs.get(agent_id, []))
        return {"type": "agent_log", "agent_id": agent_id, "agent_log": agent_log}

    def agent_state_message(self, agent_id: int) -> str:
        return json.dumps(self.agent_state(agent_id), allow_nan=False)

    def policy_agent_state_message(self, agent_id: int) -> str:
        return json.dumps(build_policy_agent_state_replay(self.agent_state(agent_id)), allow_nan=False)

    def agent_state(self, agent_id: int) -> dict:
        with self._lock:
            latest = self._latest_agent_state_msgs.get(agent_id)
            last_action = self._last_actions.get(agent_id)
            agent_log = list(self._agent_logs.get(agent_id, []))
            llm_trigger_id = self._llm_trigger_requests.get(agent_id, 0)
        if latest:
            state = json.loads(latest)
            with self._lock:
                external_policy_infos = dict(self._external_policy_infos.get(agent_id, {}))
            policy_infos = dict(state.get("policy_infos") or {})
            if external_policy_infos:
                policy_infos.update(external_policy_infos)
            state["policy_infos"] = _websocket_policy_infos(policy_infos)
            state.pop("policy_widgets", None)
            if isinstance(state.get("agent"), dict):
                state["agent"] = dict(state["agent"])
                if "policy_infos" in state["agent"]:
                    state["agent"]["policy_infos"] = _websocket_policy_infos(state["agent"].get("policy_infos"))
            state["last_action"] = last_action
            state["agent_log"] = agent_log
            if llm_trigger_id:
                state["llm_trigger_id"] = llm_trigger_id
            state.pop("wall_objects", None)
            return state
        sim = getattr(self, "_sim", None)
        policy_infos = {}
        if sim is not None:
            policy_infos = dict(getattr(sim, "_context", {}).get("policy_infos", {}).get(agent_id, {}))
        with self._lock:
            external_policy_infos = dict(self._external_policy_infos.get(agent_id, {}))
        if external_policy_infos:
            policy_infos.update(external_policy_infos)
        policy_infos = _websocket_policy_infos(policy_infos)
        state = build_agent_state_replay(
            {
                "step": getattr(sim, "current_step", None),
                "objects": [{"type_name": "agent", "agent_id": agent_id, "policy_infos": policy_infos}],
                "episode_stats": {},
            },
            agent_id,
            last_action=last_action,
            agent_log=agent_log,
        )
        if llm_trigger_id:
            state["llm_trigger_id"] = llm_trigger_id
        return state

    @classmethod
    def _is_single_step_control(cls, data: dict) -> bool:
        command, payload = cls._parse_admin_command(data)
        return command in {"step", "frame"} and int(payload.get("frames", 1)) == 1

    def _drain_pending_inputs(self):
        with self._lock:
            actions = dict(self._pending_actions)
            self._pending_actions.clear()
        for agent_id, action_name in actions.items():
            self.defer_user_action(agent_id, Action(name=action_name))

    def _broadcast(self, message: str, *, include_players: bool = True, include_global: bool = True):
        if not self._loop or self._loop.is_closed():
            return None
        coro = self._async_broadcast(message, include_players=include_players, include_global=include_global)
        try:
            return asyncio.run_coroutine_threadsafe(coro, self._loop)
        except RuntimeError:
            coro.close()
            return None

    def _broadcast_agent_states(self, messages: dict[int, str], *, policy_messages: dict[int, str] | None = None):
        if not messages or not self._loop or self._loop.is_closed():
            return None
        coro = self._async_broadcast_agent_states(messages, policy_messages=policy_messages)
        try:
            return asyncio.run_coroutine_threadsafe(coro, self._loop)
        except RuntimeError:
            coro.close()
            return None

    async def _async_broadcast(self, message: str, *, include_players: bool, include_global: bool):
        with self._lock:
            clients = []
            if include_players:
                clients.extend(self._clients)
            if include_global:
                clients.extend(self._global_clients)
        for ws in clients:
            if ws.closed:
                continue
            try:
                await asyncio.wait_for(ws.send_str(message), timeout=2.0)
            except (TimeoutError, ConnectionError):
                await ws.close()

    async def _async_broadcast_agent_states(
        self,
        messages: dict[int, str],
        exclude=None,
        *,
        policy_messages: dict[int, str] | None = None,
    ):
        policy_messages = policy_messages or messages
        with self._lock:
            clients = []
            for agent_id, message in messages.items():
                for pool in (self._agent_clients, self._policy_debug_clients):
                    clients.extend((ws, message) for ws in pool.get(agent_id, []) if ws is not exclude)
            for agent_id, message in policy_messages.items():
                clients.extend((ws, message) for ws in self._policy_clients.get(agent_id, []) if ws is not exclude)
        for ws, message in clients:
            if ws.closed:
                continue
            try:
                await asyncio.wait_for(ws.send_str(message), timeout=2.0)
            except (TimeoutError, ConnectionError):
                await ws.close()

    async def _async_broadcast_agent_message(self, message: str):
        with self._lock:
            clients = [
                ws
                for pool in (self._agent_clients, self._policy_clients, self._policy_debug_clients)
                for scoped_clients in pool.values()
                for ws in scoped_clients
            ]
        for ws in clients:
            if ws.closed:
                continue
            try:
                await asyncio.wait_for(ws.send_str(message), timeout=2.0)
            except (TimeoutError, ConnectionError):
                await ws.close()

    async def _send_ws_message(self, ws: aiohttp.web.WebSocketResponse, message: str) -> bool:
        try:
            await asyncio.wait_for(ws.send_str(message), timeout=2.0)
        except (TimeoutError, ConnectionError):
            await ws.close()
            return False
        return True

    async def _send_heartbeats(self) -> None:
        while True:
            await asyncio.sleep(self._heartbeat_interval)
            message = self.heartbeat_message()
            await self._async_broadcast(message, include_players=False, include_global=True)
            await self._async_broadcast_agent_message(message)

    def _remove_player_client(self, ws: aiohttp.web.WebSocketResponse) -> None:
        with self._lock:
            if ws in self._clients:
                self._clients.remove(ws)

    def _has_observer_clients_unlocked(self) -> bool:
        if any(not client.closed for client in self._global_clients):
            return True
        for pool in (self._agent_clients, self._policy_clients, self._policy_debug_clients):
            if any(not client.closed for clients in pool.values() for client in clients):
                return True
        return False

    def _remove_agent_client(
        self,
        clients_by_agent: dict[int, list[aiohttp.web.WebSocketResponse]],
        agent_id: int,
        ws: aiohttp.web.WebSocketResponse,
    ) -> None:
        with self._lock:
            clients = clients_by_agent.get(agent_id)
            if clients and ws in clients:
                clients.remove(ws)
            if clients == []:
                del clients_by_agent[agent_id]
            ui_closed = self._ui_client_seen and not self._playing and not self._has_observer_clients_unlocked()
        if ui_closed:
            self._schedule_ui_disconnect_shutdown()

    def _remove_global_client(self, ws: aiohttp.web.WebSocketResponse) -> None:
        with self._lock:
            if ws in self._global_clients:
                self._global_clients.remove(ws)
            ui_closed = (
                self._ui_client_seen
                and not self._playing
                and not self._has_observer_clients_unlocked()
            )
        if ui_closed:
            self._schedule_ui_disconnect_shutdown()

    def _schedule_ui_disconnect_shutdown(self) -> None:
        self._cancel_ui_disconnect_shutdown()
        if self._ui_disconnect_grace_seconds <= 0:
            self.request_shutdown()
            return
        timer = threading.Timer(self._ui_disconnect_grace_seconds, self._request_shutdown_if_ui_still_closed)
        timer.daemon = True
        self._ui_disconnect_shutdown_timer = timer
        timer.start()

    def _cancel_ui_disconnect_shutdown(self) -> None:
        timer = self._ui_disconnect_shutdown_timer
        self._ui_disconnect_shutdown_timer = None
        if timer is not None:
            timer.cancel()

    def _request_shutdown_if_ui_still_closed(self) -> None:
        with self._lock:
            ui_closed = (
                self._ui_client_seen
                and not self._playing
                and not self._has_observer_clients_unlocked()
            )
        if ui_closed:
            self.request_shutdown()

    def _agent_connection_counts_unlocked(self) -> list[dict]:
        agent_ids = set(range(int(self._initial_replay.get("num_agents", 0) or 0)))
        for pool in (self._agent_clients, self._policy_clients, self._policy_debug_clients):
            agent_ids.update(pool.keys())

        def count_open(pool: dict[int, list[aiohttp.web.WebSocketResponse]], agent_id: int) -> int:
            return sum(1 for ws in pool.get(agent_id, []) if not ws.closed)

        statuses = []
        for agent_id in sorted(agent_ids):
            agent = count_open(self._agent_clients, agent_id)
            policy = count_open(self._policy_clients, agent_id)
            policy_debug = count_open(self._policy_debug_clients, agent_id)
            statuses.append({
                "agent_id": agent_id,
                "agent": agent,
                "policy": policy,
                "policy_debug": policy_debug,
                "connected": bool(agent or policy or policy_debug),
            })
        return statuses

    def _admin_state_unlocked(self) -> dict:
        sim = getattr(self, "_sim", None)
        mode = "playing" if self._playing else ("step-on-action" if self._input_mode == "step-on-action" else "stopped")
        return {
            "ok": True,
            "playing": self._playing,
            "mode": mode,
            "step_on_action": self._input_mode == "step-on-action",
            "speed": self._tick_rate,
            "frame_requests": self._frame_requests,
            "port": self._port,
            "step": getattr(sim, "current_step", None),
            "shutdown_requested": self.shutdown_requested(),
        }

    def heartbeat_message(self) -> str:
        with self._lock:
            payload = {
                "type": "heartbeat",
                "server_time": time.time(),
                "admin": self._admin_state_unlocked(),
                "connections": {
                    "players": sum(1 for ws in self._clients if not ws.closed),
                    "global": sum(1 for ws in self._global_clients if not ws.closed),
                    "agents": sum(
                        1
                        for clients in self._agent_clients.values()
                        for ws in clients
                        if not ws.closed
                    ),
                    "policy": sum(
                        1
                        for clients in self._policy_clients.values()
                        for ws in clients
                        if not ws.closed
                    ),
                    "policy_debug": sum(
                        1
                        for clients in self._policy_debug_clients.values()
                        for ws in clients
                        if not ws.closed
                    ),
                },
                "agent_connections": self._agent_connection_counts_unlocked(),
            }
        return json.dumps(payload, allow_nan=False)

    @staticmethod
    def _status_html(status: dict) -> str:
        status_json = json.dumps(status, indent=2, sort_keys=True)
        components = status.get("components") or []
        endpoints = status.get("endpoints") or {}
        component_rows = "\n".join(
            "<tr>"
            f"<td>{html.escape(str(component.get('name', '')))}</td>"
            f"<td>{html.escape(str(component.get('state', '')))}</td>"
            f"<td>{html.escape(str(component.get('detail', '')))}</td>"
            "</tr>"
            for component in components
        )
        endpoint_rows = "\n".join(
            "<tr>"
            f"<td>{html.escape(str(name))}</td>"
            f"<td>{html.escape(str(url))}</td>"
            "</tr>"
            for name, url in endpoints.items()
        )
        status_json = html.escape(status_json)
        return f"""<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>Cogony Runner Status</title>
<style>
body {{ margin: 0; padding: 24px; background: #111; color: #ddd; font: 14px Consolas, Monaco, monospace; }}
a {{ color: #69b7ff; }}
table {{ border-collapse: collapse; min-width: 520px; margin: 16px 0; }}
th, td {{ border: 1px solid #333; padding: 8px 10px; text-align: left; vertical-align: top; }}
th {{ color: #aaa; font-weight: 600; }}
pre {{ background: #181818; border: 1px solid #333; padding: 12px; overflow: auto; }}
</style>
</head>
<body>
<h1>Cogony Runner Status</h1>
<p><a href="/status?format=json">/status?format=json</a></p>
<h2>Components</h2>
<table><thead><tr><th>Name</th><th>State</th><th>Detail</th></tr></thead><tbody>{component_rows}</tbody></table>
<h2>Endpoints</h2>
<table><thead><tr><th>Name</th><th>URL</th></tr></thead><tbody>{endpoint_rows}</tbody></table>
<h2>Raw</h2>
<pre>{status_json}</pre>
<script>setTimeout(() => location.reload(), 2000);</script>
</body>
</html>"""

    @staticmethod
    def _admin_html() -> str:
        return """<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>Cogony Admin</title>
<style>
body { margin: 0; padding: 24px; background: #111; color: #ddd; font: 14px Consolas, Monaco, monospace; }
button, input { background: #222; color: #ddd; border: 1px solid #555; border-radius: 3px; padding: 6px 10px; font: inherit; }
button { cursor: pointer; margin-right: 8px; }
button:hover { background: #333; }
input { width: 80px; }
#state { margin-top: 16px; color: #999; white-space: pre-wrap; }
</style>
</head>
<body>
<button onclick="send('stop')">Stop</button>
<button onclick="send('start')">Play</button>
<button onclick="send('step')">Frame</button>
<button onclick="send('set_mode', {mode: 'step-on-action'})">Step on Action</button>
<input id="speed" type="number" value="5" min="0.1" step="0.5">
<button onclick="send('set_ticks_per_second', {ticks_per_second: Number(document.getElementById('speed').value)})">Speed</button>
<pre id="state"></pre>
<script>
async function send(command, extra = {}) {
  const response = await fetch('/admin', {
    method: 'POST',
    headers: {'content-type': 'application/json'},
    body: JSON.stringify({command, ...extra})
  });
  render(await response.json());
}
async function refresh() {
  const response = await fetch('/admin?format=json');
  render(await response.json());
}
function render(state) {
  document.getElementById('state').textContent = JSON.stringify(state, null, 2);
  if (state.speed) document.getElementById('speed').value = state.speed;
}
refresh();
setInterval(refresh, 2000);
</script>
</body>
</html>"""
