"""Hostage exchange screen parser."""

from __future__ import annotations

import numpy as np

from ._common import (
    BAR_Y,
    COLOR_HUD_ALERT,
    COLOR_HUD_DIM,
    COLOR_HUD_NORMAL,
    COLOR_HOSTAGE_CHECK,
    PLAYER_H,
    SCREEN_HEIGHT,
)
from ._indicators import parse_role_indicator
from ._ocr import normalize_text, read_text_at
from ._sprites import detect_sprite_shape, read_sprite_color
from .types import ExchangePerception, ExchangePlayer


def parse_exchange(frame: np.ndarray) -> ExchangePerception:
    """Extract hostage exchange information.

    Args:
        frame: (128, 128) uint8 pixel array.

    Returns:
        ExchangePerception with leaders, departing, arriving, and status.
    """
    result = ExchangePerception()

    # -- Viewer status from bottom bar at (2, 121) ----------------------------
    bar_text_8 = read_text_at(frame, 2, BAR_Y + 2, COLOR_HUD_ALERT, 25)
    bar_text_2 = read_text_at(frame, 2, BAR_Y + 2, COLOR_HUD_NORMAL, 25)
    bar_text_1 = read_text_at(frame, 2, BAR_Y + 2, COLOR_HUD_DIM, 25)

    bar_8_norm = normalize_text(bar_text_8)
    bar_2_norm = normalize_text(bar_text_2)
    bar_1_norm = normalize_text(bar_text_1)

    if "EXCHANGED" in bar_8_norm.upper():
        result.viewer_status = "hostage"
    elif "ESCORTING" in bar_2_norm.upper():
        result.viewer_status = "leader"
    elif "EXCHANGING" in bar_1_norm.upper():
        result.viewer_status = "spectator"

    # -- Scan for player rows -------------------------------------------------
    # Content starts around y=26. Labels identify sections.
    # We scan for sprites at x=10, spaced 14px apart vertically.
    section = "leaders"

    for y in range(26, BAR_Y - 14, 7):
        # Check for section labels
        label_8 = normalize_text(read_text_at(frame, 8, y, COLOR_HUD_ALERT, 12))
        label_2 = normalize_text(read_text_at(frame, 8, y, COLOR_HUD_NORMAL, 12))
        label_11 = normalize_text(read_text_at(frame, 8, y, COLOR_HOSTAGE_CHECK, 12))

        if "DEPARTING" in label_8.upper():
            section = "departing"
            continue
        if "ARRIVING" in label_11.upper():
            section = "arriving"
            continue
        if "LEADER" in label_2.upper():
            section = "leaders"
            continue

        # Check for sprite at x=10
        color = read_sprite_color(frame, 10, y)
        if color is None:
            continue

        # Classify sprite shape for full player identification
        shape = detect_sprite_shape(frame, 10, y)

        # Parse role indicator below sprite
        indicator = parse_role_indicator(frame, 10, y + PLAYER_H + 1)
        player = ExchangePlayer(color=color, shape=shape, role_indicator=indicator)

        if section == "leaders":
            result.leaders.append(player)
        elif section == "departing":
            result.departing.append(player)
        elif section == "arriving":
            result.arriving.append(player)

    return result
