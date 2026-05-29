"""Crewborg's Sprite-v1 websocket bridge (design §3, AGENTS.md §Transport).

The bridge connects to the Crewrift engine, maintains a :class:`SceneState` as
binary messages arrive, drives ``runtime.step`` once per tick, and sends an input
packet only when the held button mask changes. It exits cleanly when the server
closes the socket (= game over).

**P0 scope.** Each incoming binary message is treated as one tick trigger with a
placeholder ``SceneState.apply`` (the full Sprite-v1 decoder and the
drain-to-latest-frame coalescing land in P1). The idle policy holds mask 0, so
after the initial neutral packet the bridge sends nothing.

Environment:

- ``COGAMES_ENGINE_WS_URL`` — websocket URL including ``?slot=…&token=…``
  (the runner fills these in; token validation is at HTTP upgrade).
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import Callable
from typing import Any

import websockets

from players.crewrift.crewborg import build_runtime
from players.crewrift.crewborg.action import encode_input
from players.crewrift.crewborg.coworld.scene import SceneState
from players.crewrift.crewborg.trace import StderrJsonMetricsSink, StderrJsonTraceSink
from players.crewrift.crewborg.types import Observation


async def run_bridge(
    engine_ws_url: str,
    *,
    connect: Callable[..., Any] = websockets.connect,
    build: Callable[..., Any] = build_runtime,
) -> None:
    """Connect, run the per-tick loop, and return when the socket closes."""

    scene = SceneState()
    runtime = build(
        trace_sink=StderrJsonTraceSink(),
        metrics_sink=StderrJsonMetricsSink(),
    )
    last_sent_mask: int | None = None

    async with connect(engine_ws_url, max_size=None) as websocket:
        async for message in websocket:
            if isinstance(message, str):
                # The /player stream is binary Sprite-v1; ignore stray text.
                continue
            scene.apply(message)
            scene.tick += 1

            command = runtime.step(Observation(scene=scene, tick=scene.tick))

            # Send only when the held mask changes (design §3.3). The first tick
            # sends the neutral mask once, establishing "all buttons released".
            if command.held_mask != last_sent_mask:
                await websocket.send(encode_input(command.held_mask))
                last_sent_mask = command.held_mask

    runtime.close()


def main() -> None:
    engine_ws_url = os.environ["COGAMES_ENGINE_WS_URL"]
    asyncio.run(run_bridge(engine_ws_url))


if __name__ == "__main__":
    main()
