"""Action resolver wire-format unit tests."""

from __future__ import annotations

import pytest

from agent_policies.policies.cyborg.bitworld.coborg_among_them.action import (
    BUTTON_A,
    BUTTON_RIGHT,
    PACKET_CHAT,
    PACKET_INPUT,
    pack_chat_packet,
    pack_input_packet,
    resolve_action,
)
from agent_policies.policies.cyborg.bitworld.coborg_among_them.types import (
    ActionState,
    AmongThemBelief,
    AmongThemIntent,
)


def test_pack_input_packet_noop() -> None:
    assert pack_input_packet(0) == bytes([PACKET_INPUT, 0x00])


def test_pack_input_packet_buttons() -> None:
    mask = BUTTON_RIGHT | BUTTON_A
    assert pack_input_packet(mask) == bytes([PACKET_INPUT, mask])


def test_pack_input_packet_rejects_high_bit() -> None:
    with pytest.raises(ValueError):
        pack_input_packet(0x80)


def test_pack_chat_packet_prefixes_with_0x01() -> None:
    packet = pack_chat_packet("hello")
    assert packet[0] == PACKET_CHAT
    assert packet[1:] == b"hello"


def test_pack_chat_packet_rejects_empty() -> None:
    with pytest.raises(ValueError):
        pack_chat_packet("   ")


def test_resolve_noop_emits_zero_input_packet() -> None:
    intent = AmongThemIntent(kind="noop")
    command = resolve_action(intent, AmongThemBelief(), ActionState())
    assert command.packets == (bytes([0x00, 0x00]),)


def test_resolve_input_passes_mask_through() -> None:
    intent = AmongThemIntent(kind="input", mask=BUTTON_RIGHT | BUTTON_A)
    command = resolve_action(intent, AmongThemBelief(), ActionState())
    assert command.packets == (bytes([0x00, BUTTON_RIGHT | BUTTON_A]),)


def test_resolve_chat_appends_chat_packet_after_input() -> None:
    intent = AmongThemIntent(kind="chat", text="hi")
    state = ActionState()
    command = resolve_action(intent, AmongThemBelief(), state)
    assert command.packets[0] == bytes([0x00, 0x00])
    assert command.packets[1] == bytes([0x01]) + b"hi"
    assert state.pending_chat == []  # consumed during resolve
