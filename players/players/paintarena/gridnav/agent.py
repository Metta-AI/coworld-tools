"""Websocket transport for the Paint Arena gridnav demo policy.

Connects to the game runnable, feeds each observation to a per-episode
:class:`~players.paintarena.gridnav.strategy.GridNavPolicy`, and returns the
chosen move. Transport shape mirrors ``players/paintarena/default/agent.py``
(the certification example), minus the optional artifact upload — this player
exists to demonstrate the shared ``player_sdk`` navigation libraries, not
telemetry plumbing.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from typing import Any, cast

import websockets

from players.paintarena.gridnav.strategy import GridNavPolicy, Observation

logging.basicConfig(
    level=logging.INFO, stream=sys.stderr, format="%(asctime)s %(levelname)s %(message)s"
)
logger = logging.getLogger("paintarena.gridnav")

POLICY_VERSION = "paintarena-gridnav/1"


async def main() -> None:
    url = os.environ.get("COWORLD_PLAYER_WS_URL") or os.environ["COGAMES_ENGINE_WS_URL"]
    logger.info("connecting to %s (policy=%s)", url, POLICY_VERSION)
    policy = GridNavPolicy()

    async with websockets.connect(url) as websocket:
        async for raw_message in websocket:
            message = cast(dict[str, Any], json.loads(raw_message))
            kind = message["type"]
            if kind == "final":
                logger.info("episode finished: scores=%s", message.get("scores"))
                break
            if kind != "observation":
                continue
            slot = message["slot"]
            obs = Observation.model_validate(message)
            move = policy.choose_move(obs, slot)
            await websocket.send(json.dumps({"move": move}))


if __name__ == "__main__":
    asyncio.run(main())
