from __future__ import annotations

import asyncio
import gzip
import json
import os
import tempfile
import zlib
from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse
from urllib.request import Request, urlopen

import uvicorn
from fastapi import FastAPI, WebSocket
from fastapi.responses import HTMLResponse
from starlette.websockets import WebSocketDisconnect

from .live_episode import LiveMettaGridEpisode

CLIENT_DIR = Path(__file__).parent / "clients"
GAME_NAME = "werecog"
GLOBAL_PROTOCOL = "coworld.global.v1"
START_GRACE_SECONDS = 0.5
POLICY_ACTION_TIMEOUT_SECONDS = 0.1
INITIAL_POLICY_ACTION_TIMEOUT_SECONDS = 5.0

def build_env(config: dict[str, Any]):
    from werecog import make_game

    return make_game(
        "werecog",
        num_agents=len(config["tokens"]),
        max_steps=int(config["max_steps"]),
        variants=config.get("variants") or None,
    )



def read_uri(uri: str) -> bytes:
    parsed = urlparse(uri)
    if parsed.scheme == "file":
        return Path(unquote(parsed.path)).read_bytes()
    if parsed.scheme in {"http", "https"}:
        with urlopen(uri, timeout=30) as response:  # noqa: S310 - Coworld supplies artifact URIs.
            return response.read()
    raise ValueError(f"Unsupported URI scheme for {uri!r}")


def write_uri(uri: str, data: bytes, *, method: str | None = None) -> None:
    parsed = urlparse(uri)
    if parsed.scheme == "file":
        path = Path(unquote(parsed.path))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return
    if parsed.scheme in {"http", "https"}:
        request = Request(uri, data=data, method=method or "PUT")  # noqa: S310 - Coworld supplies artifact URIs.
        request.add_header("Content-Type", "application/json")
        with urlopen(request, timeout=30) as response:  # noqa: S310
            response.read()
        return
    raise ValueError(f"Unsupported URI scheme for {uri!r}")


def output_path_for(uri: str, suffix: str) -> Path:
    parsed = urlparse(uri)
    if parsed.scheme == "file":
        path = Path(unquote(parsed.path))
        path.parent.mkdir(parents=True, exist_ok=True)
        return path
    path = Path(tempfile.mkdtemp(prefix=f"{GAME_NAME}-coworld-")) / suffix
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def load_json_uri(uri: str) -> dict[str, Any]:
    data = read_uri(uri)
    if uri.endswith(".json.gz"):
        data = gzip.decompress(data)
    elif uri.endswith(".json.z"):
        data = zlib.decompress(data)
    return json.loads(data)


class CoworldGame:
    def __init__(
        self,
        config: dict[str, Any],
        *,
        results_path: Path,
        replay_path: Path | None,
        request_shutdown: Callable[[], None],
    ) -> None:
        self.config = config
        self.tokens = list(config["tokens"])
        env = build_env(config)
        self.episode = LiveMettaGridEpisode.from_env(
            env,
            seed=int(config.get("seed", 0)),
            tokens=self.tokens,
            max_steps=int(config["max_steps"]),
            step_seconds=float(config.get("step_seconds", 0.05)),
            message_context={"game": GAME_NAME},
            start_grace_seconds=START_GRACE_SECONDS,
            wait_for_all_players=True,
            policy_action_timeout_seconds=POLICY_ACTION_TIMEOUT_SECONDS,
            initial_policy_action_timeout_seconds=INITIAL_POLICY_ACTION_TIMEOUT_SECONDS,
            disconnect_exception_types=(RuntimeError, WebSocketDisconnect),
            request_shutdown=request_shutdown,
        )
        self.episode.configure_artifacts(
            results_path=results_path,
            replay_path=replay_path,
            results_builder=self.results,
        )
        self.episode.configure_replay_events(
            baseline_builder=self.replay_baseline,
            step_builder=self.replay_step,
        )

    @property
    def sim(self):
        return self.episode.sim

    def results(self) -> dict[str, Any]:
        return {"game": GAME_NAME, "scores": self.episode.scores(), "steps": self.sim.current_step}

    def replay_baseline(self) -> dict[str, Any]:
        return {
            "type": "baseline",
            "game": GAME_NAME,
            "num_agents": len(self.tokens),
            "action_names": list(self.episode.action_names),
            "config": {key: value for key, value in self.config.items() if key != "tokens"},
        }

    def replay_step(self) -> dict[str, Any]:
        snapshot = self.episode.snapshot()
        return {"type": "step", "step": self.sim.current_step, "scores": snapshot["scores"], "slots": snapshot["slots"]}

    def global_message(self) -> dict[str, Any]:
        return {"protocol": GLOBAL_PROTOCOL, "type": "state", "game": GAME_NAME, **self.episode.snapshot()}

    def handle_global_message(self, message: dict[str, Any]) -> None:
        message_type = str(message.get("type", ""))
        if message_type == "action":
            slot = int(message.get("slot", message.get("agent_id", -1)))
            if 0 <= slot < len(self.tokens):
                self.episode.set_policy_action(slot, message, connection_id="global")
            return
        if message_type != "control":
            return
        command = str(message.get("command", "")).lower()
        if command in {"play", "resume", "start"}:
            self.episode.paused = False
        elif command in {"pause", "stop"}:
            self.episode.paused = True
        elif command == "speed":
            speed = float(message.get("speed", 1))
            if speed > 0:
                self.episode.step_seconds = 1.0 / speed


