from __future__ import annotations

from typing import Any

import pytest

from players.player_sdk import (
    Button,
    SpriteContext,
    SpriteWorld,
    run_sprite_bridge,
)
from players.player_sdk.sprite_bridge import (
    PACKET_CHAT,
    PACKET_INPUT,
    pack_chat_packet,
    pack_input_packet,
)

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


# -- wire-frame builders (mirror the BitWorld /sprite_player record layout) ----


def sprite_record(
    sprite_id: int, width: int, height: int, label: str, data: bytes = b""
) -> bytes:
    label_bytes = label.encode("utf-8")
    return (
        bytes([0x01])
        + sprite_id.to_bytes(2, "little")
        + width.to_bytes(2, "little")
        + height.to_bytes(2, "little")
        + len(data).to_bytes(4, "little")
        + data
        + len(label_bytes).to_bytes(2, "little")
        + label_bytes
    )


def object_record(
    object_id: int, x: int, y: int, z: int, layer: int, sprite_id: int
) -> bytes:
    return (
        bytes([0x02])
        + object_id.to_bytes(2, "little")
        + x.to_bytes(2, "little", signed=True)
        + y.to_bytes(2, "little", signed=True)
        + z.to_bytes(2, "little", signed=True)
        + bytes([layer])
        + sprite_id.to_bytes(2, "little")
    )


def remove_record(object_id: int) -> bytes:
    return bytes([0x03]) + object_id.to_bytes(2, "little")


def clear_record() -> bytes:
    return bytes([0x04])


async def _run(
    messages: list[str | bytes], decide: Any, **kwargs: Any
) -> FakeWebSocket:
    websocket = FakeWebSocket(messages)
    await run_sprite_bridge(
        "ws://example.test/sprite_player?slot=0&token=t",
        decide,
        connect=FakeConnect(websocket),
        on_close=lambda _exc: None,
        **kwargs,
    )
    return websocket


# -- core: frame -> input packet ----------------------------------------------


@asyncio_test
async def test_changed_frame_sends_input_packet() -> None:
    ws = await _run([object_record(1000, 5, 6, 0, 1, 1)], lambda w, c: Button.UP)
    assert ws.sent == [bytes([PACKET_INPUT, int(Button.UP)])]


@asyncio_test
async def test_int_mask_is_packed() -> None:
    ws = await _run([clear_record()], lambda w, c: 0x21)
    assert ws.sent == [bytes([PACKET_INPUT, 0x21])]


@asyncio_test
async def test_mask_zero_is_sent_to_release_buttons() -> None:
    # 0 is a real "release everything" mask, distinct from None.
    ws = await _run([clear_record()], lambda w, c: 0)
    assert ws.sent == [bytes([PACKET_INPUT, 0])]


@asyncio_test
async def test_none_sends_nothing() -> None:
    ws = await _run([clear_record()], lambda w, c: None)
    assert ws.sent == []


# -- decide receives the accumulated world ------------------------------------


@asyncio_test
async def test_world_accumulates_sprites_and_objects() -> None:
    seen: list[tuple[SpriteWorld, SpriteContext]] = []

    def decide(world: SpriteWorld, ctx: SpriteContext) -> None:
        # Capture a snapshot of sizes by reading live state on the last call.
        seen.append((world, ctx))
        return None

    await _run(
        [
            sprite_record(7, 32, 32, "map", data=b"\x01\x02"),
            object_record(1000, 11, 12, 0, 1, 7),
        ],
        decide,
    )
    world, ctx = seen[-1]
    assert world.frame == 2 and ctx.frame == 2
    assert world.sprites[7].label == "map"
    assert world.sprites[7].width == 32 and world.sprites[7].data == b"\x01\x02"
    obj = world.objects[1000]
    assert (obj.x, obj.y, obj.layer, obj.sprite_id) == (11, 12, 1, 7)
    assert world.sprite_for(obj) is world.sprites[7]


@asyncio_test
async def test_negative_object_coordinates_round_trip() -> None:
    captured: list[int] = []

    def decide(world: SpriteWorld, ctx: SpriteContext) -> None:
        captured.append(world.objects[1000].x)
        return None

    await _run([object_record(1000, -40, -3, 0, 0, 1)], decide)
    assert captured == [-40]


@asyncio_test
async def test_object_remove_and_clear() -> None:
    sizes: list[int] = []

    def decide(world: SpriteWorld, ctx: SpriteContext) -> None:
        sizes.append(len(world.objects))
        return None

    await _run(
        [
            object_record(1000, 1, 1, 0, 0, 1),
            object_record(1001, 2, 2, 0, 0, 1),
            remove_record(1000),
            clear_record(),
        ],
        decide,
    )
    assert sizes == [1, 2, 1, 0]


