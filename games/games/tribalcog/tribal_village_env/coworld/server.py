from __future__ import annotations

import asyncio
import base64
import gzip
import json
import os
import tempfile
import zlib
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse
from urllib.request import Request, urlopen

import numpy as np
import uvicorn
from fastapi import FastAPI, HTTPException, WebSocket
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from starlette.websockets import WebSocketDisconnect

from tribal_village_env.environment import ACTION_SPACE_SIZE, TribalVillageEnv

CLIENTS_DIR = Path(__file__).parent / "clients"
PROJECT_ROOT = Path(__file__).resolve().parents[2]
WASM_DIR = PROJECT_ROOT / "build" / "web"
WASM_SHELL = PROJECT_ROOT / "scripts" / "shell_minimal.html"
WASM_REQUIRED_ASSETS = (
    "tribal_village.js",
    "tribal_village.wasm",
    "tribal_village.data",
)
WASM_ASSET_NAMES = set(WASM_REQUIRED_ASSETS) | {"tribal_village.html"}
WASM_MEDIA_TYPES = {
    ".data": "application/octet-stream",
    ".html": "text/html",
    ".js": "application/javascript",
    ".wasm": "application/wasm",
}
HTTP_USER_AGENT = "tribalcog-coworld/0.1"

TEAM_COUNT = 8
AGENTS_PER_TEAM = 125
PLAYER_SLOT_COUNT = TEAM_COUNT * AGENTS_PER_TEAM
NPC_AGENT_COUNT = 6
TOTAL_AGENT_COUNT = PLAYER_SLOT_COUNT + NPC_AGENT_COUNT

TERRAIN_LABELS = [
    "empty",
    "water",
    "bridge",
    "fertile",
    "road",
    "grass",
    "dune",
    "sand",
    "snow",
    "mountain",
    "ramp_up_n",
    "ramp_up_s",
    "ramp_up_w",
    "ramp_up_e",
    "ramp_down_n",
    "ramp_down_s",
    "ramp_down_w",
    "ramp_down_e",
]
THING_LABELS = [
    "agent",
    "wall",
    "door",
    "tree",
    "wheat",
    "fish",
    "relic",
    "stone",
    "gold",
    "bush",
    "cactus",
    "stalagmite",
    "magma",
    "altar",
    "spawner",
    "tumor",
    "cow",
    "bear",
    "wolf",
    "corpse",
    "skeleton",
    "clay_oven",
    "weaving_loom",
    "outpost",
    "guard_tower",
    "barrel",
    "mill",
    "granary",
    "lumber_camp",
    "quarry",
    "mining_camp",
    "stump",
    "lantern",
    "town_center",
    "house",
    "barracks",
    "archery_range",
    "stable",
    "siege_workshop",
    "mangonel_workshop",
    "trebuchet_workshop",
    "blacksmith",
    "market",
    "dock",
    "monastery",
    "university",
    "castle",
    "wonder",
    "goblin_hive",
    "goblin_hut",
    "goblin_totem",
    "stubble",
    "cliff_edge_n",
    "cliff_edge_e",
    "cliff_edge_s",
    "cliff_edge_w",
    "cliff_corner_in_ne",
    "cliff_corner_in_se",
    "cliff_corner_in_sw",
    "cliff_corner_in_nw",
    "cliff_corner_out_ne",
    "cliff_corner_out_se",
    "cliff_corner_out_sw",
    "cliff_corner_out_nw",
    "waterfall_n",
    "waterfall_e",
    "waterfall_s",
    "waterfall_w",
]
UNIT_CLASS_LABELS = [
    "villager",
    "man_at_arms",
    "archer",
    "scout",
    "knight",
    "monk",
    "battering_ram",
    "mangonel",
    "trebuchet",
    "goblin",
    "boat",
    "trade_cog",
    "samurai",
    "longbowman",
    "cataphract",
    "woad_raider",
    "teutonic_knight",
    "huskarl",
    "mameluke",
    "janissary",
    "king",
    "long_swordsman",
    "champion",
    "light_cavalry",
    "hussar",
    "crossbowman",
    "arbalester",
    "galley",
    "fire_ship",
    "fishing_ship",
    "transport_ship",
    "demo_ship",
    "cannon_galleon",
    "scorpion",
    "cavalier",
    "paladin",
    "camel",
    "heavy_camel",
    "imperial_camel",
    "skirmisher",
    "elite_skirmisher",
    "cavalry_archer",
    "heavy_cavalry_archer",
    "hand_cannoneer",
]
ACTION_NAMES = [
    "noop",
    "move",
    "attack",
    "use",
    "swap",
    "put",
    "plant_lantern",
    "plant_resource",
    "build",
    "orient",
    "set_rally_point",
]
ORIENTATION_LABELS = [
    "north",
    "south",
    "west",
    "east",
    "north_west",
    "north_east",
    "south_west",
    "south_east",
]
TERRAIN_LAYER_START = 0
THING_LAYER_START = len(TERRAIN_LABELS)
TEAM_LAYER = THING_LAYER_START + len(THING_LABELS)
ORIENTATION_LAYER = TEAM_LAYER + 1
UNIT_CLASS_LAYER = TEAM_LAYER + 2
IDLE_LAYER = TEAM_LAYER + 3
TINT_LAYER = TEAM_LAYER + 4
OBSCURED_LAYER = TEAM_LAYER + 14

