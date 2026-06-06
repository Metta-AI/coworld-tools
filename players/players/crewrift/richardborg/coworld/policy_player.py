"""Richardborg Sprite-v1 websocket bridge."""

from __future__ import annotations

import asyncio
import os

from players.crewrift.crewborg.coworld.policy_player import run_bridge
from players.crewrift.richardborg import build_runtime


def main() -> None:
    engine_ws_url = os.environ["COGAMES_ENGINE_WS_URL"]
    asyncio.run(run_bridge(engine_ws_url, build=build_runtime))


if __name__ == "__main__":
    main()
