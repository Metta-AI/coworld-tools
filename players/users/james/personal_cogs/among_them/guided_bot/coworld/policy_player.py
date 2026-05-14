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
import json
import logging
import os
import sys
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
    from guided_bot.cogames.amongthem_policy import (
        AmongThemPolicy,
        BITWORLD_ACTION_NAMES,
    )

LOGGER = logging.getLogger("guided_bot.coworld")
DEFAULT_BITSCREEN_ADDRESS = "host.docker.internal"
DEFAULT_BITSCREEN_PORT = 8080
BITSCREEN_PLAYER_PATH = "/player"


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
            LOGGER.warning("policy returned invalid action index %s; using noop", action_index)
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
    return urlunsplit((parts.scheme, parts.netloc, default_path, parts.query, parts.fragment))


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
    endpoint = _ensure_ws_path(url) if url else f"ws://{address}:{port}{BITSCREEN_PLAYER_PATH}"
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
            LOGGER.warning("policy returned invalid action index %s; using noop", action_index)
            action_index = 0
        chat = self.policy.take_chat(self.slot)
        return action_index, chat

    def close(self) -> None:
        self.policy.close()


async def run_bitscreen_player(
    engine_ws_url: str,
    *,
    slot: int,
    first_message: Any | None = None,
) -> None:
    LOGGER.info("connecting guided_bot to BitWorld player endpoint %s", engine_ws_url)
    player = BitscreenGuidedBotPlayer(slot=slot)
    try:
        async with websockets.connect(engine_ws_url, max_size=None) as websocket:
            if first_message is not None:
                await _handle_bitscreen_message(websocket, player, first_message)
            try:
                async for message in websocket:
                    await _handle_bitscreen_message(websocket, player, message)
            except ConnectionClosed:
                LOGGER.info("BitWorld player websocket closed")
    finally:
        player.close()


async def _handle_bitscreen_message(
    websocket: websockets.ClientConnection,
    player: BitscreenGuidedBotPlayer,
    message: Any,
) -> None:
    if not isinstance(message, (bytes, bytearray, memoryview)):
        return
    frame_data = bytes(message)
    if len(frame_data) != PACKED_FRAME_BYTES:
        return
    action_index, chat = player.action_for_frame(frame_data)
    await websocket.send(pack_input_packet(int(BITWORLD_ACTION_MASKS[action_index])))
    if chat:
        try:
            await websocket.send(pack_chat_packet(chat))
        except ValueError:
            LOGGER.warning("dropping non-compliant chat packet: %r", chat)


async def run_auto_player(engine_ws_url: str, *, slot: int) -> None:
    """Detect whether the endpoint is raw BitWorld or JSON Coworld."""
    LOGGER.info("connecting guided_bot policy image to %s", engine_ws_url)
    async with websockets.connect(engine_ws_url, max_size=None) as websocket:
        first_message = await websocket.recv()
        if isinstance(first_message, str):
            try:
                message = json.loads(first_message)
            except json.JSONDecodeError:
                message = {}
            if message.get("type") == "player_config":
                await run_policy_player_socket(websocket, first_message=message)
                return
        await run_bitscreen_player_socket(websocket, slot=slot, first_message=first_message)


async def run_bitscreen_player_socket(
    websocket: websockets.ClientConnection,
    *,
    slot: int,
    first_message: Any | None = None,
) -> None:
    player = BitscreenGuidedBotPlayer(slot=slot)
    try:
        if first_message is not None:
            await _handle_bitscreen_message(websocket, player, first_message)
        try:
            async for message in websocket:
                await _handle_bitscreen_message(websocket, player, message)
        except ConnectionClosed:
            LOGGER.info("BitWorld player websocket closed")
    finally:
        player.close()


async def run_policy_player_socket(
    websocket: websockets.ClientConnection,
    *,
    first_message: dict[str, Any] | None = None,
) -> None:
    player = GuidedBotCoworldPlayer()
    try:
        if first_message is not None:
            player.configure(first_message)
        try:
            async for raw_message in websocket:
                message = json.loads(raw_message)
                message_type = message.get("type")
                if message_type == "player_config":
                    player.configure(message)
                elif message_type == "observation":
                    await websocket.send(json.dumps(player.action_for_observation(message)))
                elif message_type == "final":
                    return
                else:
                    LOGGER.debug("ignoring Coworld message type %r", message_type)
        except ConnectionClosed:
            LOGGER.info("Coworld player websocket closed")
    finally:
        player.close()


async def run_policy_player(engine_ws_url: str) -> None:
    async with websockets.connect(engine_ws_url, max_size=None) as websocket:
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
    asyncio.run(run_auto_player(auto_url, slot=slot_from_url(auto_url, max(args.slot, 0))))


if __name__ == "__main__":
    main()