def create_app(config: dict[str, Any], request_shutdown: Callable[[], None]) -> FastAPI:
    results_uri = os.environ["COGAME_RESULTS_URI"]
    replay_uri = os.environ.get("COGAME_SAVE_REPLAY_URI")
    results_path = output_path_for(results_uri, "results.json")
    replay_path = output_path_for(replay_uri, "replay.json") if replay_uri else None

    def finish_episode() -> None:
        if urlparse(results_uri).scheme != "file" and results_path.exists():
            write_uri(results_uri, results_path.read_bytes(), method=os.environ.get("COGAME_RESULTS_METHOD"))
        if replay_uri and replay_path and urlparse(replay_uri).scheme != "file" and replay_path.exists():
            write_uri(replay_uri, replay_path.read_bytes(), method=os.environ.get("COGAME_SAVE_REPLAY_METHOD"))
        request_shutdown()

    game = CoworldGame(config, results_path=results_path, replay_path=replay_path, request_shutdown=finish_episode)
    app = FastAPI()

    @app.get("/healthz")
    def healthz() -> dict[str, bool]:
        return {"ok": True}

    @app.get("/client/global")
    def global_client() -> HTMLResponse:
        return HTMLResponse((CLIENT_DIR / "global.html").read_text())

    @app.get("/client/player")
    def player_client() -> HTMLResponse:
        return HTMLResponse((CLIENT_DIR / "player.html").read_text())

    @app.get("/client/replay")
    def replay_client() -> HTMLResponse:
        return HTMLResponse((CLIENT_DIR / "replay.html").read_text())

    @app.websocket("/global")
    async def global_viewer(websocket: WebSocket) -> None:
        await websocket.accept()
        sender = asyncio.create_task(_send_global_snapshots(websocket))
        receiver = asyncio.create_task(_drain_global_messages(websocket))
        done, pending = await asyncio.wait({sender, receiver}, return_when=asyncio.FIRST_COMPLETED)
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
        for task in done:
            task.result()

    async def _send_global_snapshots(websocket: WebSocket) -> None:
        while not game.episode.done:
            await websocket.send_json(game.global_message())
            await asyncio.sleep(max(0.05, game.episode.step_seconds))
        await websocket.send_json({"protocol": GLOBAL_PROTOCOL, "type": "final", **game.global_message()})

    async def _drain_global_messages(websocket: WebSocket) -> None:
        async for message in websocket.iter_json():
            game.handle_global_message(message)

    @app.websocket("/player")
    async def player(websocket: WebSocket) -> None:
        try:
            slot = int(websocket.query_params.get("slot", "-1"))
        except ValueError:
            await websocket.close(code=1008)
            return
        token = websocket.query_params.get("token", "")
        if slot < 0 or slot >= len(game.tokens) or game.tokens[slot] != token:
            await websocket.close(code=1008)
            return
        await websocket.accept()
        connection_id = await game.episode.connect_player(slot, websocket)
        try:
            async for message in websocket.iter_json():
                if game.episode.done:
                    break
                await game.episode.handle_player_message(connection_id, message)
        finally:
            game.episode.disconnect_player(connection_id)

    @app.websocket("/replay")
    async def replay_viewer(websocket: WebSocket) -> None:
        uri = os.environ.get("COGAME_LOAD_REPLAY_URI") or websocket.query_params.get("uri")
        if not uri:
            await websocket.close(code=1008)
            return
        await websocket.accept()
        await websocket.send_json({"type": "replay", "game": GAME_NAME, **load_json_uri(uri)})
        async for command in websocket.iter_json():
            await websocket.send_json({"type": "control", "command": command})

    return app


def create_replay_app() -> FastAPI:
    app = FastAPI()

    @app.get("/healthz")
    def healthz() -> dict[str, bool]:
        return {"ok": True}

    @app.get("/client/replay")
    def replay_client() -> HTMLResponse:
        return HTMLResponse((CLIENT_DIR / "replay.html").read_text())

    @app.websocket("/replay")
    async def replay_viewer(websocket: WebSocket) -> None:
        uri = os.environ.get("COGAME_LOAD_REPLAY_URI") or websocket.query_params.get("uri")
        if not uri:
            await websocket.close(code=1008)
            return
        await websocket.accept()
        await websocket.send_json({"type": "replay", "game": GAME_NAME, **load_json_uri(uri)})
        async for command in websocket.iter_json():
            await websocket.send_json({"type": "control", "command": command})

    return app


def load_app_from_env(request_shutdown: Callable[[], None]) -> FastAPI:
    if os.environ.get("COGAME_LOAD_REPLAY_URI") or os.environ.get("COGAME_REPLAY_SERVER") == "1":
        return create_replay_app()
    config = load_json_uri(os.environ["COGAME_CONFIG_URI"])
    return create_app(config, request_shutdown)


def main() -> None:
    server: uvicorn.Server

    def request_shutdown() -> None:
        server.should_exit = True

    host = os.environ.get("COGAME_HOST", "0.0.0.0")
    port = int(os.environ.get("COGAME_PORT", "8080"))
    server = uvicorn.Server(uvicorn.Config(load_app_from_env(request_shutdown), host=host, port=port))
    server.run()


if __name__ == "__main__":
    main()
