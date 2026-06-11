"""Crewborg's Sprite-v1 websocket bridge (design §3, AGENTS.md §Transport).

The bridge connects to the Crewrift engine, maintains a :class:`SceneState` as
binary messages arrive, drives ``runtime.step`` once per tick, and sends an input
packet only when the held button mask changes. It exits cleanly when the server
closes the socket (= game over).

Each incoming binary message is decoded into the ``SceneState`` and drives one
``runtime.step``; the held button mask is sent only when it changes, and meeting
chat is sent during Voting.

Environment:

- ``COGAMES_ENGINE_WS_URL`` — websocket URL including ``?slot=…&token=…``
  (the runner fills these in; token validation is at HTTP upgrade).
"""

from __future__ import annotations

import asyncio
import os
import sys
from collections.abc import Callable
from typing import Any

import websockets
from websockets.exceptions import ConnectionClosed

from players.crewrift.crewborg import build_runtime
from players.crewrift.crewborg.action import encode_chat, encode_input
from players.crewrift.crewborg.coworld.scene import SceneState
from players.crewrift.crewborg.map import walkability_matches
from players.crewrift.crewborg.trace import TraceConfig
from players.crewrift.crewborg.types import Observation
from players.player_sdk import TraceOutputs

METRICS_ENV = "CREWBORG_METRICS"


async def run_bridge(
    engine_ws_url: str,
    *,
    connect: Callable[..., Any] = websockets.connect,
    build: Callable[..., Any] = build_runtime,
) -> None:
    """Connect, run the per-tick loop, and return when the socket closes."""

    scene = SceneState()
    trace_config = TraceConfig.from_env()
    with TraceOutputs.from_env(
        prefix="CREWBORG",
        event_filter=trace_config.allows,
        metrics_enabled=_metrics_enabled(),
    ) as outputs:
        runtime = build(trace_sink=outputs.trace_sink, metrics_sink=outputs.metrics_sink)
        last_sent_mask: int | None = None
        walkability_checked = False

        # Guarantee runtime cleanup (the strategy runner may own background
        # threads/tasks) even if connect, a step, or a shutdown-race send raises.
        try:
            async with connect(engine_ws_url, max_size=None) as websocket:
                try:
                    async for message in websocket:
                        if isinstance(message, str):
                            # The /player stream is binary Sprite-v1; ignore stray text.
                            continue
                        scene.apply(message)
                        if not scene.last_message_had_tick_marker:
                            raise RuntimeError("player frame missing server tick marker")

                        # Validate the baked map against the streamed walkability mask
                        # once it arrives (design §6); a size mismatch means a different
                        # map than croatoan. Warn loudly rather than misnavigate later.
                        if not walkability_checked and scene.walkability is not None:
                            walkability_checked = True
                            map_data = runtime.belief.map
                            if map_data is not None and not walkability_matches(
                                map_data, scene.walkability_width, scene.walkability_height
                            ):
                                print(
                                    "WARNING: walkability map "
                                    f"{scene.walkability_width}x{scene.walkability_height} does not match "
                                    f"baked map {map_data.width}x{map_data.height}; server may be running "
                                    "a different map than croatoan.",
                                    file=sys.stderr,
                                    flush=True,
                                )

                        command = runtime.step(Observation(scene=scene, tick=scene.tick))

                        # Send only when the held mask changes (design §3.3). The first
                        # tick sends the neutral mask once, establishing "all released".
                        if command.held_mask != last_sent_mask:
                            await websocket.send(encode_input(command.held_mask))
                            last_sent_mask = command.held_mask

                        # Meeting chat (accepted only during Voting); sent as it appears.
                        if command.chat is not None:
                            await websocket.send(encode_chat(command.chat))
                except ConnectionClosed:
                    # Game end: the Crewrift server closes the socket to signal the
                    # episode is over. It does so *abruptly* — no close handshake
                    # (code 1006, "no close frame received or sent") — which the
                    # websockets async iterator surfaces as ConnectionClosedError
                    # rather than swallowing (as it does a clean ConnectionClosedOK).
                    # Either way a close means the game is over: treat it as normal
                    # termination so the process exits 0. The Coworld runner requires
                    # every player container to exit 0; propagating here would fail
                    # the whole episode (runner._wait_for_player_exit).
                    print("game over: server closed the connection", file=sys.stderr, flush=True)
        finally:
            runtime.close()


def main() -> None:
    engine_ws_url = os.environ["COGAMES_ENGINE_WS_URL"]
    asyncio.run(run_bridge(engine_ws_url))


def _metrics_enabled() -> bool:
    trace_level = os.environ.get("CREWBORG_TRACE", "").strip().lower()
    metrics_flag = os.environ.get(METRICS_ENV, "").strip().lower()
    return trace_level == "debug" or metrics_flag in {"1", "true", "yes", "on"}


if __name__ == "__main__":
    main()
