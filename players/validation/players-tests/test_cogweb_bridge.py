from __future__ import annotations

import json
from typing import Any

import pytest

from players.player_sdk import CogwebContext, env_ws_url, run_cogweb_bridge

# Most tests drive the async bridge; the env_ws_url tests are sync and mark
# themselves out. (Applying asyncio per-test avoids warning on the sync ones.)
asyncio_test = pytest.mark.asyncio


class FakeWebSocket:
    def __init__(self, messages: list[str | bytes]) -> None:
        self._messages = iter(messages)
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


def _welcome(slot: int = 0, config: Any = None) -> str:
    return json.dumps(
        {"type": "welcome", "protocol": "cogweb.player.v1", "slot": slot, "config": config}
    )


def _observation(
    *, id: int, seat: int = 0, turn: int = 1, view: Any = None, **extra: Any
) -> str:
    msg = {"type": "observation", "id": id, "seat": seat, "turn": turn, "view": view}
    msg.update(extra)
    return json.dumps(msg)


def _final(scores: list[float]) -> str:
    return json.dumps({"type": "final", "scores": scores})


async def _run(messages: list[str | bytes], decide: Any, **kwargs: Any) -> FakeWebSocket:
    websocket = FakeWebSocket(messages)
    await run_cogweb_bridge(
        "ws://example.test/player?slot=0&token=t",
        decide,
        connect=FakeConnect(websocket),
        on_close=lambda _exc: None,
        **kwargs,
    )
    return websocket


# -- core observation -> reply flow -------------------------------------------

@asyncio_test
async def test_observation_produces_reply_echoing_id() -> None:
    ws = await _run(
        [_welcome(), _observation(id=7, view={"round": 1})],
        lambda view, ctx: {"action": "forest"},
    )
    assert len(ws.sent) == 1
    reply = json.loads(ws.sent[0])
    assert reply == {"type": "reply", "id": 7, "decision": {"action": "forest"}}


@asyncio_test
async def test_decide_receives_view_and_context() -> None:
    seen: list[tuple[Any, CogwebContext]] = []

    def decide(view: Any, ctx: CogwebContext) -> dict:
        seen.append((view, ctx))
        return {"action": "x"}

    await _run(
        [
            _welcome(slot=2, config={"players": 4}),
            _observation(id=1, seat=2, turn=5, view={"phase": "work"}, timeLeftMs=1234),
        ],
        decide,
    )
    view, ctx = seen[0]
    assert view == {"phase": "work"}
    assert ctx.seat == 2 and ctx.turn == 5 and ctx.slot == 2
    assert ctx.time_left_ms == 1234
    assert ctx.config == {"players": 4}


@asyncio_test
async def test_no_welcome_still_decodes_observation() -> None:
    # The bridge must not require welcome before acting (seat comes from the obs).
    ws = await _run([_observation(id=3, seat=1, view={})], lambda v, c: {"action": "a"})
    assert json.loads(ws.sent[0])["id"] == 3


# -- reason re-request --------------------------------------------------------

@asyncio_test
async def test_reason_is_surfaced_on_re_request() -> None:
    reasons: list[str | None] = []

    def decide(view: Any, ctx: CogwebContext) -> dict:
        reasons.append(ctx.reason)
        return {"action": "a"}

    await _run(
        [
            _observation(id=1, view={}),
            _observation(id=1, view={}, reason="illegal: space occupied"),
        ],
        decide,
    )
    assert reasons == [None, "illegal: space occupied"]


# -- cheap talk ---------------------------------------------------------------

@asyncio_test
async def test_decision_with_talk_lines() -> None:
    ws = await _run(
        [_observation(id=1, view={})],
        lambda v, c: ({"action": "a"}, ["hello all", {"to": 1, "text": "psst"}]),
    )
    reply = json.loads(ws.sent[0])
    assert reply["decision"] == {"action": "a"}
    assert reply["messages"] == [
        {"to": None, "text": "hello all"},
        {"to": 1, "text": "psst"},
    ]