TERRAIN_GLYPHS = {
    "water": "~",
    "bridge": "=",
    "fertile": ",",
    "road": ":",
    "grass": ".",
    "dune": "^",
    "sand": ".",
    "snow": "*",
    "mountain": "^",
}
THING_GLYPHS = {
    "agent": "@",
    "tree": "T",
    "wheat": "w",
    "fish": "f",
    "relic": "r",
    "stone": "s",
    "gold": "g",
    "bush": "b",
    "cactus": "c",
    "tumor": "x",
    "cow": "C",
    "bear": "B",
    "wolf": "W",
    "skeleton": "S",
    "town_center": "H",
    "house": "h",
    "wall": "#",
    "door": "+",
    "lantern": "l",
}
TERRAIN_COLORS = {
    "water": "#3276a8",
    "bridge": "#8f7a52",
    "fertile": "#6a8f3f",
    "road": "#7a715d",
    "grass": "#4f8146",
    "dune": "#b69b55",
    "sand": "#c8ad74",
    "snow": "#d8e7e8",
    "mountain": "#777b80",
}
TEAM_COLORS = [
    "#e3655b",
    "#d59643",
    "#d4c742",
    "#75b84a",
    "#42a868",
    "#45a9c7",
    "#6f8be8",
    "#b46ce0",
]


def wasm_media_type(path: Path) -> str:
    return WASM_MEDIA_TYPES.get(path.suffix, "application/octet-stream")


def resolve_wasm_asset_path(root: Path, asset_path: str) -> Path:
    if asset_path not in WASM_ASSET_NAMES:
        raise FileNotFoundError(asset_path)

    resolved_root = root.resolve()
    candidate = (resolved_root / asset_path).resolve()
    try:
        candidate.relative_to(resolved_root)
    except ValueError as exc:
        raise ValueError(f"Invalid WASM asset path: {asset_path}") from exc
    if not candidate.is_file():
        raise FileNotFoundError(candidate)
    return candidate


def missing_wasm_assets(root: Path = WASM_DIR) -> list[str]:
    return [asset for asset in WASM_REQUIRED_ASSETS if not (root / asset).is_file()]


def wasm_client_html() -> str:
    html_path = WASM_DIR / "tribal_village.html"
    if html_path.is_file():
        return html_path.read_text()

    html = WASM_SHELL.read_text()
    script = '<script async type="text/javascript" src="tribal_village.js"></script>'
    return html.replace("{{{ SCRIPT }}}", script).replace(
        "<title>Emscripten-Generated Code</title>",
        "<title>Tribal Cog WASM</title>",
    )


