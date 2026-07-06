"""Engine-specific websocket bridge for the BitWorld ``/sprite_player`` protocol.

This is the player protocol for **BitWorld / SpriteV1** games (Among Them,
Crewrift, ...). A BitWorld game server exposes a ``/sprite_player`` websocket; an
external player policy is a websocket CLIENT that connects to the URL the Coworld
runner injects (``COWORLD_PLAYER_WS_URL``) and drives one seat.

Unlike the request/reply ``cogweb.player.v1`` protocol, ``/sprite_player`` is a
**one-way render stream plus opportunistic input**: the server streams binary
sprite/object updates as the world ticks, and the client sends a held controller
mask (and optional chat) whenever it wants. There is no welcome handshake and no
``final`` frame — game-over is signalled by the server closing the socket.

The wire format (binary frames; mirrors mettagrid's ``bitworld_sprite_player`` —
the canonical protocol reference, which additionally decodes the AmongThem
*semantics*):

    server -> player   one frame = a sequence of records, each tagged by a kind byte:
        0x01  sprite definition  u16 id, u16 w, u16 h, u32 dlen, <dlen bytes>, u16 llen, <label>
        0x02  object upsert      u16 id, i16 x, i16 y, i16 z, u8 layer, u16 sprite_id
        0x03  object remove      u16 id
        0x04  clear all objects
        0x05 / 0x06              5- / 3-byte records this bridge skips (timing/keepalive)
    player -> server   input     [0x84, mask]            (mask is 7 button bits, 0..0x7F)
    player -> server   chat      [0x81, u16 len, <ascii>]

This bridge owns the **transport envelope**: it accumulates the sprite/object
stream into a :class:`SpriteWorld` (raw — it deliberately does NOT decode sprite
pixels, the palette, or any game semantics), calls a game-supplied ``decide``
once per inbound frame that changed the world, packs the returned controller mask
/ chat into outbound packets, and exits 0 when the server closes. Perception
(decoding the map sprite, reading labels, locating players) is the game's job and
lives in the game's player package; a game may import mettagrid's
``snappy_decompress`` / ``load_palette_lookup`` / ``SpritePlayerObservationAdapter``
to do it. Both the raw world and the chosen mask are pass-through.

Layering: this is the **BitWorld/SpriteV1 specialization** of
:mod:`players.player_sdk.message_bridge`, peer to
:mod:`players.player_sdk.cogweb_bridge` (cogweb) and
:mod:`players.player_sdk.coworld_json_bridge` (mettagrid). It is self-contained —
it depends only on :func:`run_message_bridge` for transport and re-expresses the
small, stable wire primitives locally, so importing it never requires the
optional ``mettagrid`` extra.
"""

from __future__ import annotations

import inspect
import struct
import sys
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from enum import IntFlag
from typing import Any

from players.player_sdk.message_bridge import (
    ClosePolicy,
    Connect,
    exit_zero_on_unclean_close,
    run_message_bridge,
)
from players.player_sdk.trace_outputs import TraceOutputs

#: Websocket path a BitWorld server serves the sprite-player protocol on.
PROTOCOL_PATH = "/sprite_player"

#: Outbound packet kinds.
PACKET_INPUT = 0x84
PACKET_CHAT = 0x81

#: A controller mask is 7 button bits.
INPUT_MASK_MAX = 0x7F

#: Inbound record kinds.
_RECORD_SPRITE = 0x01
_RECORD_OBJECT = 0x02
_RECORD_OBJECT_REMOVE = 0x03
_RECORD_CLEAR = 0x04
_RECORD_SKIP5 = 0x05
_RECORD_SKIP3 = 0x06

#: Button bit order matches the running BitWorld server (`common/protocol.nim`).
BUTTON_NAMES: tuple[str, ...] = ("up", "down", "left", "right", "select", "a", "b")


class Button(IntFlag):
    """Controller buttons. OR them together to build an input mask.

    e.g. ``Button.UP | Button.A``. A bare ``int`` mask works too.
    """

    UP = 1 << 0
    DOWN = 1 << 1
    LEFT = 1 << 2
    RIGHT = 1 << 3
    SELECT = 1 << 4
    A = 1 << 5
    B = 1 << 6


@dataclass
class SpriteDef:
    """A sprite definition as sent on the wire — raw, undecoded.

    ``data`` is the compressed pixel payload exactly as received; this bridge does
    not decompress it or resolve the palette. A game that needs pixels decodes
    ``data`` itself (e.g. via mettagrid's ``snappy_decompress`` + palette lookup).
    """

    sprite_id: int
    width: int
    height: int
    label: str
    data: bytes


@dataclass
class SpriteObject:
    """A placed object: which sprite is drawn where, on which layer."""

    object_id: int
    x: int
    y: int
    z: int
    layer: int
    sprite_id: int


