from __future__ import annotations

from typing import Any

import pytest
from websockets.exceptions import ConnectionClosedError

from players.player_sdk import run_message_bridge

pytestmark = pytest.mark.asyncio


class FakeWebSocket:
    def __init__(
        self,
        messages: list[str | bytes],
        *,
        close_exc: BaseException | None = None,
    ) -> None:
        self._messages = iter(messages)
        self._close_exc = close_exc
        self.sent: list[str | bytes] = []

    async def __aenter__(self) -> FakeWebSocket:
        return self

    async def __aexit__(self, *exc: object) -> bool:
        return False

    def __aiter__(self) -> FakeWebSocket:
        return self

    async def __anext__(self) -> str | bytes:
        try:
            return next(self._messages)
        except StopIteration as exc:
            if self._close_exc is not None:
                raise self._close_exc from exc
            raise StopAsyncIteration from exc

    async def send(self, frame: str | bytes) -> None:
        self.sent.append(frame)


class FakeConnect:
    def __init__(self, websocket: FakeWebSocket) -> None:
        self.websocket = websocket
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def __call__(self, url: str, **kwargs: Any) -> FakeWebSocket:
        self.calls.append((url, kwargs))
        return self.websocket


async def test_normal_dispatch_sends_one_reply_per_inbound_frame() -> None:
    websocket = FakeWebSocket(["one", "two"])
    connect = FakeConnect(websocket)

    await run_message_bridge(
        "ws://example.test/player",
        lambda message: [f"reply:{message}"],
        connect=connect,
        on_close=lambda _exc: None,
        max_size=None,
    )

    assert websocket.sent == ["reply:one", "reply:two"]
    assert connect.calls == [("ws://example.test/player", {"max_size": None})]


async def test_no_reply_sends_nothing_for_empty_iterables() -> None:
    websocket = FakeWebSocket(["ignore", "also-ignore"])

    await run_message_bridge(
        "ws://unused",
        lambda _message: [],
        connect=FakeConnect(websocket),
        on_close=lambda _exc: None,
    )

    assert websocket.sent == []


async def test_multi_reply_sends_all_frames_in_order() -> None:
    websocket = FakeWebSocket(["meeting"])

    await run_message_bridge(
        "ws://unused",
        lambda _message: ["chat:hello", "input:vote-red"],
        connect=FakeConnect(websocket),
        on_close=lambda _exc: None,
    )

    assert websocket.sent == ["chat:hello", "input:vote-red"]


async def test_clean_close_returns_normally_and_runs_teardown() -> None:
    torn_down = False

    def teardown() -> None:
        nonlocal torn_down
        torn_down = True

    await run_message_bridge(
        "ws://unused",
        lambda _message: [],
        connect=FakeConnect(FakeWebSocket([])),
        teardown=teardown,
    )

    assert torn_down


async def test_abrupt_close_exits_normally_and_runs_teardown() -> None:
    torn_down = False

    def teardown() -> None:
        nonlocal torn_down
        torn_down = True

    await run_message_bridge(
        "ws://unused",
        lambda _message: [],
        connect=FakeConnect(
            FakeWebSocket(["frame"], close_exc=ConnectionClosedError(None, None))
        ),
        teardown=teardown,
    )

    assert torn_down


async def test_teardown_runs_when_connect_raises() -> None:
    torn_down = False

    def failing_connect(*_args: object, **_kwargs: object) -> FakeWebSocket:
        raise RuntimeError("connect failed")

    def teardown() -> None:
        nonlocal torn_down
        torn_down = True

    with pytest.raises(RuntimeError, match="connect failed"):
        await run_message_bridge(
            "ws://unused",
            lambda _message: [],
            connect=failing_connect,
            teardown=teardown,
        )

    assert torn_down


async def test_non_close_handler_error_propagates_and_runs_teardown() -> None:
    torn_down = False

    def handler(_message: str | bytes) -> list[str | bytes]:
        raise RuntimeError("handler failed")

    def teardown() -> None:
        nonlocal torn_down
        torn_down = True

    with pytest.raises(RuntimeError, match="handler failed"):
        await run_message_bridge(
            "ws://unused",
            handler,
            connect=FakeConnect(FakeWebSocket(["frame"])),
            teardown=teardown,
        )

    assert torn_down


async def test_trace_outputs_closed_on_teardown() -> None:
    class FakeTraceOutputs:
        def __init__(self) -> None:
            self.closed = False

        def close(self) -> None:
            self.closed = True

    trace_outputs = FakeTraceOutputs()

    await run_message_bridge(
        "ws://unused",
        lambda _message: [],
        trace_outputs=trace_outputs,
        connect=FakeConnect(FakeWebSocket([])),
        on_close=lambda _exc: None,
    )

    assert trace_outputs.closed


async def test_binary_and_text_frames_round_trip_through_handler() -> None:
    websocket = FakeWebSocket([b"binary", "text"])
    seen: list[type[str] | type[bytes]] = []

    def handler(message: str | bytes) -> list[str | bytes]:
        seen.append(type(message))
        if isinstance(message, bytes):
            return [message + b":reply"]
        return [message + ":reply"]

    await run_message_bridge(
        "ws://unused",
        handler,
        connect=FakeConnect(websocket),
        on_close=lambda _exc: None,
    )

    assert seen == [bytes, str]
    assert websocket.sent == [b"binary:reply", "text:reply"]


async def test_async_handler_result_is_awaited() -> None:
    websocket = FakeWebSocket(["frame"])

    async def handler(_message: str | bytes) -> list[str | bytes]:
        return ["async-reply"]

    await run_message_bridge(
        "ws://unused",
        handler,
        connect=FakeConnect(websocket),
        on_close=lambda _exc: None,
    )

    assert websocket.sent == ["async-reply"]
