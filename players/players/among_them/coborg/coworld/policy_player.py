"""``bitscreen_v1`` binary WebSocket bridge for the coborg Among Them agent.

Among Them speaks the binary ``bitscreen_v1`` wire protocol, not the JSON
``coworld.player.v1`` used by cogsguard players, so this leaf does not use
the SDK's ``players.player_sdk.coworld_json_bridge``.

The bridge:

1. Reads ``COGAMES_ENGINE_WS_URL`` from the environment (overridable via
   ``--url``). Coworld's runner sets this URL with ``?slot=N&token=...`` query
   params already filled in.
2. Connects with ``websockets.connect`` (no further handshake required —
   token validation happens at HTTP upgrade time).
3. Loops over binary messages, expecting each one to be a packed 8192-byte
   BitWorld frame. Each frame drives one ``AgentRuntime.step`` and the
   resulting wire packets are sent back to the server.
4. Exits cleanly when the server closes the WebSocket (signal for game end).

Pinned against runner.py SHA e791117ff1aac01a8ae220c258ab121876511aed
(``Metta-AI/metta``, packages/coworld/src/coworld/runner/runner.py).
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
from typing import Any

import websockets
from websockets.exceptions import ConnectionClosed

from players.among_them.coborg import build_runtime
from players.among_them.coborg.trace import (
    JsonStderrTraceSink,
    configure_stderr_logging,
)
from players.among_them.coborg.types import (
    PACKED_FRAME_BYTES,
    AmongThemObservation,
)

LOGGER = logging.getLogger("coborg_among_them.coworld")


async def run_player(engine_ws_url: str, *, slot: int = 0) -> None:
    """Run the BitWorld binary-protocol loop against ``engine_ws_url``."""

    trace_sink = JsonStderrTraceSink()
    runtime = build_runtime(trace_sink=trace_sink)
    LOGGER.info(
        "connecting coborg_among_them player to %s (slot=%s)", engine_ws_url, slot
    )
    frames_seen = 0
    try:
        async with websockets.connect(engine_ws_url, max_size=None) as websocket:
            try:
                async for message in websocket:
                    if not _is_frame(message):
                        LOGGER.debug(
                            "ignoring non-frame message: %r", _describe(message)
                        )
                        continue
                    frame_bytes = bytes(message)  # type: ignore[arg-type]
                    observation = AmongThemObservation(
                        packed_frame=frame_bytes, slot=slot
                    )
                    command = runtime.step(observation)
                    for packet in command.packets:
                        await websocket.send(packet)
                    frames_seen += 1
            except ConnectionClosed as close:
                LOGGER.info(
                    "coworld websocket closed after %s frames (%s)", frames_seen, close
                )
    finally:
        runtime.close()


def _is_frame(message: Any) -> bool:
    return (
        isinstance(message, (bytes, bytearray, memoryview))
        and len(message) == PACKED_FRAME_BYTES
    )


def _describe(message: Any) -> str:
    if isinstance(message, (bytes, bytearray, memoryview)):
        return f"<binary len={len(message)}>"
    text = str(message)
    return text if len(text) <= 80 else text[:77] + "..."


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="coborg_among_them BitWorld player bridge"
    )
    parser.add_argument(
        "--url",
        default="",
        help="Override the WebSocket URL (defaults to $COGAMES_ENGINE_WS_URL).",
    )
    parser.add_argument(
        "--slot",
        type=int,
        default=int(os.environ.get("COGAMES_PLAYER_SLOT", "0")),
        help="Player slot (informational; tagged onto observations).",
    )
    parser.add_argument(
        "--log-level",
        default=os.environ.get("COBORG_AMONG_THEM_LOG_LEVEL", "INFO"),
        help="Python logging level for stderr logs.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(list(argv) if argv is not None else sys.argv[1:])
    configure_stderr_logging(
        level=getattr(logging, args.log_level.upper(), logging.INFO)
    )
    url = args.url or os.environ.get("COGAMES_ENGINE_WS_URL", "").strip()
    if not url:
        LOGGER.error("no WebSocket URL: pass --url or set COGAMES_ENGINE_WS_URL")
        return 2
    try:
        asyncio.run(run_player(url, slot=args.slot))
    except KeyboardInterrupt:
        LOGGER.info("interrupted by signal; exiting")
        return 130
    except OSError as err:
        LOGGER.error("network error: %s", err)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
