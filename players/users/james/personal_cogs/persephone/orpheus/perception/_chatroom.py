"""Chatroom view parser."""

from __future__ import annotations

import numpy as np

from ._common import (
    BAR_Y,
    BOTTOM_BAR_H,
    COLOR_HUD_ALERT,
    COLOR_HUD_DIM,
    COLOR_HUD_NORMAL,
    PLAYER_H,
    PLAYER_W,
    SCREEN_HEIGHT,
    SCREEN_WIDTH,
)
from ._ocr import GLYPH_H, normalize_text, read_text_any_color, read_text_at
from ._sprites import detect_sprite_shape, read_sprite_color, scan_sprite_row, scan_sprite_row_with_shapes
from .types import ChatMessage, ChatroomBarState, ChatroomPerception


def parse_chatroom(frame: np.ndarray) -> ChatroomPerception:
    """Extract chatroom information from a chatroom-view frame.

    Args:
        frame: (128, 128) uint8 pixel array.

    Returns:
        ChatroomPerception with occupants, messages, and bottom bar state.
    """
    result = ChatroomPerception()

    # -- Header: occupant sprites (x=66 in current renderer, x=22 in legacy)
    occupants = scan_sprite_row_with_shapes(frame, 66, 1, PLAYER_W + 2, outline_is_black=True)
    if not occupants:
        occupants = scan_sprite_row_with_shapes(frame, 22, 1, PLAYER_W + 2, outline_is_black=True)
    result.occupant_colors = [c for c, _ in occupants]
    result.occupant_shapes = [s for _, s in occupants]

    # -- Pending entry indicator ----------------------------------------------
    _parse_pending_entry(frame, result)

    # -- Bottom bar -----------------------------------------------------------
    _parse_bottom_bar(frame, result)

    # -- Messages (best-effort OCR) -------------------------------------------
    _parse_messages(frame, result)

    return result


def _parse_pending_entry(frame: np.ndarray, result: ChatroomPerception) -> None:
    """Detect pending entry indicator.

    Drawn at reqY = BAR_Y - 8 = 111. Look for color-8 pixels in
    the region x=[2,4], y=[110,116].
    """
    for y in range(BAR_Y - 9, BAR_Y - 3):
        for x in range(2, 5):
            if y < SCREEN_HEIGHT and x < SCREEN_WIDTH:
                if frame[y, x] == COLOR_HUD_ALERT:
                    result.has_pending_entry = True
                    # Read requester sprite color at (8+3, 111+3) = (11, 114)
                    req_color = read_sprite_color(frame, 8, 111)
                    result.pending_entry_color = req_color
                    # Also classify shape for full player ID
                    result.pending_entry_shape = detect_sprite_shape(frame, 8, 111, outline_is_black=True)
                    return


def _parse_bottom_bar(frame: np.ndarray, result: ChatroomPerception) -> None:
    """Parse chatroom bottom bar state."""
    bar_y = BAR_Y + 2  # 121

    # Check for offer indicators at (118, 121) in color 8
    offer_text = read_text_at(frame, SCREEN_WIDTH - 10, bar_y, COLOR_HUD_ALERT, 2)
    if offer_text.startswith("R"):
        result.pending_role_offer = True
    elif offer_text.startswith("C"):
        result.pending_color_offer = True

    # Read bar text in color 2 (menu) or color 1 (default)
    bar_text_2 = read_text_at(frame, 2, bar_y, COLOR_HUD_NORMAL, 20)

    if bar_text_2 and "(" in bar_text_2:
        # Menu state: "(CATEGORY) ACTION"
        result.bottom_bar = ChatroomBarState.MENU
        norm = normalize_text(bar_text_2)
        # Parse "(CAT) ITEM"
        if ")" in norm:
            paren_end = norm.index(")")
            cat = norm[1:paren_end].strip() if norm.startswith("(") else None
            item = norm[paren_end + 1:].strip()
            result.menu_category = cat
            result.menu_item = item
            result.menu_enabled = True
        return

    # Check for menu in disabled state (color 1)
    bar_text_1 = read_text_at(frame, 2, bar_y, COLOR_HUD_DIM, 20)
    if bar_text_1 and "(" in bar_text_1:
        result.bottom_bar = ChatroomBarState.MENU
        norm = normalize_text(bar_text_1)
        if ")" in norm:
            paren_end = norm.index(")")
            result.menu_category = norm[1:paren_end].strip() if norm.startswith("(") else None
            result.menu_item = norm[paren_end + 1:].strip()
            result.menu_enabled = False
        return

    # Check for target picker: "COLOR:" or "ROLE:" at start in color 8
    bar_text_8 = read_text_at(frame, 2, bar_y, COLOR_HUD_ALERT, 10)
    norm_8 = normalize_text(bar_text_8)
    if norm_8.startswith("COLOR") or norm_8.startswith("ROLE"):
        result.bottom_bar = ChatroomBarState.TARGET_PICKER
        result.target_mode = "COLOR" if norm_8.startswith("COLOR") else "ROLE"
        # Scan for target sprites after the label
        # The label is ~24px wide, sprites start after
        result.target_colors = scan_sprite_row(frame, 30, BAR_Y + 1, PLAYER_W + 3, 4)
        return

    # Default state
    result.bottom_bar = ChatroomBarState.DEFAULT


