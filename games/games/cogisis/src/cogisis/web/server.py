"""Local Cogisis web server for admin, global, and agent clients."""

from __future__ import annotations

import json
import secrets
import threading
import time
from collections.abc import Callable
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse

from cogisis.client import client_frame, render_client_html
from cogisis.engine import PLAYER_TURN_ACTIONS, CogisisSimulator
from cogisis.session import EpisodeArtifacts, artifact_status, build_play_links

Policy = Callable[[CogisisSimulator], dict[int, str]]
PLAYER_CONNECTION_TTL_SECONDS = 3.0


class CogisisWebServer:
    """Owns one Cogisis simulator, local HTTP clients, and manual/autorun stepping."""

    def __init__(
        self,
        sim: CogisisSimulator,
        policy: Policy,
        *,
        policy_name: str,
        seed: int,
        max_steps: int,
        port: int = 0,
        tick_rate: float = 5.0,
        autorun: bool = False,
        artifact_workspace: Path | str | None = None,
    ) -> None:
        self.sim = sim
        self._policy = policy
        self._policy_name = policy_name
        self._seed = seed
        self._max_steps = max_steps
        self._tick_rate = tick_rate
        self._tick_interval = 1.0 / max(0.1, tick_rate)
        self._playing = autorun
        self._exit_when_done = autorun
        self._last_events: list[dict[str, Any]] = []
        self._lock = threading.RLock()
        self._shutdown_requested = threading.Event()
        self._stopped = False
        self._server_thread: threading.Thread | None = None
        self._runner_thread: threading.Thread | None = None
        self._artifacts = EpisodeArtifacts.create(artifact_workspace)
        self._player_tokens = [secrets.token_urlsafe(16) for _ in sorted(sim.world.characters)]
        self._player_seen_at: dict[int, float | None] = {slot: None for slot in sorted(sim.world.characters)}
        self._turn_queue = self._active_character_ids()
        self._turn_actions_remaining = PLAYER_TURN_ACTIONS
        self._public_base_url: str | None = None
        self._httpd = ThreadingHTTPServer(("127.0.0.1", port), self._handler_class())
        self._port = int(self._httpd.server_address[1])
        self._write_config()

    @property
    def port(self) -> int:
        return self._port

    @property
    def artifacts(self) -> EpisodeArtifacts:
        return self._artifacts

    def start(self) -> None:
        if self._server_thread is not None:
            return
        self._server_thread = threading.Thread(target=self._httpd.serve_forever, name="cogisis-http", daemon=True)
        self._server_thread.start()
        self._runner_thread = threading.Thread(target=self._run_loop, name="cogisis-runner", daemon=True)
        self._runner_thread.start()

    def wait(self) -> None:
        try:
            while not self._shutdown_requested.is_set():
                if self._exit_when_done and self.sim.done:
                    self.request_shutdown()
                    break
                time.sleep(0.1)
        except KeyboardInterrupt:
            self.request_shutdown()
        finally:
            self.stop()

    def stop(self) -> None:
        if self._stopped:
            return
        self._stopped = True
        self._shutdown_requested.set()
        self._write_episode_artifacts()
        self._httpd.shutdown()
        self._httpd.server_close()
        if self._server_thread is not None:
            self._server_thread.join(timeout=2.0)
        if self._runner_thread is not None:
            self._runner_thread.join(timeout=2.0)

    def request_shutdown(self) -> None:
        self._shutdown_requested.set()

    def local_base_url(self) -> str:
        return f"http://127.0.0.1:{self._port}"

    def set_public_base_url(self, public_base_url: str | None) -> None:
        self._public_base_url = public_base_url.rstrip("/") if public_base_url else None

    def _base_url(self) -> str:
        return self._public_base_url or self.local_base_url()

    def _request_base_url(self, request: BaseHTTPRequestHandler) -> str:
        if self._public_base_url:
            return self._public_base_url
        forwarded_host = _first_header_value(request.headers.get("X-Forwarded-Host", ""))
        host = forwarded_host or _first_header_value(request.headers.get("Host", ""))
        if not host or _is_local_host(host):
            return self.local_base_url()
        proto = _first_header_value(request.headers.get("X-Forwarded-Proto", ""))
        if not proto:
            proto = "https" if host.endswith(".trycloudflare.com") else "http"
        return f"{proto}://{host}".rstrip("/")

    def client_urls(self, *, base_url: str | None = None) -> dict[str, Any]:
        base_url = base_url or self._base_url()
        links = build_play_links(self._player_tokens, game_port=self._port, base_url=base_url)
        return {
            "admin": links.admin,
            "global": links.global_,
            "players": links.players,
            "global-client": f"{base_url}/global-client",
        }

    def endpoints(self, *, base_url: str | None = None) -> dict[str, str]:
        base_url = base_url or self._base_url()
        return {
            "healthz": f"{base_url}/healthz",
            "status": f"{base_url}/status",
            "admin": f"{base_url}/admin",
            "global": f"{base_url}/global",
            "player": f"{base_url}/player",
            "state": f"{base_url}/state.json",
        }

    def status(self, *, base_url: str | None = None) -> dict[str, Any]:
        with self._lock:
            root = base_url or self._base_url()
            stats = self.sim.stats()
            return {
                "ok": True,
                "runner": "cogisis_web_server",
                "artifacts": artifact_status(self._artifacts),
                "components": [
                    {
                        "name": "server",
                        "state": "running",
                        "detail": root,
                    },
                    {
                        "name": "game",
                        "state": "done" if self.sim.done else ("running" if self._playing else "paused"),
                        "detail": f"step {stats['steps']} / {self._max_steps}",
                    },
                    {
                        "name": "policies",
                        "state": "in-process",
                        "detail": f"{self._policy_name} x{len(self.sim.world.characters)}",
                    },
                ],
                "endpoints": self.endpoints(base_url=root),
                "client_urls": self.client_urls(base_url=root),
                "admin": self.admin_state(),
                "episode": {
                    "seed": self._seed,
                    "max_steps": self._max_steps,
                    "step": stats["steps"],
                    "done": stats["done"],
                },
                "policy": {
                    "name": self._policy_name,
                    "mode": "in-process",
                    "agents": len(self.sim.world.characters),
                },
            }

    def admin_state(self) -> dict[str, Any]:
        return {
            "playing": self._playing,
            "done": self.sim.done,
            "step": self.sim.world.current_step,
            "max_steps": self._max_steps,
            "tick_rate": self._tick_rate,
            "port": self._port,
            "turn": self._turn_token(),
        }

    def current_frame(self, *, heartbeat_slot: int | None = None, heartbeat_token: str = "") -> dict[str, Any]:
        with self._lock:
            if heartbeat_slot is not None:
                self._validate_player_token_unlocked(heartbeat_slot, heartbeat_token)
                self._mark_player_seen_unlocked(heartbeat_slot)
            return client_frame(
                self.sim,
                events=self._last_events,
                turn_token=self._turn_token_unlocked(),
                player_connections=self._player_connections_unlocked(),
            )

    def handle_admin_command(self, payload: dict[str, Any]) -> dict[str, Any]:
        command = str(payload.get("command", "")).strip().lower()
        if command in {"start", "play", "autorun"}:
            self._playing = True
            return self.admin_state()
        if command in {"stop", "pause"}:
            self._playing = False
            return self.admin_state()
        if command in {"step", "frame"}:
            frames = max(1, int(payload.get("frames", 1)))
            for _ in range(frames):
                if self.sim.done:
                    break
                self.step_once()
            return self.admin_state()
        if command in {"set_ticks_per_second", "speed", "tps"}:
            tick_rate = float(payload.get("ticks_per_second", payload.get("tps", self._tick_rate)))
            if tick_rate <= 0:
                raise ValueError("ticks_per_second must be > 0")
            self._tick_rate = tick_rate
            self._tick_interval = 1.0 / tick_rate
            return self.admin_state()
        if command in {"quit", "shutdown", "exit"}:
            self.request_shutdown()
            return self.admin_state()
        raise ValueError(f"unknown admin command: {command or '<empty>'}")

    def step_once(self) -> None:
        with self._lock:
            if self.sim.done:
                self._playing = False
                return
            result = self.sim.step_with_policy(self._policy)
            self._last_events = result.events
            self._turn_queue = self._active_character_ids()
            self._turn_actions_remaining = PLAYER_TURN_ACTIONS
            if result.done:
                self._playing = False
                self._write_episode_artifacts()

    def submit_player_action(
        self,
        slot: int,
        token: str,
        action: str,
        *,
        discard_cards: list[str] | None = None,
    ) -> dict[str, Any]:
        with self._lock:
            self._validate_player_token_unlocked(slot, token)
            self._mark_player_seen_unlocked(slot)
            if CogisisSimulator.action_is_metadata(action):
                result = self.sim.perform(slot, action)
                self._last_events = list(result.events)
                return {"admin": self.admin_state(), "frame": self.current_frame(), "events": list(result.events)}
            if self._playing:
                raise ValueError("pause autorun before submitting player actions")
            if self.sim.done:
                raise ValueError("game is finished")
            self._normalize_turn_queue_unlocked()
            holder = self._turn_queue[0] if self._turn_queue else None
            if holder != slot:
                raise ValueError(f"not player {slot}'s turn")
            valid_actions = self._valid_actions_unlocked(slot)
            if action not in valid_actions:
                raise ValueError(f"invalid action for player {slot}: {action}")

            result = self.sim.perform(
                slot,
                action,
                discard_cards=discard_cards,
                require_discard_selection=CogisisSimulator.action_cost(action) > 0,
            )
            events = list(result.events)
            if CogisisSimulator.action_ends_turn(action) or not self.sim.world.characters[slot].active():
                self._advance_turn_queue_unlocked(slot)
            else:
                self._turn_actions_remaining = max(0, self._turn_actions_remaining - 1)
                if self._turn_actions_remaining <= 0:
                    self._advance_turn_queue_unlocked(slot)
            self._prune_turn_queue_unlocked()
            if not self.sim.done and not self._turn_queue:
                event_result = self.sim.event_phase()
                events.extend(event_result.events)
                self._turn_queue = self._active_character_ids()
                self._turn_actions_remaining = PLAYER_TURN_ACTIONS
            self._last_events = events
            if self.sim.done:
                self._playing = False
                self._write_episode_artifacts()
            return {"admin": self.admin_state(), "frame": self.current_frame(), "events": events}

    def _run_loop(self) -> None:
        while not self._shutdown_requested.is_set():
            if self._playing and not self.sim.done:
                self.step_once()
                time.sleep(self._tick_interval)
            else:
                time.sleep(0.05)

    def _active_character_ids(self) -> list[int]:
        return [
            character_id
            for character_id, character in sorted(self.sim.world.characters.items())
            if character.active()
        ]

    def _validate_player_token_unlocked(self, slot: int, token: str) -> None:
        if slot < 0 or slot >= len(self._player_tokens) or token != self._player_tokens[slot]:
            raise PermissionError("invalid player token")

    def _mark_player_seen_unlocked(self, slot: int) -> None:
        self._player_seen_at[slot] = time.monotonic()

    def _player_connections_unlocked(self) -> dict[int, dict[str, Any]]:
        now = time.monotonic()
        connections: dict[int, dict[str, Any]] = {}
        for slot in sorted(self.sim.world.characters):
            seen_at = self._player_seen_at.get(slot)
            last_seen_seconds = None if seen_at is None else round(now - seen_at, 1)
            connections[slot] = {
                "id": slot,
                "connected": last_seen_seconds is not None and last_seen_seconds <= PLAYER_CONNECTION_TTL_SECONDS,
                "last_seen_seconds": last_seen_seconds,
            }
        return connections

    def _prune_turn_queue_unlocked(self) -> None:
        previous_holder = self._turn_queue[0] if self._turn_queue else None
        active_ids = set(self._active_character_ids())
        self._turn_queue = [character_id for character_id in self._turn_queue if character_id in active_ids]
        holder = self._turn_queue[0] if self._turn_queue else None
        if holder != previous_holder:
            self._turn_actions_remaining = PLAYER_TURN_ACTIONS
        if holder is None:
            self._turn_actions_remaining = 0

    def _normalize_turn_queue_unlocked(self) -> None:
        self._prune_turn_queue_unlocked()
        active_ids = set(self._active_character_ids())
        if not self._turn_queue and active_ids and not self.sim.done:
            self._turn_queue = sorted(active_ids)
            self._turn_actions_remaining = PLAYER_TURN_ACTIONS

    def _advance_turn_queue_unlocked(self, slot: int) -> None:
        if slot in self._turn_queue:
            self._turn_queue.remove(slot)
        self._turn_actions_remaining = PLAYER_TURN_ACTIONS if self._turn_queue else 0

    def _turn_token(self) -> dict[str, Any]:
        with self._lock:
            return self._turn_token_unlocked()

    def _turn_token_unlocked(self) -> dict[str, Any]:
        if self.sim.done:
            return {
                "phase": self.sim.world.phase.value,
                "holder": None,
                "queue": [],
                "label": "Finished",
                "actions_per_turn": PLAYER_TURN_ACTIONS,
                "actions_remaining": 0,
            }
        if self._playing:
            return {
                "phase": self.sim.world.phase.value,
                "holder": "policy",
                "queue": list(self._turn_queue),
                "label": "Policy running",
                "actions_per_turn": PLAYER_TURN_ACTIONS,
                "actions_remaining": 0,
            }
        self._normalize_turn_queue_unlocked()
        holder = self._turn_queue[0] if self._turn_queue else None
        actions_remaining = self._turn_actions_remaining if holder is not None else 0
        holder_name = self.sim.world.characters[holder].display_name() if holder is not None else None
        label = f"{holder_name} ready / {actions_remaining} actions left" if holder is not None else "No active cogs"
        return {
            "phase": self.sim.world.phase.value,
            "holder": holder,
            "queue": list(self._turn_queue),
            "label": label,
            "actions_per_turn": PLAYER_TURN_ACTIONS,
            "actions_remaining": actions_remaining,
        }

    def _valid_actions_unlocked(self, character_id: int) -> set[str]:
        frame = client_frame(self.sim, events=[], turn_token=self._turn_token_unlocked())
        for player in frame["players"]:
            if player["id"] == character_id:
                return set(player["available_actions"])
        return set()

    def _write_config(self) -> None:
        config = {
            "seed": self._seed,
            "max_steps": self._max_steps,
            "policy": self._policy_name,
            "agents": len(self.sim.world.characters),
        }
        self._artifacts.config_path.write_text(json.dumps(config, indent=2, sort_keys=True), encoding="utf-8")

    def _write_episode_artifacts(self) -> None:
        stats = self.sim.stats()
        results = {
            "steps": stats["steps"],
            "phase": stats["phase"],
            "done": stats["done"],
            "finished_reason": stats["finished_reason"],
            "ship_survived": stats["ship_survived"],
            "winners": stats["winners"],
            "survivors": stats["survivors"],
            "policy": self._policy_name,
        }
        self._artifacts.results_path.write_text(json.dumps(results, indent=2, sort_keys=True), encoding="utf-8")
        self._artifacts.replay_path.write_text(
            json.dumps({"frames": [self.current_frame()], "results": results}, indent=2, sort_keys=True),
            encoding="utf-8",
        )

    def _handler_class(self) -> type[BaseHTTPRequestHandler]:
        server = self

        class CogisisRequestHandler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802
                server._handle_get(self)

            def do_POST(self) -> None:  # noqa: N802
                server._handle_post(self)

            def log_message(self, format: str, *args: Any) -> None:
                return

        return CogisisRequestHandler

    def _handle_get(self, request: BaseHTTPRequestHandler) -> None:
        parsed = urlparse(request.path)
        path = parsed.path
        query = parse_qs(parsed.query)
        if path == "/favicon.ico":
            self._send_response(request, HTTPStatus.NO_CONTENT, b"", "text/plain")
            return
        if path == "/healthz":
            self._send_json(request, {"ok": True})
            return
        if path == "/state.json":
            try:
                heartbeat_slot = _optional_int(query.get("slot", [""])[0])
                heartbeat_token = query.get("token", [""])[0]
                self._send_json(request, self.current_frame(heartbeat_slot=heartbeat_slot, heartbeat_token=heartbeat_token))
            except PermissionError as exc:
                self._send_json(request, {"ok": False, "error": str(exc)}, status=HTTPStatus.FORBIDDEN)
            return
        if path == "/status":
            base_url = self._request_base_url(request)
            if _wants_json(request, query):
                self._send_json(request, self.status(base_url=base_url))
            else:
                self._send_html(request, self._status_html(base_url))
            return
        if path == "/admin":
            if _wants_json(request, query):
                self._send_json(request, self.admin_state())
            else:
                self._send_html(request, self._admin_html(self._request_base_url(request)))
            return
        if path in {"/", "/global", "/global-client"}:
            self._send_html(request, self._client_html("Cogisis global client", None, None, base_url=self._request_base_url(request)))
            return
        if path == "/player":
            slot = _optional_int(query.get("slot", ["0"])[0])
            token = query.get("token", [""])[0]
            if slot is None or slot < 0 or slot >= len(self._player_tokens) or token != self._player_tokens[slot]:
                self._send_response(request, HTTPStatus.FORBIDDEN, b"invalid player token", "text/plain")
                return
            with self._lock:
                self._mark_player_seen_unlocked(slot)
            self._send_html(
                request,
                self._client_html(
                    f"Cogisis player {slot}",
                    slot,
                    {"slot": slot, "token": token},
                    f"/state.json?{urlencode({'slot': slot, 'token': token})}",
                    base_url=self._request_base_url(request),
                ),
            )
            return
        self._send_response(request, HTTPStatus.NOT_FOUND, b"not found", "text/plain")

    def _handle_post(self, request: BaseHTTPRequestHandler) -> None:
        parsed = urlparse(request.path)
        if parsed.path == "/player/action":
            self._handle_player_action(request)
            return
        if parsed.path != "/admin":
            self._send_response(request, HTTPStatus.NOT_FOUND, b"not found", "text/plain")
            return
        try:
            payload = _read_json_body(request)
            state = self.handle_admin_command(payload)
        except (ValueError, json.JSONDecodeError) as exc:
            self._send_json(request, {"ok": False, "error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
            return
        self._send_json(request, {"ok": True, "admin": state, "status": self.status(base_url=self._request_base_url(request))})

    def _handle_player_action(self, request: BaseHTTPRequestHandler) -> None:
        try:
            payload = _read_json_body(request)
            slot = int(payload.get("slot"))
            token = str(payload.get("token", ""))
            action = str(payload.get("action", "")).strip()
            discard_raw = payload.get("discard", [])
            if discard_raw is None:
                discard_cards = []
            elif isinstance(discard_raw, list):
                discard_cards = [str(card_id) for card_id in discard_raw]
            else:
                raise ValueError("discard must be a list of card ids")
            result = self.submit_player_action(slot, token, action, discard_cards=discard_cards)
        except PermissionError as exc:
            self._send_json(request, {"ok": False, "error": str(exc)}, status=HTTPStatus.FORBIDDEN)
            return
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            self._send_json(request, {"ok": False, "error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
            return
        self._send_json(request, {"ok": True, **result})

    def _client_html(
        self,
        title: str,
        selected_agent_id: int | None,
        player_auth: dict[str, Any] | None,
        live_endpoint: str = "/state.json",
        base_url: str | None = None,
    ) -> str:
        player_urls = self.client_urls(base_url=base_url)["players"] if selected_agent_id is None else None
        return render_client_html(
            [self.current_frame()],
            title=title,
            live_endpoint=live_endpoint,
            selected_agent_id=selected_agent_id,
            player_auth=player_auth,
            player_urls=player_urls,
        )

    def _admin_html(self, base_url: str | None = None) -> str:
        status = self.status(base_url=base_url)
        urls = status["client_urls"]
        player_links = "\n".join(f"<li><a href=\"{url}\">Player {idx}</a></li>" for idx, url in enumerate(urls["players"]))
        status_json = json.dumps(status, indent=2, sort_keys=True)
        return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <link rel="icon" href="data:,">
  <title>Cogisis admin</title>
  <style>
    body {{ margin: 0; background: #10100f; color: #f1efe6; font: 14px ui-sans-serif, system-ui, sans-serif; }}
    main {{ max-width: 980px; margin: 0 auto; padding: 20px; display: grid; gap: 16px; }}
    section {{ border: 1px solid #3a3d34; border-radius: 8px; background: #181917; padding: 14px; }}
    h1, h2 {{ margin: 0 0 10px; letter-spacing: 0; }}
    h1 {{ font-size: 18px; }}
    h2 {{ font-size: 13px; color: #aaa590; text-transform: uppercase; }}
    button {{ height: 34px; border: 1px solid #4d5245; border-radius: 6px; padding: 0 12px; color: #f1efe6; background: #242720; font-weight: 760; cursor: pointer; }}
    button:hover {{ border-color: #58bda4; }}
    a {{ color: #7fd6c1; }}
    ul {{ margin: 8px 0 0; padding-left: 22px; }}
    pre {{ white-space: pre-wrap; overflow-wrap: anywhere; background: #11120f; border: 1px solid #33362e; border-radius: 6px; padding: 10px; }}
    .controls {{ display: flex; flex-wrap: wrap; gap: 8px; }}
  </style>
</head>
<body>
<main>
  <section>
    <h1>Cogisis admin</h1>
    <div class="controls">
      <button data-command="start">Start</button>
      <button data-command="stop">Stop</button>
      <button data-command="step">Step</button>
      <button data-command="quit">Quit</button>
    </div>
  </section>
  <section>
    <h2>Clients</h2>
    <p><a href="{urls["global"]}">Global client</a></p>
    <p><a href="{urls["admin"]}">Admin client</a></p>
    <h2>Players</h2>
    <ul>{player_links}</ul>
  </section>
  <section>
    <h2>Status</h2>
    <pre id="status">{_escape_html(status_json)}</pre>
  </section>
</main>
<script>
async function command(name) {{
  const response = await fetch("/admin", {{
    method: "POST",
    headers: {{ "Content-Type": "application/json" }},
    body: JSON.stringify({{ command: name }})
  }});
  const data = await response.json();
  document.getElementById("status").textContent = JSON.stringify(data.status || data, null, 2);
}}
for (const button of document.querySelectorAll("button[data-command]")) {{
  button.addEventListener("click", () => command(button.dataset.command));
}}
</script>
</body>
</html>"""

    def _status_html(self, base_url: str | None = None) -> str:
        status_url = f"{base_url.rstrip('/')}/status?format=json" if base_url else "/status?format=json"
        status_json = json.dumps(self.status(base_url=base_url), indent=2, sort_keys=True)
        return f"""<!doctype html>
<html lang="en">
<head><meta charset="utf-8"><link rel="icon" href="data:,"><title>Cogisis status</title></head>
<body style="background:#10100f;color:#f1efe6;font:13px ui-monospace,monospace">
<p><a style="color:#7fd6c1" href="{status_url}">/status?format=json</a></p>
<pre>{_escape_html(status_json)}</pre>
</body>
</html>"""

    @staticmethod
    def _send_json(request: BaseHTTPRequestHandler, data: Any, *, status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(data, sort_keys=True).encode()
        CogisisWebServer._send_response(request, status, body, "application/json")

    @staticmethod
    def _send_html(request: BaseHTTPRequestHandler, html: str, *, status: HTTPStatus = HTTPStatus.OK) -> None:
        CogisisWebServer._send_response(request, status, html.encode(), "text/html; charset=utf-8")

    @staticmethod
    def _send_response(request: BaseHTTPRequestHandler, status: HTTPStatus, body: bytes, content_type: str) -> None:
        request.send_response(status)
        request.send_header("Content-Type", content_type)
        request.send_header("Content-Length", str(len(body)))
        request.end_headers()
        if body:
            request.wfile.write(body)


def _read_json_body(request: BaseHTTPRequestHandler) -> dict[str, Any]:
    length = int(request.headers.get("Content-Length", "0") or "0")
    if length <= 0:
        return {}
    raw = request.rfile.read(length)
    return json.loads(raw.decode())


def _wants_json(request: BaseHTTPRequestHandler, query: dict[str, list[str]]) -> bool:
    return query.get("format") == ["json"] or "application/json" in request.headers.get("Accept", "")


def _optional_int(value: str) -> int | None:
    try:
        return int(value)
    except ValueError:
        return None


def _first_header_value(value: str) -> str:
    return value.split(",", 1)[0].strip()


def _is_local_host(host: str) -> bool:
    host_name = host.rsplit(":", 1)[0].strip("[]").lower()
    return host_name in {"127.0.0.1", "localhost", "::1"}


def _escape_html(value: str) -> str:
    return value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
