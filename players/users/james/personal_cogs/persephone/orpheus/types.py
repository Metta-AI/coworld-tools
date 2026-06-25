"""Framework-wide public types and constants for Orpheus."""

from __future__ import annotations

from enum import Enum

# ---------------------------------------------------------------------------
# Perception re-exports
# ---------------------------------------------------------------------------

# Re-export perception enums and constants so framework code doesn't reach
# into perception internals.
from orpheus.perception._common import PLAYER_COLORS
from orpheus.perception.types import PlayerShape, Room, View


# ---------------------------------------------------------------------------
# Action masks
# ---------------------------------------------------------------------------

# ActionMask: low-level button bitmask sent in PACKET_INPUT.
# Valid range 0-127 (bits 0-6); 0xFF is the protocol-level reset mask.
ActionMask = int

# Button bit constants (from GAME_API.md packet table).
BUTTON_UP: ActionMask = 0x01
BUTTON_DOWN: ActionMask = 0x02
BUTTON_LEFT: ActionMask = 0x04
BUTTON_RIGHT: ActionMask = 0x08
BUTTON_SELECT: ActionMask = 0x10
BUTTON_A: ActionMask = 0x20
BUTTON_B: ActionMask = 0x40
RESET_MASK: ActionMask = 0xFF


# ---------------------------------------------------------------------------
# Knowledge provenance
# ---------------------------------------------------------------------------


class KnowledgeSource(Enum):
    """Provenance for role and team knowledge in the player registry."""

    MUTUAL_EXCHANGE = "mutual_exchange"  # R.OFFER + R.ACCPT; satisfies win condition.
    ROLE_REVEAL = "role_reveal"  # One-way ROLE action observed.
    COLOR_EXCHANGE = "color_exchange"  # C.OFFER + C.ACCPT; team only.
    GAME_DISPLAY = "game_display"  # Info/exchange screens and overworld indicators.
    CHAT_CLAIM = "chat_claim"  # Stated by a player in chat; unverified.
    INFERRED = "inferred"  # LLM/mode reasoning; speculative.


__all__ = [
    "View",
    "Room",
    "PlayerShape",
    "PLAYER_COLORS",
    "ActionMask",
    "BUTTON_UP",
    "BUTTON_DOWN",
    "BUTTON_LEFT",
    "BUTTON_RIGHT",
    "BUTTON_SELECT",
    "BUTTON_A",
    "BUTTON_B",
    "RESET_MASK",
    "KnowledgeSource",
]
