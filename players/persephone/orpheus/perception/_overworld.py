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
    MINIMAP_X,
    OBSERVED_TO_PLAYER_COLORS,
    OUTLINE_COLORS,
    PLAYER_COLORS,
    PLAYER_COLOR_PAIRS,
    PLAYER_H,
    PLAYER_W,
    SCREEN_HEIGHT,
    SCREEN_WIDTH,
    TEAM_A_COLOR,
    TEAM_B_COLOR,
    TOP_BAR_H,
)
from ._hostage_grid import parse_hostage_grid
from ._indicators import parse_role_indicator
from ._minimap import scan_minimap
from ._ocr import normalize_digits, normalize_text, read_text_at, read_text_any_color
from ._position import detect_room, estimate_position
from ._sprites import _RAW_TEMPLATES, detect_sprite_shape
from .types import (
    BottomBarState,
    OverworldBottomBar,
    OverworldPerception,
    Room,
    VisiblePlayer,
    View,
)


def parse_overworld(
    frame: np.ndarray,
    room_size: int = DEFAULT_ROOM_SIZE,
    view: View | None = None,
) -> OverworldPerception:
    """Extract all visible information from an overworld frame.

    Args:
        frame: (128, 128) uint8 pixel array.
        room_size: Room dimensions (for position estimation).
        view: Detected view, when available.

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

    # -- Visible player sprites ----------------------------------------------
    result.visible_players = scan_visible_players(frame)

    # -- Hostage grid ---------------------------------------------------------
    if view == View.HOSTAGE_SELECT:
        result.hostage_grid = parse_hostage_grid(frame)

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
                role_name = text.strip()
                if role_name.endswith("*"):
                    result.is_leader = True
                    role_name = role_name[:-1]
                result.role_name = role_name
                result.role_team_color = color
                return
        if result.role_name:
            break

    # HostageSelect phase label: current renderer draws it at (42, 2).
    # Keep the legacy (2, 2) path for older captured fixtures.
    alert_text = read_text_at(frame, 42, 2, COLOR_HUD_ALERT, 12)
    alert_norm = normalize_text(alert_text)
    if alert_norm.startswith("SELECT"):
        result.is_leader_selecting = True
        _parse_hostage_select_timer(alert_text, result)
        return

    dim_text = read_text_at(frame, 42, 2, COLOR_HUD_DIM, 12)
    dim_norm = normalize_text(dim_text)
    if dim_norm.startswith("SELECT"):
        _parse_hostage_select_timer(dim_text, result)
        return

    if not m:
        alert_text = read_text_at(frame, 2, 2, COLOR_HUD_ALERT, 12)
        if normalize_text(alert_text).startswith("SELECT"):
            result.is_leader_selecting = True
            _parse_hostage_select_timer(alert_text, result)
            return

        # Older non-leader layout: "{LEADER} PICKS {n}S" at (2, 2) in color 1
        dim_text = read_text_at(frame, 2, 2, COLOR_HUD_DIM, 25)
        dim_d = normalize_digits(dim_text)
        picks_match = re.search(r"(\d+)S?$", dim_d.strip())
        if picks_match and "PICK" in normalize_text(dim_text):
            result.hostage_select_secs = int(picks_match.group(1))


def _parse_hostage_select_timer(
    text: str,
    result: OverworldPerception,
) -> None:
    """Extract seconds from a ``SELECT {n}S`` phase label."""
    digits = re.search(r"(\d+)", normalize_digits(text))
    if digits:
        result.hostage_select_secs = int(digits.group(1))


def _parse_bottom_bar(frame: np.ndarray, result: OverworldPerception) -> None:
    """Parse the bottom bar state.

    Current states:
    - WAITING: "WAITING..." in color 8 (pending whisper entry)
    - NOTICE: transient notice text in color 8 (not "WAITING...")
    - DEFAULT: "J:NEW K:JOIN L:SHOUT" in color 1
    """
    # Check for text in color 8 (WAITING or other notice)
    bar_text_8 = read_text_at(frame, 2, BAR_Y + 2, COLOR_HUD_ALERT, 10)
    if normalize_text(bar_text_8).startswith("WAITING"):
        result.bottom_bar = OverworldBottomBar(state=BottomBarState.WAITING)
    elif bar_text_8.strip():
        # Some other notice text in color 8 (e.g. system feedback)
        result.bottom_bar = OverworldBottomBar(
            state=BottomBarState.NOTICE,
            notice_text=normalize_text(bar_text_8),
        )
    else:
        result.bottom_bar = OverworldBottomBar(state=BottomBarState.DEFAULT)

    # Check for unread global chat dot at (124, 123) -- color 11 (green)
    if BAR_Y + 4 < SCREEN_HEIGHT and 124 < SCREEN_WIDTH:
        if frame[BAR_Y + 4, 124] == COLOR_UNREAD_DOT:
            result.bottom_bar.has_unread_global = True


def _parse_shout_strip(frame: np.ndarray, result: OverworldPerception) -> None:
    """Parse the shout strip above the bottom bar (Playing and LeaderSummit phases).

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


