"""Coworld / BitWorld player bridge for guided_bot.

The public Among Them flow launches uploaded Docker policy images as external
player containers. Depending on the runner, this process either speaks the raw
BitWorld `/player` binary protocol or the generic JSON ``coworld.player.v1``
policy protocol.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
from dataclasses import dataclass
import json
import logging
import os
import sys
import time
from typing import Any, Literal
from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit

import numpy as np
import websockets
from websockets.exceptions import ConnectionClosed
from pydantic import BaseModel, ConfigDict, Field

from mettagrid.bitworld import (
    BITWORLD_ACTION_MASKS,
    BITWORLD_DEFAULT_FRAME_STACK,
    PACKED_FRAME_BYTES,
    SCREEN_HEIGHT,
    SCREEN_WIDTH,
    pack_chat_packet,
    pack_input_packet,
)
from mettagrid.policy.policy_env_interface import PolicyEnvInterface

try:
    from amongthem_policy import AmongThemPolicy, BITWORLD_ACTION_NAMES
except ModuleNotFoundError as exc:
    if exc.name != "amongthem_policy":
        raise
    from guided_bot.coworld.amongthem_policy import (
        AmongThemPolicy,
        BITWORLD_ACTION_NAMES,
    )

LOGGER = logging.getLogger("guided_bot.coworld")
DEFAULT_BITSCREEN_ADDRESS = "host.docker.internal"
DEFAULT_BITSCREEN_PORT = 8080
BITSCREEN_PLAYER_PATH = "/player"
WEBSOCKET_CONNECT_OPTIONS = {
    "max_size": None,
    # The BitWorld server streams frames continuously but does not reliably
    # answer websocket-level keepalive pings. The default websockets client
    # ping closes otherwise healthy connections after ~40s.
    "ping_interval": None,
}


class PolicyPlayerConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    type: Literal["player_config"]
    protocol: Literal["coworld.player.v1"]
    slot: int
    connection_id: str
    action_names: list[str]
    policy_env: PolicyEnvInterface


class PolicyPlayerObservation(BaseModel):
    model_config = ConfigDict(extra="ignore")

    type: Literal["observation"]
    protocol: Literal["coworld.player.v1"]
    slot: int
    step: int
    observation: Any = Field(...)


class GuidedBotCoworldPlayer:
    def __init__(self) -> None:
        self.config: PolicyPlayerConfig | None = None
        self.policy: AmongThemPolicy | None = None

    def configure(self, raw_message: dict[str, Any]) -> None:
        config = PolicyPlayerConfig.model_validate(raw_message)
        if tuple(config.action_names) != BITWORLD_ACTION_NAMES:
            raise ValueError(
                "guided_bot requires the 27-action BitWorld action space; "
                f"received {len(config.action_names)} actions."
            )

        policy_env = config.policy_env.model_copy(
            update={"num_agents": max(config.policy_env.num_agents, config.slot + 1)}
        )
        self.config = config
        self.policy = AmongThemPolicy(policy_env)
        LOGGER.info(
            "configured guided_bot Coworld player slot=%s num_agents=%s shape=%s kind=%s",
            config.slot,
            policy_env.num_agents,
            policy_env.observation_shape,
            policy_env.observation_kind,
        )

    def action_for_observation(self, raw_message: dict[str, Any]) -> dict[str, Any]:
        if self.config is None or self.policy is None:
            raise RuntimeError("received observation before player_config")

        observation_message = PolicyPlayerObservation.model_validate(raw_message)
        if observation_message.slot != self.config.slot:
            raise ValueError(
                f"received observation for slot {observation_message.slot}, "
                f"configured for slot {self.config.slot}"
            )

        observation = decode_pixel_observation(
            observation_message.observation,
            self.policy.policy_env_info,
        )
        actions = self.policy.step_agent_observations(
            [self.config.slot],
            observation[np.newaxis, ...],
        )
        action_index = int(actions[0])
        if action_index < 0 or action_index >= len(self.config.action_names):
            LOGGER.warning(
                "policy returned invalid action index %s; using noop", action_index
            )
            action_index = 0

        infos: dict[str, Any] = {"slot": self.config.slot}
        chat = self.policy.take_chat(self.config.slot)
        if chat:
            infos["chat"] = chat

        response: dict[str, Any] = {
            "type": "action",
            "action_index": action_index,
            "action_name": self.config.action_names[action_index],
            "policy_infos": infos,
            "request_id": f"step-{observation_message.step}",
        }
        chat_field = os.environ.get("GUIDED_BOT_COWORLD_CHAT_FIELD")
        if chat and chat_field:
            response[chat_field] = chat
        return response

    def close(self) -> None:
        if self.policy is not None:
            self.policy.close()
            self.policy = None


def decode_pixel_observation(
    raw_observation: Any,
    policy_env: PolicyEnvInterface,
) -> np.ndarray:
    """Decode Coworld JSON observation payloads into one pixel tensor."""
    shape = tuple(int(dim) for dim in policy_env.observation_shape)
    dtype = np.dtype(policy_env.observation_dtype or "uint8")

    if isinstance(raw_observation, dict):
        shape = tuple(int(dim) for dim in raw_observation.get("shape", shape))
        dtype = np.dtype(raw_observation.get("dtype", dtype.name))
        raw_observation = raw_observation.get("data", raw_observation)

    if isinstance(raw_observation, str):
        array = np.frombuffer(_decode_base64(raw_observation), dtype=dtype)
    elif isinstance(raw_observation, (bytes, bytearray, memoryview)):
        array = np.frombuffer(raw_observation, dtype=dtype)
    else:
        array = np.asarray(raw_observation, dtype=dtype)

    if array.shape == (1, *shape):
        array = array[0]
    if array.shape == shape:
        return np.ascontiguousarray(array, dtype=np.uint8)

    expected = int(np.prod(shape))
    if array.size == expected:
        return np.ascontiguousarray(array.reshape(shape), dtype=np.uint8)

    raise ValueError(
        f"expected observation shape {shape} ({expected} values), "
        f"received shape {array.shape} ({array.size} values)"
    )


def _decode_base64(value: str) -> bytes:
    if "," in value and value.split(",", 1)[0].startswith("data:"):
        value = value.split(",", 1)[1]
    if value.startswith("base64:"):
        value = value.removeprefix("base64:")
    return base64.b64decode(value, validate=False)


def build_policy_env(slot: int = 0) -> PolicyEnvInterface:
    """Build the pixel-only BitWorld policy contract used by Among Them."""
    return PolicyEnvInterface(
        action_names=list(BITWORLD_ACTION_NAMES),
        num_agents=max(1, slot + 1),
        observation_shape=(
            BITWORLD_DEFAULT_FRAME_STACK,
            SCREEN_HEIGHT,
            SCREEN_WIDTH,
        ),
        egocentric_shape=(SCREEN_HEIGHT, SCREEN_WIDTH),
        observation_kind="pixels",
        observation_dtype="uint8",
        observation_low=0,
        observation_high=15,
    )


def unpack_bitscreen_frame(frame_data: bytes) -> np.ndarray:
    """Unpack one 4-bit BitWorld frame into a 128x128 uint8 pixel array."""
    if len(frame_data) != PACKED_FRAME_BYTES:
        raise ValueError(
            f"expected {PACKED_FRAME_BYTES} packed frame bytes, got {len(frame_data)}"
        )
    packed = np.frombuffer(frame_data, dtype=np.uint8)
    pixels = np.empty((PACKED_FRAME_BYTES * 2,), dtype=np.uint8)
    pixels[0::2] = packed & 0x0F
    pixels[1::2] = packed >> 4
    return pixels.reshape((SCREEN_HEIGHT, SCREEN_WIDTH))


def stack_bitscreen_observation(
    current_stack: np.ndarray | None,
    frame_data: bytes,
) -> np.ndarray:
    frame = unpack_bitscreen_frame(frame_data)
    if current_stack is None:
        return np.repeat(
            frame[np.newaxis, :, :],
            BITWORLD_DEFAULT_FRAME_STACK,
            axis=0,
        )
    current_stack[:-1] = current_stack[1:]
    current_stack[-1] = frame
    return current_stack


def _ensure_ws_path(url: str, default_path: str = BITSCREEN_PLAYER_PATH) -> str:
    """Insert the player websocket path when an endpoint has only host/port."""
    parts = urlsplit(url)
    if parts.path and parts.path != "/":
        return url
    return urlunsplit(
        (parts.scheme, parts.netloc, default_path, parts.query, parts.fragment)
    )


def _add_query_params(url: str, params: dict[str, str]) -> str:
    parts = urlsplit(url)
    query = parse_qs(parts.query, keep_blank_values=True)
    for key, value in params.items():
        if value and key not in query:
            query[key] = [value]
    return urlunsplit(
        (
            parts.scheme,
            parts.netloc,
            parts.path,
            urlencode(query, doseq=True),
            parts.fragment,
        )
    )


def bitscreen_connect_url(
    *,
    address: str,
    port: int,
    name: str,
    token: str,
    slot: int,
    url: str,
) -> str:
    """Build the raw BitWorld player websocket URL expected by BitWorld bots."""
    endpoint = (
        _ensure_ws_path(url) if url else f"ws://{address}:{port}{BITSCREEN_PLAYER_PATH}"
    )
    params: dict[str, str] = {}
    if name:
        params["name"] = name
    if slot >= 0:
        params["slot"] = str(slot)
    if token:
        params["token"] = token
    return _add_query_params(endpoint, params)


def slot_from_url(url: str, fallback: int = 0) -> int:
    query = parse_qs(urlsplit(url).query, keep_blank_values=True)
    values = query.get("slot")
    if not values:
        return fallback
    try:
        return int(values[0])
    except (TypeError, ValueError):
        return fallback


class BitscreenGuidedBotPlayer:
    """Raw BitWorld player protocol bridge used by the Among Them runner."""

    def __init__(self, slot: int) -> None:
        self.slot = max(0, slot)
        self.policy = AmongThemPolicy(build_policy_env(self.slot))
        self.observation_stack: np.ndarray | None = None

    def action_for_frame(self, frame_data: bytes) -> tuple[int, str]:
        self.observation_stack = stack_bitscreen_observation(
            self.observation_stack,
            frame_data,
        )
        actions = self.policy.step_agent_observations(
            [self.slot],
            self.observation_stack[np.newaxis, ...],
        )
        action_index = int(actions[0])
        if action_index < 0 or action_index >= len(BITWORLD_ACTION_MASKS):
            LOGGER.warning(
                "policy returned invalid action index %s; using noop", action_index
            )
            action_index = 0
        chat = self.policy.take_chat(self.slot)
        return action_index, chat

    def close(self) -> None:
        self.policy.close()


@dataclass
class WebsocketDiagnostics:
    protocol: str
    slot: int | None = None
    connected_at: float = 0.0
    messages_received: int = 0
    non_binary_messages: int = 0
    bad_frame_sizes: int = 0
    json_messages: int = 0
    observations: int = 0
    actions_sent: int = 0
    chats_sent: int = 0
    last_message_bytes: int = 0
    last_message_type: str = ""
    last_action_index: int | None = None
    last_action_name: str = ""
    last_action_mask: int | None = None
    last_chat_chars: int = 0
    last_recv_at: float = 0.0
    last_send_at: float = 0.0

    def __post_init__(self) -> None:
        if self.connected_at == 0.0:
            self.connected_at = time.monotonic()

    def mark_bitscreen_message(self, message: Any) -> bytes | None:
        self.messages_received += 1
        self.last_recv_at = time.monotonic()
        self.last_message_type = type(message).__name__
        if not isinstance(message, (bytes, bytearray, memoryview)):
            self.non_binary_messages += 1
            return None

        frame_data = bytes(message)
        self.last_message_bytes = len(frame_data)
        if len(frame_data) != PACKED_FRAME_BYTES:
            self.bad_frame_sizes += 1
            return None

        return frame_data

    def mark_bitscreen_action(self, action_index: int, chat: str) -> int:
        self.actions_sent += 1
        self.last_send_at = time.monotonic()
        self.last_action_index = action_index
        self.last_action_name = BITWORLD_ACTION_NAMES[action_index]
        action_mask = int(BITWORLD_ACTION_MASKS[action_index])
        self.last_action_mask = action_mask
        if chat:
            self.chats_sent += 1
            self.last_chat_chars = len(chat)
        return action_mask

    def mark_json_message(self, message_type: str) -> None:
        self.messages_received += 1
        self.json_messages += 1
        self.last_recv_at = time.monotonic()
        self.last_message_type = message_type
        if message_type == "observation":
            self.observations += 1

    def mark_json_action(self, action_index: int, action_name: str) -> None:
        self.actions_sent += 1
        self.last_send_at = time.monotonic()
        self.last_action_index = action_index
        self.last_action_name = action_name

    def summary(self) -> str:
        now = time.monotonic()
        since_recv = _elapsed_seconds(self.last_recv_at, now)
        since_send = _elapsed_seconds(self.last_send_at, now)
        return (
            f"protocol={self.protocol} slot={self.slot} "
            f"uptime_s={now - self.connected_at:.3f} "
            f"messages={self.messages_received} actions={self.actions_sent} "
            f"observations={self.observations} json_messages={self.json_messages} "
            f"non_binary={self.non_binary_messages} bad_frame_sizes={self.bad_frame_sizes} "
            f"last_message_type={self.last_message_type!r} "
            f"last_message_bytes={self.last_message_bytes} "
            f"last_action_index={self.last_action_index} "
            f"last_action_name={self.last_action_name!r} "
            f"last_action_mask={self.last_action_mask} chats={self.chats_sent} "
            f"last_chat_chars={self.last_chat_chars} "
            f"seconds_since_recv={since_recv} seconds_since_send={since_send}"
        )


def _elapsed_seconds(start: float, now: float) -> str:
    if start == 0.0:
        return "never"
    return f"{now - start:.3f}"


def _connection_closed_details(exc: ConnectionClosed) -> str:
    parts = [f"class={type(exc).__name__}"]
    code = getattr(exc, "code", None)
    reason = getattr(exc, "reason", None)
    if code is not None:
        parts.append(f"code={code}")
    if reason:
        parts.append(f"reason={reason!r}")

    for attr in ("rcvd", "sent"):
        frame = getattr(exc, attr, None)
        if frame is None:
            continue
        frame_code = getattr(frame, "code", None)
        frame_reason = getattr(frame, "reason", "")
        if frame_code is not None:
            parts.append(f"{attr}_code={frame_code}")
        if frame_reason:
            parts.append(f"{attr}_reason={frame_reason!r}")

    order = getattr(exc, "rcvd_then_sent", None)
    if order is not None:
        parts.append(f"rcvd_then_sent={order}")
    return " ".join(parts)


async def run_bitscreen_player(
    engine_ws_url: str,
    *,
    slot: int,
    first_message: Any | None = None,
) -> None:
    LOGGER.info("connecting guided_bot to BitWorld player endpoint %s", engine_ws_url)
    player = BitscreenGuidedBotPlayer(slot=slot)
    diagnostics = WebsocketDiagnostics(protocol="bitscreen", slot=slot)
    try:
        async with websockets.connect(
            engine_ws_url, **WEBSOCKET_CONNECT_OPTIONS
        ) as websocket:
            if first_message is not None:
                await _handle_bitscreen_message(
                    websocket,
                    player,
                    first_message,
                    diagnostics,
                )
            try:
                async for message in websocket:
                    await _handle_bitscreen_message(
                        websocket,
                        player,
                        message,
                        diagnostics,
                    )
            except ConnectionClosed as exc:
                LOGGER.info(
                    "BitWorld player websocket closed: %s; %s",
                    _connection_closed_details(exc),
                    diagnostics.summary(),
                )
    finally:
        LOGGER.info("BitWorld player socket summary: %s", diagnostics.summary())
        player.close()


async def _handle_bitscreen_message(
    websocket: websockets.ClientConnection,
    player: BitscreenGuidedBotPlayer,
    message: Any,
    diagnostics: WebsocketDiagnostics,
) -> None:
    frame_data = diagnostics.mark_bitscreen_message(message)
    if frame_data is None:
        if diagnostics.non_binary_messages or diagnostics.bad_frame_sizes:
            LOGGER.warning(
                "ignoring unexpected BitWorld player message: %s",
                diagnostics.summary(),
            )
        return
    action_index, chat = player.action_for_frame(frame_data)
    action_mask = diagnostics.mark_bitscreen_action(action_index, chat)
    await websocket.send(pack_input_packet(action_mask))
    if chat:
        try:
            await websocket.send(pack_chat_packet(chat))
        except ValueError:
            LOGGER.warning("dropping non-compliant chat packet: %r", chat)


async def run_auto_player(engine_ws_url: str, *, slot: int) -> None:
    """Detect whether the endpoint is raw BitWorld or JSON Coworld."""
    LOGGER.info("connecting guided_bot policy image to %s", engine_ws_url)
    async with websockets.connect(
        engine_ws_url, **WEBSOCKET_CONNECT_OPTIONS
    ) as websocket:
        first_message = await websocket.recv()
        if isinstance(first_message, str):
            try:
                message = json.loads(first_message)
            except json.JSONDecodeError:
                message = {}
            if message.get("type") == "player_config":
                await run_policy_player_socket(websocket, first_message=message)
                return
        await run_bitscreen_player_socket(
            websocket, slot=slot, first_message=first_message
        )


async def run_bitscreen_player_socket(
    websocket: websockets.ClientConnection,
    *,
    slot: int,
    first_message: Any | None = None,
) -> None:
    player = BitscreenGuidedBotPlayer(slot=slot)
    diagnostics = WebsocketDiagnostics(protocol="bitscreen", slot=slot)
    try:
        if first_message is not None:
            await _handle_bitscreen_message(
                websocket,
                player,
                first_message,
                diagnostics,
            )
        try:
            async for message in websocket:
                await _handle_bitscreen_message(
                    websocket,
                    player,
                    message,
                    diagnostics,
                )
        except ConnectionClosed as exc:
            LOGGER.info(
                "BitWorld player websocket closed: %s; %s",
                _connection_closed_details(exc),
                diagnostics.summary(),
            )
    finally:
        LOGGER.info("BitWorld player socket summary: %s", diagnostics.summary())
        player.close()


async def run_policy_player_socket(
    websocket: websockets.ClientConnection,
    *,
    first_message: dict[str, Any] | None = None,
) -> None:
    player = GuidedBotCoworldPlayer()
    diagnostics = WebsocketDiagnostics(protocol="coworld-json")
    try:
        if first_message is not None:
            player.configure(first_message)
            diagnostics.slot = player.config.slot if player.config else None
        try:
            async for raw_message in websocket:
                message = json.loads(raw_message)
                message_type = message.get("type")
                diagnostics.mark_json_message(str(message_type))
                if message_type == "player_config":
                    player.configure(message)
                    diagnostics.slot = player.config.slot if player.config else None
                elif message_type == "observation":
                    action = player.action_for_observation(message)
                    diagnostics.mark_json_action(
                        int(action["action_index"]),
                        str(action["action_name"]),
                    )
                    await websocket.send(json.dumps(action))
                elif message_type == "final":
                    return
                else:
                    LOGGER.debug("ignoring Coworld message type %r", message_type)
        except ConnectionClosed as exc:
            LOGGER.info(
                "Coworld player websocket closed: %s; %s",
                _connection_closed_details(exc),
                diagnostics.summary(),
            )
    finally:
        LOGGER.info("Coworld player socket summary: %s", diagnostics.summary())
        player.close()


async def run_policy_player(engine_ws_url: str) -> None:
    async with websockets.connect(
        engine_ws_url, **WEBSOCKET_CONNECT_OPTIONS
    ) as websocket:
        await run_policy_player_socket(websocket)


def normalize_colon_args(argv: list[str]) -> list[str]:
    """Accept Nim-style `--key:value` flags from BitWorld tournament_server."""
    normalized: list[str] = []
    for arg in argv:
        if arg.startswith("--") and ":" in arg and "=" not in arg:
            key, value = arg.split(":", 1)
            normalized.append(f"{key}={value}")
        else:
            normalized.append(arg)
    return normalized


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="guided_bot BitWorld/Coworld player")
    parser.add_argument("--address", default=DEFAULT_BITSCREEN_ADDRESS)
    parser.add_argument("--port", type=int, default=DEFAULT_BITSCREEN_PORT)
    parser.add_argument("--name", default="")
    parser.add_argument("--token", default="")
    parser.add_argument("--slot", type=int, default=-1)
    parser.add_argument("--url", default="")
    parser.add_argument(
        "--protocol",
        choices=("auto", "bitscreen", "coworld-json"),
        default=os.environ.get("GUIDED_BOT_PLAYER_PROTOCOL", "auto"),
    )
    return parser.parse_args(normalize_colon_args(argv))


def main() -> None:
    logging.basicConfig(
        level=os.environ.get("GUIDED_BOT_COWORLD_LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    args = parse_args(sys.argv[1:])
    env_url = os.environ.get("COGAMES_ENGINE_WS_URL", "")
    url = args.url or env_url
    if not url:
        url = bitscreen_connect_url(
            address=args.address,
            port=args.port,
            name=args.name,
            token=args.token,
            slot=args.slot,
            url="",
        )

    if args.protocol == "coworld-json":
        asyncio.run(run_policy_player(url))
        return

    if args.protocol == "bitscreen":
        bitscreen_url = bitscreen_connect_url(
            address=args.address,
            port=args.port,
            name=args.name,
            token=args.token,
            slot=args.slot,
            url=url,
        )
        asyncio.run(
            run_bitscreen_player(
                bitscreen_url,
                slot=slot_from_url(bitscreen_url, max(args.slot, 0)),
            )
        )
        return

    auto_url = bitscreen_connect_url(
        address=args.address,
        port=args.port,
        name=args.name,
        token=args.token,
        slot=args.slot,
        url=url,
    )
    asyncio.run(
        run_auto_player(auto_url, slot=slot_from_url(auto_url, max(args.slot, 0)))
    )


if __name__ == "__main__":
    main()
