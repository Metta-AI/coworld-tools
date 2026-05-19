"""End-to-end smoke for the Coworld WebSocket bridge.

Spins an in-process WebSocket server that mimics the BitWorld game protocol:
sends N packed frames, expects N matching 2-byte noop input packets, then
closes. The bridge must consume each frame, drive the runtime, and emit the
correct wire output.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator

import pytest
from websockets.asyncio.server import ServerConnection, serve

from players.among_them.coborg.coworld.policy_player import (
    run_player,
)
from players.among_them.coborg.types import (
    PACKED_FRAME_BYTES,
)


@contextlib.asynccontextmanager
async def _fake_server(
    *, frame_count: int, received: list[bytes]
) -> AsyncIterator[str]:
    """Yield a ws:// URL pointing at a server that scripts ``frame_count`` frames."""

    done = asyncio.Event()

    async def handler(websocket: ServerConnection) -> None:
        try:
            for _ in range(frame_count):
                await websocket.send(bytes(PACKED_FRAME_BYTES))
                packet = await asyncio.wait_for(websocket.recv(), timeout=2.0)
                received.append(bytes(packet))
            await websocket.close()
        finally:
            done.set()

    server = await serve(handler, host="127.0.0.1", port=0)
    try:
        host, port = next(iter(server.sockets)).getsockname()[:2]
        yield f"ws://{host}:{port}/player?slot=0&token=test"
        await asyncio.wait_for(done.wait(), timeout=5.0)
    finally:
        server.close()
        await server.wait_closed()


@pytest.mark.asyncio
async def test_player_emits_noop_per_frame() -> None:
    received: list[bytes] = []
    async with _fake_server(frame_count=3, received=received) as url:
        await run_player(url, slot=0)
    assert received == [bytes([0x00, 0x00])] * 3


@pytest.mark.asyncio
async def test_player_ignores_short_messages() -> None:
    received: list[bytes] = []

    async def handler(websocket: ServerConnection) -> None:
        # Send one too-short message, then one valid frame.
        await websocket.send(bytes(16))  # not a frame, should be ignored
        await websocket.send(bytes(PACKED_FRAME_BYTES))
        packet = await asyncio.wait_for(websocket.recv(), timeout=2.0)
        received.append(bytes(packet))
        await websocket.close()

    server = await serve(handler, host="127.0.0.1", port=0)
    try:
        host, port = next(iter(server.sockets)).getsockname()[:2]
        url = f"ws://{host}:{port}/player?slot=0&token=test"
        await run_player(url, slot=0)
    finally:
        server.close()
        await server.wait_closed()
    assert received == [bytes([0x00, 0x00])]
