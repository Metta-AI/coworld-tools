"""Global chat view parser."""

from __future__ import annotations

import numpy as np

from ._common import (
    BAR_Y,
    COLOR_HUD_DIM,
    COLOR_HUD_NORMAL,
    SCREEN_WIDTH,
)
from ._ocr import normalize_text, read_text_any_color, read_text_at
from ._sprites import read_sprite_color
from .types import (
    ChatMessage,
    GlobalChatPerception,
    HostageGrid,
    UsurpCandidate,
)


def parse_global_chat(frame: np.ndarray) -> GlobalChatPerception:
    """Extract global chat information from a global-chat-view frame.

    Args:
        frame: (128, 128) uint8 pixel array.

    Returns:
        GlobalChatPerception with room name, usurp/hostage info, messages.
    """
    result = GlobalChatPerception()

    # -- Header: "{RoomName} CHAT" at (2, 2) in color 2 ----------------------
    header = read_text_at(frame, 2, 2, COLOR_HUD_NORMAL, 20)
    header_norm = normalize_text(header)
    if "UNDERWORLD" in header_norm.upper():
        result.room_name = "Underworld"
    elif "MORTAL" in header_norm.upper():
        result.room_name = "Mortal Realm"

    # -- Bottom bar -----------------------------------------------------------
    bar_result = read_text_any_color(frame, 2, BAR_Y + 2)
    if bar_result:
        result.bottom_bar_text = bar_result[0]

    # -- Usurp candidate (non-leader) ----------------------------------------
    usurp_text = read_text_at(frame, 2, 11, COLOR_HUD_DIM, 10)
    usurp_norm = normalize_text(usurp_text)
    if "USURP" in usurp_norm.upper():
        candidate = UsurpCandidate()
        # Check for text candidate after the label
        # Label "USURP: " is about 28px wide
        after_label = read_text_at(frame, 30, 11, COLOR_HUD_NORMAL, 6)
        after_norm = normalize_text(after_label)
        if after_norm in ("NONE", "ME"):
            candidate.text = after_norm
        else:
            # Check for sprite
            sprite_c = read_sprite_color(frame, 30, 11)
            if sprite_c:
                candidate.player_color = sprite_c
        result.usurp_candidate = candidate

    # -- Committed state (leader) ---------------------------------------------
    committed_text = read_text_at(frame, 0, 14, COLOR_HUD_NORMAL, 20)
    if "COMMITTED" in normalize_text(committed_text).upper():
        result.hostage_grid = HostageGrid(is_committed=True)

    # -- Messages (below divider line) ----------------------------------------
    # Find the divider (1px color-1 horizontal line)
    divider_y = _find_divider(frame)
    if divider_y:
        _parse_messages(frame, result, divider_y + 2)

    return result


def _find_divider(frame: np.ndarray) -> int | None:
    """Find the 1px color-1 divider line separating voting area from messages."""
    for y in range(10, 60):
        # Check if the full row is color 1
        row = frame[y, :]
        if int(row[0]) == 1 and int(row[64]) == 1 and int(row[127]) == 1:
            return y
    return None


def _parse_messages(
    frame: np.ndarray,
    result: GlobalChatPerception,
    start_y: int,
) -> None:
    """Parse global chat messages starting from start_y."""
    line_h = 7
    msg_bot = BAR_Y - 1

    for y in range(start_y, msg_bot, line_h):
        if y + line_h > msg_bot:
            break

        # Player messages have a sprite at x=2, text after
        sender_color = read_sprite_color(frame, 2, y)
        if sender_color:
            text_result = read_text_any_color(frame, 10, y)
            if text_result:
                result.messages.append(ChatMessage(
                    sender_color=sender_color,
                    is_system=False,
                    text=text_result[0],
                    y_position=y,
                ))
            continue

        # System messages in color 8
        from ._common import COLOR_HUD_ALERT

        sys_text = read_text_at(frame, 2, y, COLOR_HUD_ALERT, 25)
        if sys_text and len(sys_text.strip()) >= 2:
            result.messages.append(ChatMessage(
                sender_color=None,
                is_system=True,
                text=sys_text.strip(),
                y_position=y,
            ))
