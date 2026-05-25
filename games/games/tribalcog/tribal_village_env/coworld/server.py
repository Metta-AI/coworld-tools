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

from tribal_village_env.build import get_runtime_project_root
from tribal_village_env.environment import ACTION_SPACE_SIZE, TribalVillageEnv

CLIENTS_DIR = Path(__file__).parent / "clients"
PROJECT_ROOT = get_runtime_project_root()
ASSETS_DIR = PROJECT_ROOT / "data"
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
ASSET_MEDIA_TYPES = {
    ".png": "image/png",
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
GLOBAL_TERRAIN_LABELS = [
    "empty",
    "water",
    "shallow_water",
    "bridge",
    "fertile",
    "road",
    "grass",
    "dune",
    "sand",
    "snow",
    "mud",
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
GLOBAL_THING_LABELS = [
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
    "temple",
    "university",
    "castle",
    "wonder",
    "control_point",
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
THING_RENDER_ORDER = [
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
    "tree",
    "wheat",
    "fish",
    "relic",
    "stone",
    "gold",
    "bush",
    "cactus",
    "stalagmite",
    "stump",
    "stubble",
    "corpse",
    "skeleton",
    "cow",
    "bear",
    "wolf",
    "wall",
    "door",
    "altar",
    "spawner",
    "tumor",
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
    "temple",
    "university",
    "castle",
    "wonder",
    "control_point",
    "goblin_hive",
    "goblin_hut",
    "goblin_totem",
    "magma",
    "agent",
]
THING_RENDER_RANK = {label: idx for idx, label in enumerate(THING_RENDER_ORDER)}
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
GLOBAL_CELL_TERRAIN = 0
GLOBAL_CELL_BACKGROUND_KIND = 1
GLOBAL_CELL_BACKGROUND_TEAM = 2
GLOBAL_CELL_BACKGROUND_ORIENTATION = 3
GLOBAL_CELL_BACKGROUND_UNIT_CLASS = 4
GLOBAL_CELL_BACKGROUND_AGENT_ID = 5
GLOBAL_CELL_THING_KIND = 6
GLOBAL_CELL_THING_TEAM = 7
GLOBAL_CELL_THING_ORIENTATION = 8
GLOBAL_CELL_THING_UNIT_CLASS = 9
GLOBAL_CELL_THING_AGENT_ID = 10
GLOBAL_CELL_TINT = 11
GLOBAL_CELL_ELEVATION = 12
GLOBAL_CELL_FIELD_COUNT = 13
SPRITE_PLAYER_INPUT_MESSAGE = 0x84
BUTTON_UP = 0x01
BUTTON_DOWN = 0x02
BUTTON_LEFT = 0x04
BUTTON_RIGHT = 0x08
BUTTON_SELECT = 0x10
BUTTON_A = 0x20
BUTTON_B = 0x40

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
    "temple": "t",
    "control_point": "p",
}
TERRAIN_COLORS = {
    "water": "#3276a8",
    "shallow_water": "#4f9ab9",
    "bridge": "#8f7a52",
    "fertile": "#6a8f3f",
    "road": "#7a715d",
    "grass": "#4f8146",
    "dune": "#b69b55",
    "sand": "#c8ad74",
    "snow": "#d8e7e8",
    "mud": "#685947",
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
ORIENTATION_ASSET_SUFFIXES = {
    "north": "n",
    "south": "s",
    "west": "w",
    "east": "e",
    "north_west": "nw",
    "north_east": "ne",
    "south_west": "sw",
    "south_east": "se",
}
TERRAIN_ASSET_KEYS = {
    "empty": "floor",
    "water": "water",
    "shallow_water": "water",
    "bridge": "bridge",
    "fertile": "fertile",
    "road": "road",
    "grass": "grass",
    "dune": "dune",
    "sand": "sand",
    "snow": "snow",
    "mud": "mud",
    "mountain": "dune",
    "ramp_up_n": "oriented/ramp_up_n",
    "ramp_up_s": "oriented/ramp_up_s",
    "ramp_up_w": "oriented/ramp_up_w",
    "ramp_up_e": "oriented/ramp_up_e",
    "ramp_down_n": "oriented/ramp_down_n",
    "ramp_down_s": "oriented/ramp_down_s",
    "ramp_down_w": "oriented/ramp_down_w",
    "ramp_down_e": "oriented/ramp_down_e",
}
THING_ASSET_KEYS = {
    "wall": "oriented/wall",
    "relic": "goblet",
    "cliff_edge_n": "cliff_edge_ew_s",
    "cliff_edge_e": "cliff_edge_ns_w",
    "cliff_edge_s": "cliff_edge_ew",
    "cliff_edge_w": "cliff_edge_ns",
    "cliff_corner_in_ne": "oriented/cliff_corner_in_ne",
    "cliff_corner_in_se": "oriented/cliff_corner_in_se",
    "cliff_corner_in_sw": "oriented/cliff_corner_in_sw",
    "cliff_corner_in_nw": "oriented/cliff_corner_in_nw",
    "cliff_corner_out_ne": "oriented/cliff_corner_out_ne",
    "cliff_corner_out_se": "oriented/cliff_corner_out_se",
    "cliff_corner_out_sw": "oriented/cliff_corner_out_sw",
    "cliff_corner_out_nw": "oriented/cliff_corner_out_nw",
}
ORIENTED_THING_ASSET_BASES = {
    "cow": "oriented/cow",
    "bear": "oriented/bear",
    "wolf": "oriented/wolf",
    "tumor": "oriented/tumor",
}
UNIT_ASSET_BASES = {
    "villager": "oriented/gatherer",
    "trebuchet": "oriented/trebuchet_packed",
}
UNIT_ASSET_FALLBACK_BASES = {
    "long_swordsman": "oriented/man_at_arms",
    "champion": "oriented/man_at_arms",
    "light_cavalry": "oriented/scout",
    "hussar": "oriented/scout",
    "crossbowman": "oriented/archer",
    "arbalester": "oriented/archer",
    "galley": "oriented/boat",
    "fire_ship": "oriented/boat",
    "fishing_ship": "oriented/boat",
    "transport_ship": "oriented/boat",
    "demo_ship": "oriented/boat",
    "cannon_galleon": "oriented/boat",
    "scorpion": "oriented/mangonel",
    "cavalier": "oriented/knight",
    "paladin": "oriented/knight",
    "camel": "oriented/scout",
    "heavy_camel": "oriented/scout",
    "imperial_camel": "oriented/scout",
    "skirmisher": "oriented/archer",
    "elite_skirmisher": "oriented/archer",
    "cavalry_archer": "oriented/archer",
    "heavy_cavalry_archer": "oriented/archer",
    "hand_cannoneer": "oriented/janissary",
}


def wasm_media_type(path: Path) -> str:
    return WASM_MEDIA_TYPES.get(path.suffix, "application/octet-stream")


def asset_media_type(path: Path) -> str:
    return ASSET_MEDIA_TYPES.get(path.suffix, "application/octet-stream")


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


def resolve_sprite_asset_path(root: Path, asset_path: str) -> Path:
    if Path(asset_path).suffix.lower() not in ASSET_MEDIA_TYPES:
        raise FileNotFoundError(asset_path)

    resolved_root = root.resolve()
    candidate = (resolved_root / asset_path).resolve()
    try:
        candidate.relative_to(resolved_root)
    except ValueError as exc:
        raise ValueError(f"Invalid sprite asset path: {asset_path}") from exc
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


def _direction_argument(dx: int, dy: int) -> int | None:
    return {
        (0, -1): 0,
        (0, 1): 1,
        (-1, 0): 2,
        (1, 0): 3,
        (-1, -1): 4,
        (1, -1): 5,
        (-1, 1): 6,
        (1, 1): 7,
    }.get((dx, dy))


def decode_player_buttons(buttons: int) -> int:
    buttons = int(buttons) & 0x7F
    dx = int(bool(buttons & BUTTON_RIGHT)) - int(bool(buttons & BUTTON_LEFT))
    dy = int(bool(buttons & BUTTON_DOWN)) - int(bool(buttons & BUTTON_UP))
    direction = _direction_argument(dx, dy)
    if direction is None:
        return 0
    if buttons & BUTTON_A:
        verb = 2
    elif buttons & BUTTON_B:
        verb = 3
    elif buttons & BUTTON_SELECT:
        verb = 9
    else:
        verb = 1
    return verb * 28 + direction


def decode_binary_action(message: bytes) -> int:
    if len(message) >= 2 and message[0] == SPRITE_PLAYER_INPUT_MESSAGE:
        return decode_player_buttons(message[1])
    return 0


def _first_active_layer(obs: np.ndarray, labels: list[str], start: int, x: int, y: int) -> str | None:
    for offset, label in enumerate(labels):
        if int(obs[start + offset, x, y]) > 0:
            return label
    return None


def _active_layers(obs: np.ndarray, labels: list[str], start: int, x: int, y: int) -> list[str]:
    return [
        label
        for offset, label in enumerate(labels)
        if int(obs[start + offset, x, y]) > 0
    ]


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


def _sprite_key_exists(key: str) -> bool:
    return (ASSETS_DIR / f"{key}.png").is_file()


def _asset_url(key: str | None) -> str | None:
    if key is None or not _sprite_key_exists(key):
        return None
    return f"/assets/{key}.png"


def _oriented_asset_key(base_key: str, orientation: str | None) -> str | None:
    suffixes: list[str] = []
    if orientation is not None:
        suffix = ORIENTATION_ASSET_SUFFIXES.get(orientation)
        if suffix is not None:
            suffixes.append(suffix)
    suffixes.append("s")

    for suffix in suffixes:
        key = f"{base_key}.{suffix}"
        if _sprite_key_exists(key):
            return key
    return base_key if _sprite_key_exists(base_key) else None


def _unit_asset_key(unit_class: str | None, orientation: str | None) -> str | None:
    if unit_class is None:
        unit_class = "villager"
    bases = [
        UNIT_ASSET_BASES.get(unit_class, f"oriented/{unit_class}"),
        UNIT_ASSET_FALLBACK_BASES.get(unit_class),
    ]
    for base_key in bases:
        if base_key is None:
            continue
        asset_key = _oriented_asset_key(base_key, orientation)
        if asset_key is not None:
            return asset_key
    return _oriented_asset_key("oriented/gatherer", orientation)


def _thing_asset_key(
    thing: str | None,
    unit_class: str | None,
    orientation: str | None,
) -> str | None:
    if thing is None:
        return None
    if thing == "agent":
        return _unit_asset_key(unit_class, orientation)
    if thing in ORIENTED_THING_ASSET_BASES:
        return _oriented_asset_key(ORIENTED_THING_ASSET_BASES[thing], orientation)
    key = THING_ASSET_KEYS.get(thing, thing)
    return key if _sprite_key_exists(key) else None


def _terrain_asset_key(terrain: str) -> str | None:
    key = TERRAIN_ASSET_KEYS.get(terrain, terrain)
    return key if _sprite_key_exists(key) else None


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
            unit_class = _indexed_label(UNIT_CLASS_LABELS, unit_class_value)
            orientation = _indexed_label(ORIENTATION_LABELS, orientation_value)
            things = sorted(
                _active_layers(obs, THING_LABELS, THING_LAYER_START, x, y),
                key=lambda label: THING_RENDER_RANK.get(label, len(THING_RENDER_RANK)),
            )
            if things:
                thing = things[-1]
            thing_assets = [
                asset
                for asset in (
                    _asset_url(_thing_asset_key(label, unit_class, orientation))
                    for label in things
                )
                if asset is not None
            ]
            terrain_asset = None if obscured else _asset_url(_terrain_asset_key(terrain))
            thing_assets = [] if obscured else thing_assets
            thing_asset = thing_assets[-1] if thing_assets else None
            cell: dict[str, Any] = {
                "x": x,
                "y": y,
                "terrain": terrain,
                "thing": thing,
                "things": [] if obscured else things,
                "sprite": _cell_sprite(terrain, thing, obscured),
                "terrain_asset": terrain_asset,
                "thing_asset": thing_asset,
                "thing_assets": thing_assets,
                "sprite_asset": thing_asset or terrain_asset,
                "glyph": _cell_glyph(terrain, thing, obscured),
                "color": _cell_color(terrain, team_id, obscured),
                "team_id": team_id,
                "unit_class": unit_class,
                "orientation": orientation,
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


def _ordinal_label(labels: list[str], value: int) -> str | None:
    if 0 <= value < len(labels):
        return labels[value]
    return None


def _global_terrain_sprites() -> list[dict[str, Any]]:
    return [
        {
            "id": terrain_id,
            "label": label,
            "asset": _asset_url(_terrain_asset_key(label)),
            "color": TERRAIN_COLORS.get(label, "#4b534c"),
        }
        for terrain_id, label in enumerate(GLOBAL_TERRAIN_LABELS)
    ]


def _global_thing_object(
    layer: str,
    x: int,
    y: int,
    cell: np.ndarray,
    *,
    kind_index: int,
    team_index: int,
    orientation_index: int,
    unit_class_index: int,
    agent_id_index: int,
) -> dict[str, Any] | None:
    kind_value = int(cell[kind_index])
    thing = _ordinal_label(GLOBAL_THING_LABELS, kind_value)
    if thing is None:
        return None

    team_value = int(cell[team_index])
    team_id = team_value if 0 <= team_value < TEAM_COUNT else None
    orientation = _ordinal_label(ORIENTATION_LABELS, int(cell[orientation_index]))
    unit_class = _ordinal_label(UNIT_CLASS_LABELS, int(cell[unit_class_index]))
    agent_id_value = int(cell[agent_id_index])
    agent_id = agent_id_value if agent_id_value >= 0 else None
    asset = _asset_url(_thing_asset_key(thing, unit_class, orientation))
    z = THING_RENDER_RANK.get(thing, len(THING_RENDER_RANK))
    if layer == "foreground":
        z += len(THING_RENDER_RANK)
    return {
        "id": f"{layer}:{x}:{y}",
        "layer": layer,
        "x": x,
        "y": y,
        "z": z,
        "thing": thing,
        "team_id": team_id,
        "agent_id": agent_id,
        "unit_class": unit_class,
        "orientation": orientation,
        "asset": asset,
        "glyph": THING_GLYPHS.get(thing, thing[:1].upper()),
        "color": _cell_color("empty", team_id, False),
    }


def global_sprite_view_from_cells(cells: np.ndarray) -> dict[str, Any]:
    if cells.ndim != 3 or cells.shape[2] < GLOBAL_CELL_FIELD_COUNT:
        raise ValueError("global sprite cells must be an HxWx13 int16 array")

    height = int(cells.shape[0])
    width = int(cells.shape[1])
    terrain = np.clip(cells[:, :, GLOBAL_CELL_TERRAIN], 0, 255).astype(
        np.uint8,
        copy=False,
    )
    objects: list[dict[str, Any]] = []
    for y in range(height):
        for x in range(width):
            cell = cells[y, x]
            background = _global_thing_object(
                "background",
                x,
                y,
                cell,
                kind_index=GLOBAL_CELL_BACKGROUND_KIND,
                team_index=GLOBAL_CELL_BACKGROUND_TEAM,
                orientation_index=GLOBAL_CELL_BACKGROUND_ORIENTATION,
                unit_class_index=GLOBAL_CELL_BACKGROUND_UNIT_CLASS,
                agent_id_index=GLOBAL_CELL_BACKGROUND_AGENT_ID,
            )
            if background is not None:
                objects.append(background)
            foreground = _global_thing_object(
                "foreground",
                x,
                y,
                cell,
                kind_index=GLOBAL_CELL_THING_KIND,
                team_index=GLOBAL_CELL_THING_TEAM,
                orientation_index=GLOBAL_CELL_THING_ORIENTATION,
                unit_class_index=GLOBAL_CELL_THING_UNIT_CLASS,
                agent_id_index=GLOBAL_CELL_THING_AGENT_ID,
            )
            if foreground is not None:
                objects.append(foreground)

    objects.sort(key=lambda obj: (obj["z"], obj["y"], obj["x"], obj["id"]))
    return {
        "protocol": "tribalcog-global-sprite-v1",
        "width": width,
        "height": height,
        "tile_size": 24,
        "terrain": {
            "encoding": "u8-base64",
            "labels": GLOBAL_TERRAIN_LABELS,
            "sprites": _global_terrain_sprites(),
            "data": base64.b64encode(np.ascontiguousarray(terrain).tobytes()).decode(
                "ascii"
            ),
        },
        "objects": objects,
        "object_count": len(objects),
        "legend": {
            "terrain": GLOBAL_TERRAIN_LABELS,
            "thing": GLOBAL_THING_LABELS,
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
        self.global_viewers: dict[WebSocket, bool] = {}
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

    def global_sprite_view(self) -> dict[str, Any] | None:
        cells = self.env.global_sprite_cells()
        if cells is None:
            return None
        return global_sprite_view_from_cells(cells)

    def snapshot(self, *, include_frame: bool = False) -> dict[str, Any]:
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
        global_view = self.global_sprite_view()
        if global_view is not None:
            snapshot["global_view"] = global_view
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
            viewer.send_json(self.snapshot(include_frame=include_frame))
            for viewer, include_frame in list(self.global_viewers.items())
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
                await viewer.send_json(
                    self.snapshot(include_frame=self.global_viewers[viewer])
                )
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


@app.get("/assets/{asset_path:path}")
def sprite_asset(asset_path: str) -> FileResponse:
    try:
        path = resolve_sprite_asset_path(ASSETS_DIR, asset_path)
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=404) from exc
    return FileResponse(path, media_type=asset_media_type(path))


@app.websocket("/global")
async def global_viewer(websocket: WebSocket) -> None:
    state = _runtime()
    await websocket.accept()
    include_frame = websocket.query_params.get("frame") == "1"
    state.global_viewers[websocket] = include_frame
    try:
        await websocket.send_json(state.snapshot(include_frame=include_frame))
        async for _ in websocket.iter_json():
            pass
    finally:
        state.global_viewers.pop(websocket, None)


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
        while True:
            message = await websocket.receive()
            if message["type"] == "websocket.disconnect":
                break
            action = 0
            if message.get("text") is not None:
                try:
                    payload = json.loads(message["text"])
                except json.JSONDecodeError:
                    payload = {}
                action = decode_action(payload) if isinstance(payload, dict) else 0
            elif message.get("bytes") is not None:
                action = decode_binary_action(message["bytes"])
            async with state.lock:
                state.actions[slot] = action
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