def wasm_missing_html(missing_assets: list[str]) -> str:
    missing = ", ".join(missing_assets)
    return (
        "<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">"
        "<title>Tribal Cog WASM</title></head><body><main>"
        "<h1>Tribal Cog WASM client is not built</h1>"
        f"<p>Missing: <code>{missing}</code></p>"
        "<p>Run <code>nimble wasm</code> from games/tribalcog, then reload.</p>"
        "</main></body></html>"
    )


@dataclass(frozen=True)
class CoworldConfig:
    tokens: list[str]
    max_steps: int
    seed: int
    step_seconds: float
    victory_condition: int
    player_connect_timeout_seconds: float
    render_every_steps: int

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CoworldConfig":
        tokens = [str(token) for token in data.get("tokens", [])]
        if not 1 <= len(tokens) <= PLAYER_SLOT_COUNT:
            raise ValueError(
                f"Tribal Cog Coworld requires between 1 and {PLAYER_SLOT_COUNT} tokens, "
                f"got {len(tokens)}"
            )
        if any(not token for token in tokens):
            raise ValueError("Coworld tokens must be non-empty strings")
        max_steps = int(data.get("max_steps", 1000))
        if max_steps < 1:
            raise ValueError("max_steps must be at least 1")
        step_seconds = float(data.get("step_seconds", 0.05))
        if step_seconds <= 0:
            raise ValueError("step_seconds must be greater than 0")
        render_every_steps = int(data.get("render_every_steps", 5))
        if render_every_steps < 1:
            raise ValueError("render_every_steps must be at least 1")
        return cls(
            tokens=tokens,
            max_steps=max_steps,
            seed=int(data.get("seed", 0)),
            step_seconds=step_seconds,
            victory_condition=int(data.get("victory_condition", 0)),
            player_connect_timeout_seconds=float(
                data.get("player_connect_timeout_seconds", 180)
            ),
            render_every_steps=render_every_steps,
        )


def read_data(uri: str) -> bytes:
    parsed = urlparse(uri)
    if parsed.scheme in ("http", "https"):
        request = Request(uri, headers={"User-Agent": HTTP_USER_AGENT})
        with urlopen(request, timeout=30) as response:
            return response.read()
    if parsed.scheme == "file":
        return Path(unquote(parsed.path)).read_bytes()
    if parsed.scheme == "":
        return Path(uri).read_bytes()
    raise ValueError(f"Unsupported URI for read_data: {uri}")


def post_data(uri: str, data: bytes | str, *, content_type: str) -> None:
    if isinstance(data, str):
        data = data.encode()

    parsed = urlparse(uri)
    if parsed.scheme in ("http", "https"):
        request = Request(uri, data=data, method="POST")
        request.add_header("Content-Type", content_type)
        request.add_header("User-Agent", HTTP_USER_AGENT)
        with urlopen(request, timeout=60):
            return
    if parsed.scheme == "file":
        path = Path(unquote(parsed.path))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return
    if parsed.scheme == "":
        path = Path(uri)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return
    raise ValueError(f"Unsupported URI for post_data: {uri}")


def load_replay_data(replay_uri: str) -> dict[str, Any]:
    replay_data = read_data(replay_uri)
    if replay_uri.endswith(".json.z"):
        replay_data = zlib.decompress(replay_data)
    elif replay_uri.endswith(".json.gz"):
        replay_data = gzip.decompress(replay_data)
    else:
        with suppress(zlib.error):
            replay_data = zlib.decompress(replay_data)
    return json.loads(replay_data)


def slot_to_team(slot: int) -> int:
    return slot // AGENTS_PER_TEAM


def slot_team_index(slot: int) -> int:
    return slot % AGENTS_PER_TEAM


