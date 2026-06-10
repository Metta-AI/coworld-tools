"""In-process bridge smoke (design §3).

Stands up a real websocket server, streams a few binary "scene" frames, and
asserts the bridge connects, drives the idle runtime, sends the neutral input
packet exactly once (send-only-on-change), and exits cleanly when the server
closes the socket.
"""

from __future__ import annotations

import asyncio
import io
import json
import sys

import pytest
from websockets.asyncio.server import serve
from websockets.exceptions import ConnectionClosed, ConnectionClosedError

from players.crewrift.crewborg.action import INPUT_HEADER, encode_chat
from players.crewrift.crewborg.coworld.policy_player import run_bridge
from players.crewrift.crewborg.tests import sprite_wire as w
from players.crewrift.crewborg.types import Command
from players.player_sdk import NullMetricsSink, TraceEvent

pytestmark = pytest.mark.asyncio


async def test_bridge_defaults_to_lean_trace_and_no_metrics(monkeypatch) -> None:
    class FakeRuntime:
        def close(self) -> None:
            pass

    captured: dict[str, object] = {}
    stderr = io.StringIO()
    monkeypatch.delenv("CREWBORG_TRACE", raising=False)
    monkeypatch.delenv("CREWBORG_METRICS", raising=False)
    monkeypatch.setattr(sys, "stderr", stderr)

    def build(**kwargs):
        captured.update(kwargs)
        return FakeRuntime()

    def failing_connect(*_args, **_kwargs):
        raise RuntimeError("connect failed")

    with pytest.raises(RuntimeError, match="connect failed"):
        await run_bridge("ws://unused", connect=failing_connect, build=build)

    assert isinstance(captured["metrics_sink"], NullMetricsSink)
    trace_sink = captured["trace_sink"]
    trace_sink.record(TraceEvent(tick=1, name="perception", data={}))
    trace_sink.record(TraceEvent(tick=2, name="domain.meeting_vote_selected", data={}))
    records = [json.loads(line) for line in stderr.getvalue().splitlines()]
    assert [record["event"] for record in records] == ["domain.meeting_vote_selected"]


async def test_bridge_enables_metrics_when_requested(monkeypatch) -> None:
    class FakeRuntime:
        def close(self) -> None:
            pass

    captured: dict[str, object] = {}
    monkeypatch.setenv("CREWBORG_METRICS", "1")

    def build(**kwargs):
        captured.update(kwargs)
        return FakeRuntime()

    def failing_connect(*_args, **_kwargs):
        raise RuntimeError("connect failed")

    with pytest.raises(RuntimeError, match="connect failed"):
        await run_bridge("ws://unused", connect=failing_connect, build=build)

    assert not isinstance(captured["metrics_sink"], NullMetricsSink)


async def test_bridge_runs_idle_loop_and_exits_cleanly() -> None:
    bridge_packets: list[bytes] = []

    async def handler(websocket) -> None:
        # Stream three valid scene frames, then drain whatever the bridge replies
        # with and close (returning from the handler closes the connection).
        for _ in range(3):
            await websocket.send(w.clear_objects())
        try:
            while True:
                bridge_packets.append(await asyncio.wait_for(websocket.recv(), timeout=0.25))
        except (asyncio.TimeoutError, ConnectionClosed):
            return

    async with serve(handler, "localhost", 0) as server:
        port = server.sockets[0].getsockname()[1]
        url = f"ws://localhost:{port}/player?slot=0&token="
        # The bridge must return on its own when the server closes the socket.
        await asyncio.wait_for(run_bridge(url), timeout=5.0)

    # Idle holds mask 0; the bridge sends the neutral packet once and nothing
    # after, since the held mask never changes.
    assert bridge_packets == [bytes([INPUT_HEADER, 0x00])]


async def test_bridge_treats_unclean_close_as_game_end() -> None:
    """The Crewrift Nim server drops the ``/player`` socket without a close
    handshake (code 1006, "no close frame received or sent") at game end. The
    bridge must treat that unclean close as normal termination — return without
    raising so the container exits 0 — and still close the runtime. (The
    websockets async iterator swallows a *clean* close but re-raises
    ``ConnectionClosedError`` on an unclean one, which is what this guards.)"""

    class FakeRuntime:
        def __init__(self) -> None:
            self.closed = False

        def step(self, _observation) -> Command:
            return Command(held_mask=0)

        def close(self) -> None:
            self.closed = True

    fake_runtime = FakeRuntime()

    class UncleanConnection:
        """Async context manager + iterator: yields one scene frame, then raises
        ``ConnectionClosedError`` exactly as the real server's abrupt close does."""

        def __init__(self) -> None:
            self._frame_sent = False

        async def __aenter__(self) -> UncleanConnection:
            return self

        async def __aexit__(self, *exc: object) -> bool:
            return False

        def __aiter__(self) -> UncleanConnection:
            return self

        async def __anext__(self) -> bytes:
            if not self._frame_sent:
                self._frame_sent = True
                return w.clear_objects()
            raise ConnectionClosedError(None, None)

        async def send(self, _data: bytes) -> None:
            pass

    def fake_connect(*_args: object, **_kwargs: object) -> UncleanConnection:
        return UncleanConnection()

    # Must return (not raise) despite the unclean close, and still close the runtime.
    await asyncio.wait_for(
        run_bridge("ws://unused", connect=fake_connect, build=lambda **_: fake_runtime),
        timeout=5.0,
    )
    assert fake_runtime.closed


async def test_bridge_closes_runtime_when_connect_raises() -> None:
    """A failure anywhere in connect/loop/send must still close the runtime
    (the strategy runner may own background threads/tasks)."""

    class FakeRuntime:
        def __init__(self) -> None:
            self.closed = False

        def close(self) -> None:
            self.closed = True

    fake = FakeRuntime()

    def failing_connect(*args, **kwargs):
        raise RuntimeError("connect failed")

    with pytest.raises(RuntimeError, match="connect failed"):
        await run_bridge("ws://unused", connect=failing_connect, build=lambda **_: fake)

    assert fake.closed


async def test_bridge_sends_chat_packet() -> None:
    received: list[bytes] = []

    class ChattyRuntime:
        def __init__(self) -> None:
            self.steps = 0

        def step(self, _observation) -> Command:
            self.steps += 1
            return Command(held_mask=0, chat="gg") if self.steps == 1 else Command(held_mask=0)

        def close(self) -> None:
            pass

    async def handler(websocket) -> None:
        await websocket.send(w.clear_objects())
        try:
            while True:
                received.append(await asyncio.wait_for(websocket.recv(), timeout=0.25))
        except (asyncio.TimeoutError, ConnectionClosed):
            return

    async with serve(handler, "localhost", 0) as server:
        port = server.sockets[0].getsockname()[1]
        url = f"ws://localhost:{port}/player?slot=0&token="
        await asyncio.wait_for(run_bridge(url, build=lambda **_: ChattyRuntime()), timeout=5.0)

    assert encode_chat("gg") in received
