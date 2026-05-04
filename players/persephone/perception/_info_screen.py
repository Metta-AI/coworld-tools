"""Info screen parser."""

from __future__ import annotations

import numpy as np

from ._common import (
    COLOR_HUD_DIM,
    COLOR_HUD_NORMAL,
    PLAYER_H,
    PLAYER_W,
    ROLE_NAMES,
    SCREEN_HEIGHT,
    SCREEN_WIDTH,
    TEAM_A_COLOR,
    TEAM_B_COLOR,
)
from ._indicators import parse_role_indicator
from ._ocr import normalize_text, read_text_any_color, read_text_at
from ._sprites import read_sprite_color
from .types import InfoMode, InfoScreenPerception, KnownPlayer


_INFO_HEADER_Y = 2
_INFO_ROW_START_Y = 12
_INFO_ROW_H = 11
_INFO_SPRITE_X = 4
_INFO_TEXT_X = 15
_INFO_MAX_ROWS = (SCREEN_HEIGHT - 22) // _INFO_ROW_H


def parse_info_screen(frame: np.ndarray) -> InfoScreenPerception:
    """Extract info screen data.

    Args:
        frame: (128, 128) uint8 pixel array.

    Returns:
        InfoScreenPerception with mode and content.
    """
    result = InfoScreenPerception()

    # Detect mode: "KNOWN PLAYERS" header = shared mode, "YOU ARE" = role mode
    header_text = read_text_at(frame, 2, _INFO_HEADER_Y, COLOR_HUD_NORMAL, 15)
    header_norm = normalize_text(header_text)

    if "KNOWN" in header_norm:
        result.mode = InfoMode.SHARED
        _parse_shared_mode(frame, result)
    else:
        # Check for role mode (has team-color border + "YOU ARE")
        result.mode = InfoMode.ROLE
        _parse_role_mode(frame, result)

    return result


def _parse_role_mode(frame: np.ndarray, result: InfoScreenPerception) -> None:
    """Parse the 'role' info screen sub-mode."""
    border_color = int(frame[0, 0])
    result.team_color = border_color

    if border_color == TEAM_A_COLOR:
        result.team_name = "Shades"
    elif border_color == TEAM_B_COLOR:
        result.team_name = "Nymphs"

    # Role name at y=30 in border color (centered)
    for x in range(0, SCREEN_WIDTH - 10, 2):
        text = read_text_at(frame, x, 30, border_color, 12)
        if text and len(text.strip()) >= 3:
            result.role_name = _match_role(text.strip())
            break


def _parse_shared_mode(frame: np.ndarray, result: InfoScreenPerception) -> None:
    """Parse the 'shared' info screen (known players list)."""
    for row in range(_INFO_MAX_ROWS):
        y = _INFO_ROW_START_Y + row * _INFO_ROW_H

        # Read sprite color at (4, y)
        color = read_sprite_color(frame, _INFO_SPRITE_X, y)
        if color is None:
            break  # No more entries

        # Read role text at (15, y+2)
        text_result = read_text_any_color(frame, _INFO_TEXT_X, y + 2)

        role_name = None
        team_color = None
        color_only = False

        if text_result:
            text, text_c = text_result
            text_norm = normalize_text(text).strip()
            if text_norm == "???":
                color_only = True
                # Read team color from the dot at (sprite_x+3, y+PLAYER_H+1)
                dot_y = y + PLAYER_H + 1
                dot_x = _INFO_SPRITE_X + 3
                if dot_y < SCREEN_HEIGHT and dot_x < SCREEN_WIDTH:
                    dot_c = int(frame[dot_y, dot_x])
                    if dot_c in (TEAM_A_COLOR, TEAM_B_COLOR):
                        team_color = dot_c
            else:
                role_name = _match_role(text_norm)
                team_color = text_c  # Text color is the team color

        result.known_players.append(KnownPlayer(
            color=color,
            role_name=role_name,
            team_color=team_color,
            is_self=(row == 0),
            color_only=color_only,
        ))


def _match_role(text: str) -> str | None:
    """Match OCR'd text against known role names."""
    upper = normalize_text(text).upper().replace(" ", "")
    for name in ROLE_NAMES:
        if upper.startswith(name.upper()):
            return name
    return text  # Return raw if no exact match