# -- frame gating: only changed frames trigger decide -------------------------


@asyncio_test
async def test_skip_records_do_not_trigger_decide() -> None:
    calls = 0

    def decide(world: SpriteWorld, ctx: SpriteContext) -> None:
        nonlocal calls
        calls += 1
        return None

    await _run(
        [
            bytes([0x05, 0, 0, 0, 0, 0]),  # 0x05: 5-byte skip record, no change
            bytes([0x06, 0, 0, 0]),  # 0x06: 3-byte skip record, no change
            object_record(1000, 1, 1, 0, 0, 1),  # the only world-changing frame
        ],
        decide,
    )
    assert calls == 1


# -- chat ----------------------------------------------------------------------


@asyncio_test
async def test_mask_and_chat_tuple_sends_both() -> None:
    ws = await _run([clear_record()], lambda w, c: (Button.A, "body in nav"))
    assert ws.sent == [
        bytes([PACKET_INPUT, int(Button.A)]),
        pack_chat_packet("body in nav"),
    ]
    assert ws.sent[1][0] == PACKET_CHAT


@asyncio_test
async def test_chat_only_via_none_mask_tuple() -> None:
    ws = await _run([clear_record()], lambda w, c: (None, "skip"))
    assert ws.sent == [pack_chat_packet("skip")]


# -- on_frame hook -------------------------------------------------------------


@asyncio_test
async def test_on_frame_hook_runs_per_changed_frame() -> None:
    frames: list[int] = []
    await _run(
        [object_record(1000, 1, 1, 0, 0, 1), clear_record()],
        lambda w, c: None,
        on_frame=lambda w, c: frames.append(c.frame),
    )
    assert frames == [1, 2]


# -- async decide --------------------------------------------------------------


@asyncio_test
async def test_async_decide_is_awaited() -> None:
    async def decide(world: SpriteWorld, ctx: SpriteContext) -> int:
        return int(Button.LEFT)

    ws = await _run([clear_record()], decide)
    assert ws.sent == [bytes([PACKET_INPUT, int(Button.LEFT)])]


# -- robustness: never crash on junk ------------------------------------------


@asyncio_test
async def test_truncated_and_unknown_frames_do_not_crash() -> None:
    calls = 0

    def decide(world: SpriteWorld, ctx: SpriteContext) -> int:
        nonlocal calls
        calls += 1
        return int(Button.UP)

    ws = await _run(
        [
            b"\x01\x00\x00",  # truncated sprite header -> applies nothing, no change
            b"\xff\xff",  # unknown record kind -> stop, no change
            "stray text frame",  # text on a binary protocol -> ignored
            object_record(1000, 1, 1, 0, 0, 1),  # the only actionable frame
        ],
        decide,
    )
    assert calls == 1
    assert len(ws.sent) == 1


@asyncio_test
async def test_invalid_chat_is_dropped_not_raised() -> None:
    # Non-ASCII chat must not crash the bridge mid-episode; the mask still sends.
    ws = await _run([clear_record()], lambda w, c: (Button.UP, "snow☃man"))
    assert ws.sent == [bytes([PACKET_INPUT, int(Button.UP)])]


# -- connect passthrough -------------------------------------------------------


@asyncio_test
async def test_connect_kwargs_forwarded() -> None:
    websocket = FakeWebSocket([])
    connect = FakeConnect(websocket)
    await run_sprite_bridge(
        "ws://unused",
        lambda w, c: None,
        connect=connect,
        on_close=lambda _exc: None,
        max_size=None,
    )
    assert connect.calls == [("ws://unused", {"max_size": None})]


# -- packet helpers ------------------------------------------------------------


def test_pack_input_packet_round_trip() -> None:
    assert pack_input_packet(0x21) == bytes([PACKET_INPUT, 0x21])


def test_pack_input_packet_rejects_out_of_range() -> None:
    with pytest.raises(ValueError):
        pack_input_packet(0x80)


def test_pack_chat_packet_layout() -> None:
    packet = pack_chat_packet(" hello ")
    assert packet == bytes([PACKET_CHAT]) + (5).to_bytes(2, "little") + b"hello"


def test_pack_chat_packet_rejects_empty_and_non_ascii() -> None:
    with pytest.raises(ValueError):
        pack_chat_packet("   ")
    with pytest.raises(ValueError):
        pack_chat_packet("☃")