def decode_action(message: dict[str, Any]) -> int:
    raw_action = message.get("action", 0)
    if isinstance(raw_action, dict):
        verb = int(raw_action.get("verb", 0))
        argument = int(raw_action.get("argument", 0))
        raw_action = verb * 28 + argument
    try:
        action = int(raw_action)
    except (TypeError, ValueError):
        return 0
    if action < 0 or action >= ACTION_SPACE_SIZE:
        return 0
    return action


def _first_active_layer(obs: np.ndarray, labels: list[str], start: int, x: int, y: int) -> str | None:
    for offset, label in enumerate(labels):
        if int(obs[start + offset, x, y]) > 0:
            return label
    return None


def _indexed_label(labels: list[str], value: int) -> str | None:
    index = value - 1
    if 0 <= index < len(labels):
        return labels[index]
    return None


def _cell_sprite(terrain: str, thing: str | None, obscured: bool) -> str:
    if obscured:
        return "fog.unknown"
    if thing:
        return f"thing.{thing}"
    return f"terrain.{terrain}"


def _cell_glyph(terrain: str, thing: str | None, obscured: bool) -> str:
    if obscured:
        return "?"
    if thing:
        return THING_GLYPHS.get(thing, thing[:1].upper())
    return TERRAIN_GLYPHS.get(terrain, ".")


def _cell_color(terrain: str, team_id: int | None, obscured: bool) -> str:
    if obscured:
        return "#1b2021"
    if team_id is not None and 0 <= team_id < len(TEAM_COLORS):
        return TEAM_COLORS[team_id]
    return TERRAIN_COLORS.get(terrain, "#4b534c")