@dataclass
class SpriteWorld:
    """Accumulated sprite/object render state, updated frame by frame.

    This is the raw ``view`` handed to ``decide``. ``sprites`` maps sprite id ->
    definition; ``objects`` maps object id -> placement. ``frame`` increments each
    time an inbound frame mutated the world.
    """

    sprites: dict[int, SpriteDef] = field(default_factory=dict)
    objects: dict[int, SpriteObject] = field(default_factory=dict)
    frame: int = 0

    def sprite_for(self, obj: SpriteObject) -> SpriteDef | None:
        """The :class:`SpriteDef` an object draws, or ``None`` if not yet defined."""
        return self.sprites.get(obj.sprite_id)

    def apply_frame(self, payload: bytes) -> bool:
        """Apply one inbound binary frame; return whether it changed the world.

        Robust by construction: a truncated or unknown record stops parsing and
        returns the changes applied so far rather than raising — a player process
        must not die mid-episode or the host scores the seat as failed.
        """
        offset = 0
        changed = False
        size = len(payload)
        while offset < size:
            kind = payload[offset]
            offset += 1
            if kind == _RECORD_SPRITE:
                if offset + 10 > size:
                    break
                sprite_id = _u16(payload, offset)
                width = _u16(payload, offset + 2)
                height = _u16(payload, offset + 4)
                data_len = _u32(payload, offset + 6)
                offset += 10
                if offset + data_len + 2 > size:
                    break
                data = bytes(payload[offset : offset + data_len])
                offset += data_len
                label_len = _u16(payload, offset)
                offset += 2
                if offset + label_len > size:
                    break
                label = payload[offset : offset + label_len].decode("utf-8", "replace")
                offset += label_len
                self.sprites[sprite_id] = SpriteDef(sprite_id, width, height, label, data)
                changed = True
            elif kind == _RECORD_OBJECT:
                if offset + 11 > size:
                    break
                object_id = _u16(payload, offset)
                self.objects[object_id] = SpriteObject(
                    object_id=object_id,
                    x=_i16(payload, offset + 2),
                    y=_i16(payload, offset + 4),
                    z=_i16(payload, offset + 6),
                    layer=payload[offset + 8],
                    sprite_id=_u16(payload, offset + 9),
                )
                offset += 11
                changed = True
            elif kind == _RECORD_OBJECT_REMOVE:
                if offset + 2 > size:
                    break
                self.objects.pop(_u16(payload, offset), None)
                offset += 2
                changed = True
            elif kind == _RECORD_CLEAR:
                self.objects.clear()
                changed = True
            elif kind == _RECORD_SKIP5:
                offset += 5
            elif kind == _RECORD_SKIP3:
                offset += 3
            else:
                break  # unknown record kind — stop, don't guess
        if changed:
            self.frame += 1
        return changed


@dataclass
class SpriteContext:
    """Per-frame context handed to ``decide`` alongside the world.

    Thin today (the protocol carries no seat/turn/config envelope), but kept as a
    distinct argument for symmetry with the other engine bridges and room to grow.
    """

    #: The world's frame counter at this decision (== ``world.frame``).
    frame: int


#: A controller mask: an ``int`` in [0, 127] or a :class:`Button` combination.
Mask = int
#: ``decide`` returns a mask, ``(mask, chat)`` to also send a chat line, or
#: ``None`` to send nothing this frame (the server holds the previous mask).
#: A mask of ``0`` is meaningful — it releases all buttons.
DecideResult = Mask | tuple[Mask | None, str | None] | None
Decide = Callable[
    [SpriteWorld, SpriteContext], DecideResult | Awaitable[DecideResult]
]

#: Optional hook invoked after each world-changing frame (e.g. to record traces),
#: with the world and context. Runs whether or not ``decide`` sent anything.
OnFrame = Callable[[SpriteWorld, SpriteContext], None]


def pack_input_packet(mask: int) -> bytes:
    """Pack a controller mask into a ``/sprite_player`` input packet."""
    value = int(mask)
    if not 0 <= value <= INPUT_MASK_MAX:
        raise ValueError(f"sprite input mask must be in [0, {INPUT_MASK_MAX}], got {value}")
    return bytes([PACKET_INPUT, value])


def pack_chat_packet(text: str) -> bytes:
    """Pack a chat line into a ``/sprite_player`` chat packet (printable ASCII)."""
    clean = text.strip()
    if not clean:
        raise ValueError("sprite chat text must be non-empty")
    if any(ord(ch) < 0x20 or ord(ch) >= 0x7F for ch in clean):
        raise ValueError("sprite chat text must be printable ASCII")
    payload = clean.encode("ascii")
    if len(payload) > 0xFFFF:
        raise ValueError("sprite chat text is too long")
    return bytes([PACKET_CHAT]) + len(payload).to_bytes(2, "little") + payload


