from __future__ import annotations

import asyncio
import json
import os
import random
from typing import Any

import websockets


async def main() -> None:
    url = os.environ["COGAMES_ENGINE_WS_URL"]
    rng = random.Random(int(os.environ.get("TRIBALCOG_PLAYER_SEED", "0")))
    mode = os.environ.get("TRIBALCOG_PLAYER_MODE", "random")
    async with websockets.connect(url, max_size=None) as websocket:
        async for raw_message in websocket:
            message = json.loads(raw_message)
            if message["type"] == "final":
                return
            if message["type"] == "observation":
                await websocket.send(json.dumps({"action": choose_action(message, mode, rng)}))


def choose_action(message: dict[str, Any], mode: str, rng: random.Random) -> int:
    if mode == "noop":
        return 0
    action_space = int(message.get("action_space", 308))
    return rng.randrange(max(1, action_space))


if __name__ == "__main__":
    asyncio.run(main())