def sprite_view_from_observation(obs: np.ndarray) -> dict[str, Any]:
    width = int(obs.shape[1])
    height = int(obs.shape[2])
    cells: list[list[dict[str, Any]]] = []
    for y in range(height):
        row: list[dict[str, Any]] = []
        for x in range(width):
            terrain = _first_active_layer(obs, TERRAIN_LABELS, TERRAIN_LAYER_START, x, y) or "empty"
            thing = _first_active_layer(obs, THING_LABELS, THING_LAYER_START, x, y)
            team_value = int(obs[TEAM_LAYER, x, y])
            orientation_value = int(obs[ORIENTATION_LAYER, x, y])
            unit_class_value = int(obs[UNIT_CLASS_LAYER, x, y])
            obscured = bool(int(obs[OBSCURED_LAYER, x, y]))
            team_id = team_value - 1 if team_value > 0 else None
            cell: dict[str, Any] = {
                "x": x,
                "y": y,
                "terrain": terrain,
                "thing": thing,
                "sprite": _cell_sprite(terrain, thing, obscured),
                "glyph": _cell_glyph(terrain, thing, obscured),
                "color": _cell_color(terrain, team_id, obscured),
                "team_id": team_id,
                "unit_class": _indexed_label(UNIT_CLASS_LABELS, unit_class_value),
                "orientation": _indexed_label(ORIENTATION_LABELS, orientation_value),
                "idle": bool(int(obs[IDLE_LAYER, x, y])),
                "tint": int(obs[TINT_LAYER, x, y]),
                "obscured": obscured,
            }
            row.append(cell)
        cells.append(row)
    return {
        "protocol": "tribalcog-sprite-v1",
        "width": width,
        "height": height,
        "radius": width // 2,
        "center": {"x": width // 2, "y": height // 2},
        "cells": cells,
        "legend": {
            "terrain": TERRAIN_LABELS,
            "thing": THING_LABELS,
            "unit_class": UNIT_CLASS_LABELS,
            "action": ACTION_NAMES,
            "orientation": ORIENTATION_LABELS,
        },
    }


def _local_replay_path(replay_uri: str) -> Path:
    parsed = urlparse(replay_uri)
    if parsed.scheme == "file":
        return Path(unquote(parsed.path))
    if parsed.scheme == "":
        return Path(replay_uri)
    return Path(tempfile.mkdtemp(prefix="tribalcog-coworld-")) / "replay.json.z"


class TribalCogCoworld:
    def __init__(self, config: CoworldConfig, results_uri: str, replay_uri: str):
        self.config = config
        self.results_uri = results_uri
        self.replay_uri = replay_uri
        self.local_replay_path = _local_replay_path(replay_uri)
        self.local_replay_path.parent.mkdir(parents=True, exist_ok=True)
        os.environ["TV_REPLAY_PATH"] = str(self.local_replay_path)
        os.environ["TV_REPLAY_LABEL"] = "Tribal Cog Coworld Replay"

        self.env = TribalVillageEnv(
            config={
                "max_steps": config.max_steps,
                "victory_condition": config.victory_condition,
                "ai_mode": "external",
                "render_mode": "rgb_array",
            }
        )
        self.env.reset(seed=config.seed)

        self.players: dict[int, WebSocket] = {}
        self.global_viewers: set[WebSocket] = set()
        self.player_slot_count = len(config.tokens)
        self.actions = [0 for _ in range(TOTAL_AGENT_COUNT)]
        self.last_rewards = [0.0 for _ in range(self.player_slot_count)]
        self.scores = [0.0 for _ in range(self.player_slot_count)]
        self.team_scores = [0.0 for _ in range(TEAM_COUNT)]
        self.started = False
        self.done = False
        self.paused = False
        self.finalized = False
        self.step_task: asyncio.Task[None] | None = None
        self.lock = asyncio.Lock()

    def close(self) -> None:
        self.env.close()

    def validate_slot(self, slot: int, token: str) -> bool:
        return 0 <= slot < self.player_slot_count and self.config.tokens[slot] == token

    def player_observation(self, slot: int, *, final: bool = False) -> dict[str, Any]:
        obs = np.ascontiguousarray(self.env.observations[slot])
        return {
            "type": "final" if final else "observation",
            "slot": slot,
            "agent_id": slot,
            "team_id": slot_to_team(slot),
            "team_agent_index": slot_team_index(slot),
            "step": self.env.step_count,
            "max_steps": self.config.max_steps,
            "started": self.started,
            "done": self.done or final,
            "reward": self.last_rewards[slot],
            "score": self.scores[slot],
            "team_score": self.team_scores[slot_to_team(slot)],
            "action_space": ACTION_SPACE_SIZE,
            "action_names": ACTION_NAMES,
            "orientation_names": ORIENTATION_LABELS,
            "sprite_view": sprite_view_from_observation(obs),
            "observation": {
                "dtype": "uint8",
                "shape": list(obs.shape),
                "encoding": "base64",
                "data": base64.b64encode(obs.tobytes()).decode("ascii"),
            },
        }

    def snapshot(self, *, include_frame: bool = True) -> dict[str, Any]:
        snapshot: dict[str, Any] = {
            "type": "state",
            "step": self.env.step_count,
            "max_steps": self.config.max_steps,
            "started": self.started,
            "paused": self.paused,
            "done": self.done,
            "connected_players": len(self.players),
            "total_player_slots": self.player_slot_count,
            "team_scores": self.team_scores.copy(),
            "team_connected_players": [
                sum(1 for slot in self.players if slot_to_team(slot) == team)
                for team in range(TEAM_COUNT)
            ],
            "step_seconds": self.config.step_seconds,
        }
        if include_frame and (
            self.env.step_count % self.config.render_every_steps == 0 or self.done
        ):
            frame = np.ascontiguousarray(self.env.render())
            snapshot["frame"] = {
                "width": int(frame.shape[1]),
                "height": int(frame.shape[0]),
                "encoding": "rgb-base64",
                "data": base64.b64encode(frame.tobytes()).decode("ascii"),
            }
        return snapshot

    async def maybe_start(self) -> None:
        if self.started or self.done:
            return
        self.started = True
        self.step_task = asyncio.create_task(self.play())

    async def play(self) -> None:
        while self.env.step_count < self.config.max_steps and not self.done:
            if self.paused:
                await asyncio.sleep(0.1)
                continue
            async with self.lock:
                action_values = self.actions.copy()
                self.actions = [0 for _ in range(TOTAL_AGENT_COUNT)]
            action_dict = {
                f"agent_{agent_id}": action
                for agent_id, action in enumerate(action_values[:PLAYER_SLOT_COUNT])
                if action != 0
            }
            self.env.step(action_dict)
            self._update_scores()
            await self.broadcast()
            await asyncio.sleep(self.config.step_seconds)
        await self.finalize()

    async def broadcast(self) -> None:
        player_tasks = [
            player.send_json(self.player_observation(slot))
            for slot, player in list(self.players.items())
        ]
        global_tasks = [
            viewer.send_json(self.snapshot()) for viewer in list(self.global_viewers)
        ]
        if player_tasks or global_tasks:
            await asyncio.gather(*player_tasks, *global_tasks, return_exceptions=True)

    def _update_scores(self) -> None:
        rewards = [float(value) for value in self.env.rewards[: self.player_slot_count]]
        self.last_rewards = rewards
        for slot, reward in enumerate(rewards):
            self.scores[slot] += reward
        self.team_scores = [
            float(sum(self.scores[start : start + AGENTS_PER_TEAM]))
            for start in range(0, PLAYER_SLOT_COUNT, AGENTS_PER_TEAM)
        ]

    def results(self) -> dict[str, Any]:
        return {
            "scores": [float(score) for score in self.scores],
            "team_scores": [float(score) for score in self.team_scores],
            "steps": int(self.env.step_count),
            "winner_team": winner_team(self.team_scores),
            "victory_condition": int(self.config.victory_condition),
            "truncation_reason": "max_steps"
            if self.env.step_count >= self.config.max_steps
            else "game_over",
        }

    async def finalize(self) -> None:
        if self.finalized:
            return
        self.done = True
        self.finalized = True
        results = self.results()
        post_data(
            self.results_uri,
            json.dumps(results),
            content_type="application/json",
        )
        replay_bytes = self._replay_bytes(results)
        post_data(
            self.replay_uri,
            replay_bytes,
            content_type="application/octet-stream",
        )
        for slot, player in list(self.players.items()):
            with suppress(Exception):
                await player.send_json(self.player_observation(slot, final=True))
        for viewer in list(self.global_viewers):
            with suppress(Exception):
                await viewer.send_json(self.snapshot())
        if server is not None:
            server.should_exit = True

    def _replay_bytes(self, results: dict[str, Any]) -> bytes:
        if self.local_replay_path.exists():
            return self.local_replay_path.read_bytes()
        fallback = {
            "version": 1,
            "label": "Tribal Cog Coworld Replay",
            "results": results,
            "steps": self.env.step_count,
            "team_scores": self.team_scores,
        }
        return json.dumps(fallback).encode()


def winner_team(team_scores: list[float]) -> int | None:
    if not team_scores:
        return None
    best_score = max(team_scores)
    winners = [idx for idx, score in enumerate(team_scores) if score == best_score]
    return winners[0] if len(winners) == 1 else None


runtime: TribalCogCoworld | None = None
server: uvicorn.Server | None = None


@asynccontextmanager
async def lifespan(_app: FastAPI):
    global runtime
    timeout_task: asyncio.Task[None] | None = None
    if os.environ.get("COGAME_REPLAY_SERVER") != "1":
        config = CoworldConfig.from_dict(
            json.loads(read_data(os.environ["COGAME_CONFIG_URI"]))
        )
        runtime = TribalCogCoworld(
            config=config,
            results_uri=os.environ["COGAME_RESULTS_URI"],
            replay_uri=os.environ["COGAME_SAVE_REPLAY_URI"],
        )
        timeout_task = asyncio.create_task(_start_after_player_connect_timeout())
    yield
    if timeout_task is not None:
        timeout_task.cancel()
        with suppress(asyncio.CancelledError):
            await timeout_task
    if runtime is not None:
        runtime.close()
        runtime = None


app = FastAPI(lifespan=lifespan)


def _runtime() -> TribalCogCoworld:
    if runtime is None:
        raise RuntimeError("Tribal Cog Coworld runtime is not initialized")
    return runtime


@app.get("/healthz")
def healthz() -> dict[str, bool]:
    return {"ok": True}


@app.get("/clients/global")
def global_client() -> HTMLResponse:
    return HTMLResponse((CLIENTS_DIR / "global.html").read_text())


@app.get("/clients/player")
def player_client() -> HTMLResponse:
    return HTMLResponse((CLIENTS_DIR / "player.html").read_text())


@app.get("/clients/replay")
def replay_client() -> HTMLResponse:
    return HTMLResponse((CLIENTS_DIR / "replay.html").read_text())


@app.get("/clients/wasm")
def wasm_client_redirect() -> RedirectResponse:
    return RedirectResponse("/clients/wasm/")


@app.get("/clients/wasm/")
def wasm_client() -> HTMLResponse:
    missing_assets = missing_wasm_assets()
    if missing_assets:
        return HTMLResponse(wasm_missing_html(missing_assets), status_code=404)
    return HTMLResponse(wasm_client_html())


@app.get("/clients/wasm/{asset_path:path}")
def wasm_asset(asset_path: str) -> FileResponse:
    try:
        path = resolve_wasm_asset_path(WASM_DIR, asset_path)
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=404) from exc
    return FileResponse(path, media_type=wasm_media_type(path))