@asyncio_test
async def test_no_messages_key_when_no_talk() -> None:
    ws = await _run([_observation(id=1, view={})], lambda v, c: {"action": "a"})
    assert "messages" not in json.loads(ws.sent[0])


# -- decline ------------------------------------------------------------------

@asyncio_test
async def test_decline_sends_nothing() -> None:
    ws = await _run([_observation(id=1, view={})], lambda v, c: None)
    assert ws.sent == []


@asyncio_test
async def test_decline_via_tuple_sends_nothing() -> None:
    ws = await _run([_observation(id=1, view={})], lambda v, c: (None, ["chatter"]))
    assert ws.sent == []


# -- final + lifecycle hooks --------------------------------------------------

@asyncio_test
async def test_final_invokes_on_final_with_float_scores() -> None:
    finals: list[list[float]] = []
    await _run(
        [_observation(id=1, view={}), _final([10, 22, 7, 3])],
        lambda v, c: {"action": "a"},
        on_final=finals.append,
    )
    assert finals == [[10.0, 22.0, 7.0, 3.0]]


@asyncio_test
async def test_on_welcome_invoked_once() -> None:
    welcomes: list[CogwebContext] = []
    await _run(
        [_welcome(slot=3, config={"k": 1}), _observation(id=1, view={})],
        lambda v, c: {"action": "a"},
        on_welcome=welcomes.append,
    )
    assert len(welcomes) == 1
    assert welcomes[0].slot == 3 and welcomes[0].config == {"k": 1}


# -- async decide -------------------------------------------------------------

@asyncio_test
async def test_async_decide_is_awaited() -> None:
    async def decide(view: Any, ctx: CogwebContext) -> dict:
        return {"action": "async"}

    ws = await _run([_observation(id=9, view={})], decide)
    assert json.loads(ws.sent[0])["decision"] == {"action": "async"}


# -- robustness: never crash on junk -----------------------------------------

@asyncio_test
async def test_junk_and_unknown_frames_are_ignored() -> None:
    calls = 0

    def decide(view: Any, ctx: CogwebContext) -> dict:
        nonlocal calls
        calls += 1
        return {"action": "a"}

    ws = await _run(
        [
            "not json at all",
            json.dumps([1, 2, 3]),  # valid json, not an object
            json.dumps({"type": "mystery"}),  # unknown frame type
            b"\x00\x01binary-junk",
            _observation(id=1, view={}),  # the only actionable frame
        ],
        decide,
    )
    assert calls == 1
    assert len(ws.sent) == 1


@asyncio_test
async def test_binary_observation_frame_is_decoded() -> None:
    ws = await _run(
        [_observation(id=4, view={}).encode("utf-8")], lambda v, c: {"action": "a"}
    )
    assert json.loads(ws.sent[0])["id"] == 4


# -- connect passthrough ------------------------------------------------------

@asyncio_test
async def test_connect_kwargs_forwarded() -> None:
    websocket = FakeWebSocket([])
    connect = FakeConnect(websocket)
    await run_cogweb_bridge(
        "ws://unused",
        lambda v, c: None,
        connect=connect,
        on_close=lambda _exc: None,
        ping_interval=20,
        max_size=None,
    )
    assert connect.calls == [("ws://unused", {"ping_interval": 20, "max_size": None})]


# -- env_ws_url ---------------------------------------------------------------

def test_env_ws_url_prefers_canonical() -> None:
    assert env_ws_url({"COWORLD_PLAYER_WS_URL": "ws://canonical"}) == "ws://canonical"


def test_env_ws_url_falls_back_to_legacy() -> None:
    assert env_ws_url({"COGAMES_ENGINE_WS_URL": "ws://legacy"}) == "ws://legacy"


def test_env_ws_url_raises_when_unset() -> None:
    with pytest.raises(SystemExit, match="COWORLD_PLAYER_WS_URL is not set"):
        env_ws_url({})
