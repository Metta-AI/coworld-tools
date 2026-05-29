"""Action layer: resolve symbolic intents into wire payloads (design §9).

All Sprite-v1 transport mechanics live here. ``resolve_action`` is stateful
across ticks via ``ActionState``; P0 only handles ``idle`` (hold nothing).
Navigation, the edge-triggered A-press FSM, momentum control, and chat buffering
arrive in P2+.

Wire encoding (design §3.3, AGENTS.md §2):

- Input: ``[0x84, mask & 0x7f]`` — d-pad up/down/left/right = ``0x01/0x02/0x04/0x08``,
  A = ``0x20``, B = ``0x40``; bit 7 reserved. Sent only when the held mask changes
  (the bridge owns that comparison).
"""

from __future__ import annotations

from players.crewrift.crewborg.types import ActionState, Belief, Command, Intent

INPUT_HEADER = 0x84
MASK_BITS = 0x7F

# Button bit assignments (AGENTS.md §2 / design §3.3).
BTN_UP = 0x01
BTN_DOWN = 0x02
BTN_LEFT = 0x04
BTN_RIGHT = 0x08
BTN_A = 0x20
BTN_B = 0x40


def encode_input(held_mask: int) -> bytes:
    """Encode a held-button bitmask into a Sprite-v1 input packet."""

    return bytes([INPUT_HEADER, held_mask & MASK_BITS])


def resolve_action(intent: Intent, belief: Belief, action_state: ActionState) -> Command:
    """Execute an intent into this tick's wire command.

    P0: every intent resolves to "hold nothing" (mask 0). Later phases diff the
    incoming intent against ``action_state`` and advance nav routes / button FSMs.
    """

    del belief  # unused in P0
    if intent.kind in ("idle", "loiter"):
        action_state.held_mask = 0
        return Command(held_mask=0)

    # Other intent kinds are part of the vocabulary but not yet wired (P2+).
    action_state.held_mask = 0
    return Command(held_mask=0)