@app.websocket("/global")
async def global_viewer(websocket: WebSocket) -> None:
    state = _runtime()
    await websocket.accept()
    state.global_viewers.add(websocket)
    try:
        include_frame = websocket.query_params.get("frame") == "1"
        await websocket.send_json(state.snapshot(include_frame=include_frame))
        async for _ in websocket.iter_json():
            pass
    finally:
        state.global_viewers.discard(websocket)


@app.websocket("/replay")
async def replay_viewer(websocket: WebSocket) -> None:
    if "uri" not in websocket.query_params:
        await websocket.close(code=1008)
        return
    await websocket.accept()
    try:
        replay = load_replay_data(websocket.query_params["uri"])
    except (OSError, ValueError, json.JSONDecodeError, zlib.error, gzip.BadGzipFile):
        await websocket.close(code=1008)
        return
    await websocket.send_json(
        {
            "type": "replay",
            "replay": replay,
            "object_count": len(replay.get("objects", [])),
            "max_steps": replay.get("max_steps", 0),
        }
    )
    async for command in websocket.iter_json():
        await websocket.send_json({"type": "control", "command": command})


@app.websocket("/player")
async def player(websocket: WebSocket) -> None:
    state = _runtime()
    try:
        slot = int(websocket.query_params.get("slot", "-1"))
    except ValueError:
        await websocket.close(code=1008)
        return
    token = websocket.query_params.get("token", "")
    if not state.validate_slot(slot, token):
        await websocket.close(code=1008)
        return
    if slot in state.players:
        await websocket.close(code=1008)
        return

    await websocket.accept()
    state.players[slot] = websocket
    await websocket.send_json(state.player_observation(slot))
    if len(state.players) == state.player_slot_count:
        await state.maybe_start()

    try:
        async for message in websocket.iter_json():
            async with state.lock:
                state.actions[slot] = decode_action(message)
    except WebSocketDisconnect:
        pass
    finally:
        if state.players.get(slot) is websocket:
            del state.players[slot]


async def _start_after_player_connect_timeout() -> None:
    state = _runtime()
    await asyncio.sleep(state.config.player_connect_timeout_seconds)
    await state.maybe_start()


def main() -> None:
    global server
    server = uvicorn.Server(uvicorn.Config(app, host="0.0.0.0", port=8080))
    server.run()


if __name__ == "__main__":
    main()
