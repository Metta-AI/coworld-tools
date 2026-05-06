"""Shared constants for the perception module.

All values derived from the upstream game source:
- game/constants.ts
- rendering/renderer.ts
- rendering/framebuffer.ts
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Screen geometry
# ---------------------------------------------------------------------------

SCREEN_WIDTH = 128
SCREEN_HEIGHT = 128
PROTOCOL_BYTES = (SCREEN_WIDTH * SCREEN_HEIGHT) // 2  # 8192

BOTTOM_BAR_H = 9
BAR_Y = SCREEN_HEIGHT - BOTTOM_BAR_H  # 119

TOP_BAR_H = 9

# ---------------------------------------------------------------------------
# Minimap
# ---------------------------------------------------------------------------

MINIMAP_SIZE = 20
MINIMAP_X = SCREEN_WIDTH - MINIMAP_SIZE - 2  # 106
MINIMAP_Y = 2

# ---------------------------------------------------------------------------
# Player geometry
# ---------------------------------------------------------------------------

PLAYER_W = 7
PLAYER_H = 7

# ---------------------------------------------------------------------------
# Team colors
# ---------------------------------------------------------------------------

TEAM_A_COLOR = 3  # Shades
TEAM_B_COLOR = 14  # Nymphs

TEAM_A_NAME = "Shades"
TEAM_B_NAME = "Nymphs"

# ---------------------------------------------------------------------------
# Room colors
# ---------------------------------------------------------------------------

ROOM_A_FLOOR = 12  # Underworld base floor
ROOM_A_ALT = 6  # Underworld grid dot color
ROOM_B_FLOOR = 9  # Mortal Realm base floor
ROOM_B_ALT = 10  # Mortal Realm grid dot color

ROOM_A_NAME = "Underworld"
ROOM_B_NAME = "Mortal Realm"

# ---------------------------------------------------------------------------
# Player colors (8, assigned by player_index % 8)
# ---------------------------------------------------------------------------

PLAYER_COLORS = [3, 14, 8, 10, 7, 9, 11, 12]

COLOR_NAMES = {
    3: "RED",
    14: "BLUE",
    8: "YELLOW",
    10: "GREEN",
    7: "ORANGE",
    9: "PURPLE",
    11: "LIME",
    12: "NAVY",
}

# ---------------------------------------------------------------------------
# UI colors
# ---------------------------------------------------------------------------

COLOR_BLACK = 0
COLOR_HUD_NORMAL = 2  # Round/timer, headers
COLOR_HUD_DIM = 1  # Hints, control labels
COLOR_HUD_ALERT = 8  # System messages, timers, offers
COLOR_SELF_DOT = 2  # Self on minimap
COLOR_UNREAD_DOT = 11  # Green dot for unread global
COLOR_WALL = 5
COLOR_BUBBLE = 2  # Speech bubble color
COLOR_HOSTAGE_CHECK = 11  # Green checkmark on selected hostages

# ---------------------------------------------------------------------------
# Floor grid
# ---------------------------------------------------------------------------

FLOOR_DOT_GRID = 24  # Spacing of the floor reference dots
FLOOR_DOT_OFFSET = 11  # First dot at this offset within each grid cell

# ---------------------------------------------------------------------------
# Role names (for OCR matching)
# ---------------------------------------------------------------------------

ROLE_NAMES = ["Hades", "Persephone", "Cerberus", "Demeter", "Shade", "Nymph"]

# ---------------------------------------------------------------------------
# Minimap exclusion sets
# ---------------------------------------------------------------------------

# Colors that are NOT player dots on the minimap
MINIMAP_EXCLUDE_BASE = frozenset([0, 1, 5])  # black, border, obstacle
# Room-specific: also exclude the room's base floor color
MINIMAP_EXCLUDE_ROOM_A = MINIMAP_EXCLUDE_BASE | {ROOM_A_FLOOR}
MINIMAP_EXCLUDE_ROOM_B = MINIMAP_EXCLUDE_BASE | {ROOM_B_FLOOR}

# ---------------------------------------------------------------------------
# Shadow map (fog of war color remapping)
# ---------------------------------------------------------------------------

SHADOW_MAP = [0, 12, 9, 5, 5, 0, 5, 5, 5, 12, 9, 9, 0, 12, 12, 9]

# ---------------------------------------------------------------------------
# Shape detection
# ---------------------------------------------------------------------------

# Minimum fraction of non-transparent template pixels that must match for a
# shape classification to succeed. Tune this value to trade off between false
# negatives (too high — rejects partially occluded sprites) and false
# positives (too low — misclassifies noise). 0.70 handles typical fog-of-war
# partial occlusion while rejecting random pixel patterns.
SHAPE_MATCH_THRESHOLD = 0.70

# For each player color, the (normal, shadow) pair used for fill-pixel
# matching. A fill pixel matches if it equals EITHER value in the pair.
PLAYER_COLOR_PAIRS: dict[int, tuple[int, int]] = {
    c: (c, SHADOW_MAP[c]) for c in PLAYER_COLORS
}

# Outline pixels match if they are either the normal outline color (1) or
# the shadow-mapped outline color (SHADOW_MAP[1] = 12).
OUTLINE_COLORS: tuple[int, int] = (1, SHADOW_MAP[1])

# Reverse lookup: observed color → canonical player color. Maps both normal
# and shadow-mapped colors back to the original player color. When a shadow
# color is shared by multiple players (e.g., 5 maps to RED, YELLOW, ORANGE),
# returns a frozenset of candidates.
_SHADOW_TO_PLAYERS: dict[int, list[int]] = {}
for _c in PLAYER_COLORS:
    _s = SHADOW_MAP[_c]
    if _s != 0:  # Ignore shadow=0 (invisible in shadow)
        _SHADOW_TO_PLAYERS.setdefault(_s, []).append(_c)

OBSERVED_TO_PLAYER_COLORS: dict[int, frozenset[int]] = {}
# Normal colors map to themselves (unambiguous)
for _c in PLAYER_COLORS:
    OBSERVED_TO_PLAYER_COLORS[_c] = frozenset([_c])
# Shadow colors may map to multiple candidates
for _s, _candidates in _SHADOW_TO_PLAYERS.items():
    if _s not in OBSERVED_TO_PLAYER_COLORS:
        OBSERVED_TO_PLAYER_COLORS[_s] = frozenset(_candidates)
    else:
        # Shadow color is also a normal player color — merge
        OBSERVED_TO_PLAYER_COLORS[_s] = frozenset(
            [_s] + _candidates if _s not in _candidates else _candidates
        )

# Cleanup module-level temporaries
del _c, _s, _candidates, _SHADOW_TO_PLAYERS

# ---------------------------------------------------------------------------
# Default room size (used when room_size is unknown)
# ---------------------------------------------------------------------------

DEFAULT_ROOM_SIZE = 100  # Smallest room (6-8 players)
