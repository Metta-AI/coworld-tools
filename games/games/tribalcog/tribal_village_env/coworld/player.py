from __future__ import annotations

import asyncio
import json
import os
import random
from typing import Any

import websockets

CONNECT_RETRY_INTERVAL_SECONDS = 0.25
CONNECT_TIMEOUT_SECONDS = 8.0
TRANSIENT_CONNECT_ERRORS = (
    OSError,
    asyncio.TimeoutError,
    websockets.InvalidHandshake,
    websockets.InvalidMessage,
)


def player_ws_url() -> str:
    return os.environ["COWORLD_PLAYER_WS_URL"]


async def connect_with_retry(url: str):
    timeout = float(
        os.environ.get("TRIBALCOG_PLAYER_CONNECT_TIMEOUT_SECONDS", CONNECT_TIMEOUT_SECONDS)
    )
    deadline = asyncio.get_running_loop().time() + timeout
    while True:
        try:
            return await websockets.connect(url, max_size=None)
        except TRANSIENT_CONNECT_ERRORS:
            if asyncio.get_running_loop().time() >= deadline:
                return None
            await asyncio.sleep(CONNECT_RETRY_INTERVAL_SECONDS)


async def main() -> None:
    url = player_ws_url()
    rng = random.Random(int(os.environ.get("TRIBALCOG_PLAYER_SEED", "0")))
    mode = os.environ.get("TRIBALCOG_PLAYER_MODE", "overseer")
    websocket = await connect_with_retry(url)
    if websocket is None:
        return
    try:
        async for raw_message in websocket:
            message = json.loads(raw_message)
            if message["type"] == "final":
                return
            if message["type"] == "observation":
                command = choose_overseer_command(message, mode, rng)
                if command is not None:
                    await websocket.send(json.dumps(command))
    except websockets.ConnectionClosed:
        return
    finally:
        await websocket.close()


def choose_overseer_command(
    message: dict[str, Any],
    mode: str,
    rng: random.Random,
) -> dict[str, Any] | None:
    if mode == "noop":
        return None
    buildings = [
        building
        for building in message.get("visible_buildings", [])
        if isinstance(building, dict)
    ]
    if not buildings:
        return None
    military = {
        "barracks",
        "archery_range",
        "stable",
        "siege_workshop",
        "mangonel_workshop",
        "trebuchet_workshop",
        "monastery",
        "castle",
    }
    candidates = [
        building for building in buildings if building.get("thing") in military
    ] or buildings
    building = rng.choice(candidates)
    program_id = 3 if building.get("thing") in military else 0
    current = building.get("program") if isinstance(building.get("program"), dict) else {}
    if int(current.get("id", -1)) == program_id:
        return {"type": "town.select_building", "x": building["x"], "y": building["y"]}
    return {
        "type": "town.set_program",
        "x": building["x"],
        "y": building["y"],
        "program_id": program_id,
    }


if __name__ == "__main__":
    asyncio.run(main())
