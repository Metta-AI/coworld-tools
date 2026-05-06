"""Role indicator parsing: read the 5x2 bar below player sprites."""

from __future__ import annotations

import numpy as np

from ._common import (
    COLOR_HUD_ALERT,
    COLOR_HUD_NORMAL,
    SCREEN_HEIGHT,
    SCREEN_WIDTH,
    TEAM_A_COLOR,
    TEAM_B_COLOR,
)
from .types import RoleIndicator


def parse_role_indicator(frame: np.ndarray, x: int, y: int) -> RoleIndicator | None:
    """Parse a role indicator bar at position (x, y).

    The indicator is a 5x2 pixel bar at (x+1, y) in team color, with
    optional special dots that identify the specific role.

    Args:
        frame: (128, 128) pixel array.
        x: X position of the parent sprite (indicator is at x+1).
        y: Y position of the indicator bar (sprite_y + PLAYER_H + 1).

    Returns:
        RoleIndicator with team and role, or None if no indicator found.
    """
    # The bar starts at (x+1, y) and is 5 wide, 2 tall.
    bx = x + 1
    if bx < 0 or bx + 5 > SCREEN_WIDTH or y < 0 or y + 2 > SCREEN_HEIGHT:
        return None

    # Read the bar's base color (should be TEAM_A_COLOR or TEAM_B_COLOR)
    # Sample multiple pixels to determine the base fill color.
    bar_region = frame[y:y + 2, bx:bx + 5]

    # Count team color pixels
    a_count = int(np.sum(bar_region == TEAM_A_COLOR))
    b_count = int(np.sum(bar_region == TEAM_B_COLOR))

    if a_count < 3 and b_count < 3:
        return None  # Not a valid indicator

    if a_count >= b_count:
        team = "shades"
        team_color = TEAM_A_COLOR
    else:
        team = "nymphs"
        team_color = TEAM_B_COLOR

    # Determine role from special dot patterns.
    # Dot positions are relative to bx:
    #   Center: (bx+2, y) and (bx+2, y+1)
    #   Split:  (bx+1, y) and (bx+3, y)
    # Dot colors: 8 (alert/yellow) for Shades key roles,
    #             2 (normal/white) for Nymphs key roles.

    dot_color = COLOR_HUD_ALERT if team == "shades" else COLOR_HUD_NORMAL

    center_top = int(frame[y, bx + 2])
    center_bot = int(frame[y + 1, bx + 2])
    split_left = int(frame[y, bx + 1])
    split_right = int(frame[y, bx + 3])

    has_center = (center_top == dot_color and center_bot == dot_color)
    has_split = (split_left == dot_color and split_right == dot_color)

    if has_center:
        role = "hades" if team == "shades" else "persephone"
    elif has_split:
        role = "cerberus" if team == "shades" else "demeter"
    else:
        role = "shade" if team == "shades" else "nymph"

    return RoleIndicator(team=team, role=role)
