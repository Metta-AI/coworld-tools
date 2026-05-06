"""Perception module for Persephone's Escape.

Stateless frame parser: converts a raw 8192-byte pixel frame into a
structured symbolic representation (FramePerception).

Usage:
    from perception import parse_frame
    from perception.types import FramePerception, View

    result = parse_frame(raw_bytes)  # or parse_frame(pixels_128x128)

    if result.view == View.PLAYING and result.overworld:
        for dot in result.overworld.minimap_dots:
            print(f"Player at ({dot.world_x}, {dot.world_y})")
"""

from __future__ import annotations

import numpy as np

from ._chatroom import parse_chatroom
from ._common import DEFAULT_ROOM_SIZE, PROTOCOL_BYTES
from ._detect import detect_view
from ._exchange import parse_exchange
from ._global_chat import parse_global_chat
from ._info_screen import parse_info_screen
from ._lobby import parse_lobby
from ._overworld import parse_overworld
from ._result import parse_result
from ._role_reveal import parse_role_reveal
from ._roster_reveal import parse_roster_reveal
from ._unpack import unpack_frame
from .types import FramePerception, View

__all__ = ["parse_frame"]


def parse_frame(
    data: bytes | bytearray | np.ndarray,
    *,
    room_size: int = DEFAULT_ROOM_SIZE,
) -> FramePerception:
    """Parse a raw frame into a complete symbolic representation.

    Args:
        data: Either raw 8192 bytes (from WebSocket) or a pre-unpacked
              (128, 128) uint8 NumPy array.
        room_size: Room dimensions for position estimation. Update this
                   after reading the role reveal screen (which reports
                   the actual room size for the current game).

    Returns:
        FramePerception with the detected view and extracted data.
    """
    # Unpack if necessary
    if isinstance(data, np.ndarray) and data.shape == (128, 128):
        frame = data
    elif isinstance(data, np.ndarray) and data.size == PROTOCOL_BYTES:
        frame = unpack_frame(data)
    else:
        frame = unpack_frame(data)

    # Detect view
    view = detect_view(frame)

    # Build result
    result = FramePerception(view=view, raw_pixels=frame)

    # Dispatch to view-specific parser
    if view == View.LOBBY:
        result.lobby = parse_lobby(frame)

    elif view == View.ROLE_REVEAL:
        result.role_reveal = parse_role_reveal(frame)

    elif view == View.ROSTER_REVEAL:
        result.roster_reveal = parse_roster_reveal(frame)

    elif view == View.PLAYING:
        result.overworld = parse_overworld(frame, room_size)

    elif view in (View.HOSTAGE_SELECT, View.LEADER_SUMMIT):
        result.overworld = parse_overworld(frame, room_size)

    elif view == View.WAITING_ENTRY:
        # Waiting entry is an overworld sub-state: the game world is
        # still rendered. Populate overworld data so agents have spatial
        # info while waiting.
        result.overworld = parse_overworld(frame, room_size)

    elif view == View.WHISPER:
        result.chatroom = parse_chatroom(frame)

    elif view == View.GLOBAL_CHAT:
        result.global_chat = parse_global_chat(frame)

    elif view == View.INFO_SCREEN:
        result.info_screen = parse_info_screen(frame)

    elif view == View.HOSTAGE_EXCHANGE:
        result.exchange = parse_exchange(frame)

    elif view in (View.REVEAL, View.GAME_OVER):
        result.result = parse_result(frame)

    # UNKNOWN: no sub-view populated (just raw_pixels available)

    return result