def scan_visible_players(frame: np.ndarray) -> list[VisiblePlayer]:
    """Detect ordinary visible player sprites in the overworld viewport."""
    candidates: list[tuple[float, int, int, VisiblePlayer]] = []
    y_stop = min(BAR_Y - PLAYER_H, SCREEN_HEIGHT - PLAYER_H + 1)
    x_stop = min(MINIMAP_X - PLAYER_W, SCREEN_WIDTH - PLAYER_W + 1)

    for y in range(TOP_BAR_H, max(TOP_BAR_H, y_stop)):
        for x in range(0, max(0, x_stop)):
            color, score = _dominant_player_color_and_score(
                frame[y : y + PLAYER_H, x : x + PLAYER_W]
            )
            if color is None or score < 8 or score > 32:
                continue
            shape = detect_sprite_shape(
                frame,
                x,
                y,
                player_color=color,
                outline_is_black=True,
            )
            if shape is None:
                continue
            match_fraction = _sprite_match_fraction(
                frame[y : y + PLAYER_H, x : x + PLAYER_W],
                color,
                shape,
            )
            if match_fraction < 0.85:
                continue
            indicator = parse_role_indicator(frame, x, y + PLAYER_H + 1)
            candidates.append(
                (
                    match_fraction,
                    x,
                    y,
                    VisiblePlayer(
                        screen_x=x,
                        screen_y=y,
                        player_color=color,
                        player_shape=shape,
                        role_indicator=indicator,
                        in_whisper=_has_whisper_indicator(frame, x, y),
                    ),
                )
            )

    selected: list[VisiblePlayer] = []
    occupied: list[tuple[int, int]] = []
    for _score, x, y, player in sorted(candidates, key=lambda item: item[0], reverse=True):
        if any(abs(x - ox) <= PLAYER_W and abs(y - oy) <= PLAYER_H for ox, oy in occupied):
            continue
        occupied.append((x, y))
        selected.append(player)

    selected.sort(key=lambda player: (player.screen_y, player.screen_x))
    return selected


def _has_whisper_indicator(frame: np.ndarray, x: int, y: int) -> bool:
    """Return True when the overworld whisper marker is visible above a sprite."""

    indicator_points = (
        (x - 3, y - 4),
        (x - 2, y - 4),
        (x - 1, y - 4),
        (x - 3, y - 3),
        (x - 2, y - 3),
        (x - 1, y - 3),
        (x, y - 2),
    )
    matches = 0
    for px, py in indicator_points:
        if 0 <= px < SCREEN_WIDTH and 0 <= py < SCREEN_HEIGHT:
            matches += int(frame[py, px] == COLOR_HUD_NORMAL)
    return matches >= 5


def _dominant_player_color_and_score(region: np.ndarray) -> tuple[int | None, int]:
    counts: dict[int, int] = {}
    for observed in region.ravel():
        observed_int = int(observed)
        if observed_int in (0, 1):
            continue
        candidates = OBSERVED_TO_PLAYER_COLORS.get(observed_int)
        if not candidates:
            continue
        for candidate in candidates:
            counts[candidate] = counts.get(candidate, 0) + 1
    if not counts:
        return None, 0
    color = max(
        PLAYER_COLORS,
        key=lambda candidate: (
            counts.get(candidate, 0),
            -PLAYER_COLORS.index(candidate),
        ),
    )
    score = counts.get(color, 0)
    return (color, score) if score > 0 else (None, 0)


def _sprite_match_fraction(
    region: np.ndarray,
    player_color: int,
    shape,
) -> float:
    template = np.array(_RAW_TEMPLATES[shape], dtype=np.uint8)
    fill_mask = template == 2
    outline_mask = template == 1
    total = int(fill_mask.sum() + outline_mask.sum())
    if total == 0 or player_color not in PLAYER_COLOR_PAIRS:
        return 0.0

    normal_fill, shadow_fill = PLAYER_COLOR_PAIRS[player_color]
    fill_ok = (region == normal_fill) | (region == shadow_fill)
    outline_a, outline_b = OUTLINE_COLORS
    outline_ok = (region == outline_a) | (region == outline_b) | (region == 0)
    matches = int((fill_mask & fill_ok).sum() + (outline_mask & outline_ok).sum())
    return matches / total