def _parse_messages(frame: np.ndarray, result: ChatroomPerception) -> None:
    """Best-effort OCR of visible chat messages.

    The bitworld renderer (rendering/renderer.ts) stacks whisper messages
    from the BOTTOM of the message area: with msgArea.y=10, h=108 the
    bottom-most slot's top-y is msgAreaBot - lineH = 111, the next is 104,
    etc. So row top-y values are 111, 104, 97, ..., 13. Iterating from the
    top (y=10, 17, ...) misses every actual message because the rows are
    off by 3 px.

    Most system messages additionally render with a leading sender-sprite
    glyph (sim.ts uses ``pref(pi)`` = "\\x01<pi>" which drawRichText turns
    into a player sprite, advancing cx by PLAYER_W=7 before the text and
    then a 4px space). The actual COLOR_HUD_ALERT text therefore begins at
    x = 2 + PLAYER_W + SPACE_WIDTH = 13 even though drawChatMsg is called
    with x=2. To find the text regardless of how many leading sprites the
    message has, we scan each row for the leftmost column with an alert
    pixel and start the OCR from there.
    """
    msg_top = 10
    msg_bot = BAR_Y - 1  # 118
    line_h = 7

    # Build row top-y values from bottom up to mirror the renderer math
    # (msgAreaBot - n*lineH for n=1, 2, ...), then iterate top-down so
    # messages are appended in chronological order (oldest first).
    rows: list[int] = []
    y = msg_bot - line_h
    while y >= msg_top + 1 and y + GLYPH_H <= msg_bot:
        rows.append(y)
        y -= line_h

    # When a pending entry indicator is shown, the bottom slot at y=111 is
    # the "WANTS IN" indicator (already extracted by _parse_pending_entry),
    # not a chat message. Skip it so we don't double-count.
    if result.has_pending_entry and rows:
        rows = rows[1:]

    for row_y in reversed(rows):
        # System message (alert color). Scan for the first column with an
        # alert pixel inside this row's GLYPH_H span and OCR from there
        # (skips the leading sender sprite, if any).
        sys_text = _read_alert_text_at_row(frame, row_y)
        if sys_text and len(sys_text.strip()) >= 2:
            result.messages.append(ChatMessage(
                sender_color=None,
                sender_shape=None,
                is_system=True,
                text=sys_text.strip(),
                y_position=row_y,
            ))
            continue

        # Player message: sprite at x=2, text at x=10 in sender's color.
        sender_color = read_sprite_color(frame, 2, row_y)
        if sender_color:
            sender_shape = detect_sprite_shape(frame, 2, row_y)
            text_result = read_text_any_color(frame, 10, row_y)
            if text_result:
                result.messages.append(ChatMessage(
                    sender_color=sender_color,
                    sender_shape=sender_shape,
                    is_system=False,
                    text=text_result[0],
                    y_position=row_y,
                ))


def _read_alert_text_at_row(frame: np.ndarray, y: int) -> str:
    """Find the leftmost alert-colored column at row y and OCR from there."""
    if y < 0 or y + GLYPH_H > frame.shape[0]:
        return ""
    row_band = frame[y:y + GLYPH_H, :]
    alert_columns = np.any(row_band == COLOR_HUD_ALERT, axis=0)
    nonzero = np.flatnonzero(alert_columns)
    if nonzero.size == 0:
        return ""
    return read_text_at(frame, int(nonzero[0]), y, COLOR_HUD_ALERT, 30)
