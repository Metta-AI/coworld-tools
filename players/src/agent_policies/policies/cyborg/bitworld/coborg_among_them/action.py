"""Action resolver: symbolic intent → BitWorld wire packets.

The BitWorld player protocol uses two packet families:

- ``[0x00, mask]`` — 2-byte input packet; ``mask`` is a 7-bit button bitmask
  (Up=1, Down=2, Left=4, Right=8, Select=16, A=32, B=64).
- ``[0x01, <ascii text>]`` — variable-length chat packet (text is 7-bit ASCII).

P0 emits exactly one input packet per tick (mask=0 for noop). Future phases
will compose chat packets alongside the input packet when the mode requests
speech.
"""

from __future__ import annotations

from agent_policies.policies.cyborg.bitworld.coborg_among_them.types import (
    ActionState,
    AmongThemBelief,
    AmongThemCommand,
    AmongThemIntent,
)


PACKET_INPUT = 0x00
PACKET_CHAT = 0x01

BUTTON_UP = 1 << 0
BUTTON_DOWN = 1 << 1
BUTTON_LEFT = 1 << 2
BUTTON_RIGHT = 1 << 3
BUTTON_SELECT = 1 << 4
BUTTON_A = 1 << 5
BUTTON_B = 1 << 6
BUTTON_MASK_VALID = 0x7F  # bit 7 is reserved


def pack_input_packet(mask: int) -> bytes:
    """Return the 2-byte input packet for ``mask`` (0-127)."""

    if not 0 <= mask <= BUTTON_MASK_VALID:
        raise ValueError(f"input mask must fit in 7 bits; got {mask:#x}")
    return bytes((PACKET_INPUT, mask))


def pack_chat_packet(text: str) -> bytes:
    """Return a chat packet carrying ``text`` (7-bit ASCII, stripped)."""

    payload = text.strip()
    if not payload:
        raise ValueError("chat text must not be empty after stripping")
    encoded = payload.encode("ascii")  # raises UnicodeEncodeError on non-ASCII
    return bytes((PACKET_CHAT,)) + encoded


def resolve_action(
    intent: AmongThemIntent,
    belief: AmongThemBelief,
    action_state: ActionState,
) -> AmongThemCommand:
    """Translate a symbolic intent into wire packets.

    The resolver always emits an input packet (mask=0 for "noop"/"chat" kinds)
    so the server receives one input per tick — Coworld's protocol expects a
    response for every frame. Chat is appended when present.
    """

    del belief  # unused in P0; P1+ may consult belief for movement plans
    mask = intent.mask if intent.kind == "input" else 0
    packets: list[bytes] = [pack_input_packet(mask)]
    if intent.kind == "chat" and intent.text:
        action_state.pending_chat.append(intent.text)
    while action_state.pending_chat:
        text = action_state.pending_chat.pop(0)
        try:
            packets.append(pack_chat_packet(text))
        except (ValueError, UnicodeEncodeError):
            continue  # drop non-compliant text rather than aborting the tick
    return AmongThemCommand(packets=tuple(packets))
