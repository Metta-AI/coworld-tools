"""Overworld view parser (Playing / HostageSelect phases)."""

from __future__ import annotations

import re

import numpy as np

from ._bubbles import scan_speech_bubbles
from ._common import (
    BAR_Y,
    BOTTOM_BAR_H,
    COLOR_HUD_ALERT,
    COLOR_HUD_DIM,
    COLOR_HUD_NORMAL,
    COLOR_UNREAD_DOT,
    DEFAULT_ROOM_SIZE,
    MINIMAP_SIZE,
    SCREEN_HEIGHT,
    SCREEN_WIDTH,
    TEAM_A_COLOR,
    TEAM_B_COLOR,
)
from ._minimap import scan_minimap
from ._ocr import normalize_digits, normalize_text, read_text_at, read_text_any_color
from ._position import detect_room, estimate_position
from .types import (
    BottomBarState,
    OverworldBottomBar,
    OverworldPerception,
    Room,
)


def parse_overworld(
    frame: np.ndarray,
    room_size: int = DEFAULT_ROOM_SIZE,
) -> OverworldPerception:
    """Extract all visible information from an overworld frame.

    Args:
        frame: (128, 128) uint8 pixel array.
        room_size: Room dimensions (for position estimation).

    Returns:
        OverworldPerception with all detected fields.
    """
    result = OverworldPerception()

    # -- Room detection -------------------------------------------------------
    room = detect_room(frame)
    result.room = room

    # -- Position estimation --------------------------------------------------
    pos = estimate_position(frame, room, room_size)
    result.self_position = pos

    # -- Minimap scanning -----------------------------------------------------
    result.minimap_dots = scan_minimap(frame, room, room_size)

    # -- HUD: Top bar ---------------------------------------------------------
    _parse_top_bar(frame, result)

    # -- HUD: Bottom bar ------------------------------------------------------
    _parse_bottom_bar(frame, result)

    # -- Shout strip (Playing phase only) -------------------------------------
    _parse_shout_strip(frame, result)

    # -- Speech bubbles -------------------------------------------------------
    result.speech_bubbles = scan_speech_bubbles(frame)

    return result


def _parse_top_bar(frame: np.ndarray, result: OverworldPerception) -> None:
    """Parse the top bar HUD (round, timer, role name, hostage select)."""
    # Playing: "R{round} M:SS" at (2, 2) in color 2
    hud_text = read_text_at(frame, 2, 2, COLOR_HUD_NORMAL, 15)
    hud_d = normalize_digits(hud_text)

    m = re.match(r"R(\d+)\s+(\d+):(\d+)", hud_d)
    if m:
        result.round = int(m.group(1))
        result.timer_secs = int(m.group(2)) * 60 + int(m.group(3))

    # Role name: right-aligned before minimap, in team color (3 or 14)
    # Scan from right to left for text in either team color
    minimap_left = SCREEN_WIDTH - MINIMAP_SIZE - 4
    for color in [TEAM_A_COLOR, TEAM_B_COLOR]:
        for x in range(max(0, minimap_left - 44), minimap_left):
            text = read_text_at(frame, x, 2, color, 12)
            if text and len(text.strip()) >= 3:
                result.role_name = text.strip()
                result.role_team_color = color
                return
        if result.role_name:
            break

    # HostageSelect: "SELECT {n}S" at (2, 2) in color 8
    if not m:
        alert_text = read_text_at(frame, 2, 2, COLOR_HUD_ALERT, 12)
        alert_norm = normalize_text(alert_text)
        alert_d = normalize_digits(alert_text)
        if alert_norm.startswith("SELECT"):
            result.is_leader_selecting = True
            digits = re.search(r"(\d+)", alert_d[6:])
            if digits:
                result.hostage_select_secs = int(digits.group(1))
        # Non-leader: "{LEADER} PICKS {n}S" at (2, 2) in color 1
        else:
            dim_text = read_text_at(frame, 2, 2, COLOR_HUD_DIM, 25)
            dim_d = normalize_digits(dim_text)
            picks_match = re.search(r"(\d+)S?$", dim_d.strip())
            if picks_match and "PICK" in normalize_text(dim_text):
                result.hostage_select_secs = int(picks_match.group(1))


def _parse_bottom_bar(frame: np.ndarray, result: OverworldPerception) -> None:
    """Parse the bottom bar state."""
    # Check for WAITING (chatroom entry pending) in color 8
    bar_text_8 = read_text_at(frame, 2, BAR_Y + 2, COLOR_HUD_ALERT, 10)
    if normalize_text(bar_text_8).startswith("WAITING"):
        result.bottom_bar = OverworldBottomBar(state=BottomBarState.WAITING)
    else:
        # Check for comm menu: "< ITEM >" in color 2
        bar_text_2 = read_text_at(frame, 2, BAR_Y + 2, COLOR_HUD_NORMAL, 15)
        if bar_text_2.startswith("<"):
            # Extract item name between < and >
            item = bar_text_2.strip("<> ").strip()
            result.bottom_bar = OverworldBottomBar(
                state=BottomBarState.COMM_MENU,
                comm_menu_item=normalize_text(item) if item else None,
            )
        else:
            result.bottom_bar = OverworldBottomBar(state=BottomBarState.DEFAULT)

    # Check for unread global chat dot at (124, 123) -- color 11 (green)
    if BAR_Y + 4 < SCREEN_HEIGHT and 124 < SCREEN_WIDTH:
        if frame[BAR_Y + 4, 124] == COLOR_UNREAD_DOT:
            result.bottom_bar.has_unread_global = True


def _parse_shout_strip(frame: np.ndarray, result: OverworldPerception) -> None:
    """Parse the shout strip above the bottom bar (Playing phase only).

    The strip is at y=112 (BAR_Y - 7). Has a 3-pixel red marker at x=0,
    then text at x=2 in the sender's player color.
    """
    strip_y = BAR_Y - 7  # 112

    # Check for the red marker at x=0
    has_marker = False
    for y in range(strip_y, min(strip_y + 3, SCREEN_HEIGHT)):
        if frame[y, 0] == COLOR_HUD_ALERT:
            has_marker = True
            break

    if not has_marker:
        return

    # Read text at x=2 in whatever color is present
    text_result = read_text_any_color(frame, 2, strip_y)
    if text_result:
        result.last_shout = text_result[0]
        result.last_shout_color = text_result[1]