class _SpriteHandler:
    """Accumulates the sprite stream and turns each frame into outbound packets.

    Robust by construction: undecodable frames and invalid ``decide`` outputs are
    skipped (never sent, never raised) so the bridge survives the whole episode.
    """

    def __init__(self, decide: Decide, *, on_frame: OnFrame | None = None) -> None:
        self._decide = decide
        self._on_frame = on_frame
        self.world = SpriteWorld()

    async def __call__(self, message: str | bytes) -> list[bytes]:
        if not isinstance(message, (bytes, bytearray, memoryview)):
            return []  # the sprite protocol is binary; ignore stray text frames
        if not self.world.apply_frame(bytes(message)):
            return []  # nothing changed this frame — don't bother the policy

        ctx = SpriteContext(frame=self.world.frame)
        result = self._decide(self.world, ctx)
        if inspect.isawaitable(result):
            result = await result
        if self._on_frame is not None:
            self._on_frame(self.world, ctx)

        mask, chat = _split_result(result)
        return _pack_outbound(mask, chat)


def _split_result(result: DecideResult) -> tuple[int | None, str | None]:
    """Normalize a ``decide`` return into ``(mask, chat)``.

    A 2-tuple is ``(mask, chat)``; anything else is the mask itself. ``None`` for
    either field means "don't send that part".
    """
    if isinstance(result, tuple) and len(result) == 2:
        mask, chat = result
        return (None if mask is None else int(mask)), chat
    if result is None:
        return None, None
    return int(result), None


def _pack_outbound(mask: int | None, chat: str | None) -> list[bytes]:
    """Pack mask/chat into wire packets, skipping (not raising on) invalid values."""
    frames: list[bytes] = []
    if mask is not None:
        try:
            frames.append(pack_input_packet(mask & INPUT_MASK_MAX))
        except ValueError as exc:  # pragma: no cover - mask is pre-masked
            print(f"sprite bridge: dropping bad input mask: {exc}", file=sys.stderr)
    if chat:
        try:
            frames.append(pack_chat_packet(chat))
        except ValueError as exc:
            print(f"sprite bridge: dropping invalid chat line: {exc}", file=sys.stderr)
    return frames


async def run_sprite_bridge(
    url: str,
    decide: Decide,
    *,
    on_frame: OnFrame | None = None,
    trace_outputs: TraceOutputs | None = None,
    connect: Connect | None = None,
    on_close: ClosePolicy = exit_zero_on_unclean_close,
    teardown: Callable[[], None] | None = None,
    **connect_kwargs: Any,
) -> None:
    """Run a BitWorld ``/sprite_player`` player loop until the server closes.

    The game supplies only ``decide``; the bridge owns the transport (accumulating
    the sprite/object stream into a :class:`SpriteWorld`, packing the controller
    mask / chat, and exit-0-on-close).

    Args:
        url: the websocket URL (typically :func:`players.player_sdk.env_ws_url`,
            which reads ``COWORLD_PLAYER_WS_URL``). Use it verbatim.
        decide: ``decide(world, ctx) -> mask`` (or ``(mask, chat)``), sync or
            async. ``world`` is the raw :class:`SpriteWorld`; ``ctx`` is a
            :class:`SpriteContext`. Return a mask (``int``/:class:`Button`) to hold
            those buttons, ``(mask, chat)`` to also broadcast a chat line, or
            ``None`` to send nothing (the server keeps the previous mask). A mask
            of ``0`` releases all buttons. Called once per inbound frame that
            changed the world.
        on_frame: optional hook run after each world-changing frame.
        trace_outputs: optional :class:`TraceOutputs`; closed on exit.
        connect: optional websocket connector (for tests); defaults to
            ``websockets.connect``.
        on_close: close policy; defaults to :func:`exit_zero_on_unclean_close`.
        teardown: optional cleanup callback run on exit.
        **connect_kwargs: forwarded to ``websockets.connect`` (e.g. ``max_size``).
    """
    handler = _SpriteHandler(decide, on_frame=on_frame)
    bridge_kwargs: dict[str, Any] = dict(connect_kwargs)
    if connect is not None:
        bridge_kwargs["connect"] = connect
    await run_message_bridge(
        url,
        handler,
        trace_outputs=trace_outputs,
        on_close=on_close,
        teardown=teardown,
        **bridge_kwargs,
    )


def _u16(data: bytes, offset: int) -> int:
    return data[offset] | (data[offset + 1] << 8)


def _i16(data: bytes, offset: int) -> int:
    return struct.unpack_from("<h", data, offset)[0]


def _u32(data: bytes, offset: int) -> int:
    return struct.unpack_from("<I", data, offset)[0]
