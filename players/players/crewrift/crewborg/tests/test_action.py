"""Action-layer tests: input encoding and idle resolution (design §3.3, §9)."""

from __future__ import annotations

from players.crewrift.crewborg.action import (
    BTN_A,
    BTN_DOWN,
    BTN_LEFT,
    BTN_RIGHT,
    BTN_UP,
    INPUT_HEADER,
    encode_input,
    resolve_action,
)
from players.crewrift.crewborg.types import ActionState, Belief, Intent


def test_encode_input_emits_header_and_masked_byte() -> None:
    assert encode_input(0) == bytes([INPUT_HEADER, 0x00])
    assert encode_input(BTN_UP | BTN_A) == bytes([INPUT_HEADER, 0x21])
    assert encode_input(BTN_DOWN | BTN_LEFT | BTN_RIGHT) == bytes([INPUT_HEADER, 0x0E])


def test_encode_input_masks_reserved_bit_7() -> None:
    # Bit 7 is reserved and must never reach the wire.
    assert encode_input(0xFF) == bytes([INPUT_HEADER, 0x7F])


def test_resolve_idle_holds_nothing() -> None:
    action_state = ActionState(held_mask=BTN_UP)
    command = resolve_action(Intent(kind="idle"), Belief(), action_state)
    assert command.held_mask == 0
    assert command.chat is None
    assert action_state.held_mask == 0
