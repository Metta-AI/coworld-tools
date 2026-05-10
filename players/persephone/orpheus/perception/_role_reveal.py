"""Role reveal screen parser."""

from __future__ import annotations

import re

import numpy as np

from ._common import (
    COLOR_HUD_DIM,
    COLOR_HUD_NORMAL,
    ECHO_ROLE_NAMES,
    OBSERVED_TO_PLAYER_COLORS,
    PLAYER_COLORS,
    PLAYER_H,
    PLAYER_W,
    ROLE_NAMES,
    ROOM_A_NAME,
    ROOM_B_NAME,
    SCREEN_HEIGHT,
    SCREEN_WIDTH,
    TEAM_A_NAME,
    TEAM_B_NAME,
)
from ._ocr import measure_text, read_text_at
from ._sprites import detect_sprite_shape
from .types import PlayerShape, RoleRevealPerception


_ROLE_NAMES_UPPER = [r.upper() for r in ROLE_NAMES]
_TEAM_NAMES_UPPER = [TEAM_A_NAME.upper(), TEAM_B_NAME.upper()]
_ROOM_NAMES_UPPER = [ROOM_A_NAME.upper(), ROOM_B_NAME.upper()]


def parse_role_reveal(frame: np.ndarray) -> RoleRevealPerception:
    """Extract role, team, room, and game info from the role reveal screen.

    Uses "YOU ARE" as a y-position anchor, then extracts fields at
    known offsets relative to that anchor. This matches the game's
    sequential top-to-bottom text rendering.

    Args:
        frame: (128, 128) uint8 pixel array.

    Returns:
        RoleRevealPerception with all detected fields.
    """
    result = RoleRevealPerception()

    border_color = int(frame[0, 0])

    # Summary/schedule panels have cheap, fixed-position headers. Classify
    # them before role-card OCR so live agents do not burn a full centered-text
    # scan on every non-card intro frame. Team-colored borders only appear on
    # role-card panels, so skip summary/schedule probes there.
    if border_color not in (3, 14):
        if _has_role_summary_header(frame):
            result.panel_index = 2
            (
                result.match_roles,
                result.missing_roles,
                result.echo_substitutions,
            ) = _parse_role_summary(frame)
            if result.match_roles or result.missing_roles or result.echo_substitutions:
                result.spy_in_game_config = "Spy" in result.match_roles
            return result

        if _has_round_schedule_header(frame):
            result.panel_index = 3
            result.round_schedule = _parse_round_schedule(frame)
            return result

    # On the role-card panel the border color is the team color. Other intro
    # panels use ordinary HUD colors, so only assign team fields for real team
    # palette values.
    result.self_color, result.self_shape = _read_self_sprite(frame)

    # Team assignment from border color
    if border_color == 3:
        result.team_color = border_color
        result.team = TEAM_A_NAME
    elif border_color == 14:
        result.team_color = border_color
        result.team = TEAM_B_NAME

    # Find "YOU ARE" anchor to establish base y position.
    # The TS renderer places it at varying y depending on content.
    base_y = _find_anchor(frame)
    if base_y is not None:
        # Role name: baseY + 10, in team color (border_color)
        role_text = _read_centered_role_name(frame, base_y + 10, border_color)
        if role_text is None:
            role_text = _scan_centered(frame, base_y + 10, border_color)
        if role_text:
            result.role = _match_role_name(role_text)

        # Room name: baseY + 32..42, in color 2
        for offset in [38, 36, 34, 40, 42, 32]:
            room_text = _read_centered_room_name(
                frame,
                base_y + offset,
                COLOR_HUD_NORMAL,
            )
            if room_text is None:
                room_text = _scan_centered(frame, base_y + offset, COLOR_HUD_NORMAL)
            if room_text:
                matched = _match_room_name(room_text)
                if matched:
                    result.room = matched
                    break

        # Info line: baseY + 44..52, in color 1: "{n}P  {w}x{h}"
        # The player count and room size may be separated by a gap wider than
        # the OCR's space detection. Scan for each part independently.
        for offset in [48, 46, 44, 50, 52]:
            y = base_y + offset
            if y < 0 or y + 5 > 128:
                continue
            _parse_role_card_info_at(frame, y, result)
            if result.player_count is not None or result.room_size is not None:
                break

        # Countdown: scan lower region for "STARTING IN {n}" in color 2
        for y in (base_y + 88, base_y + 92, base_y + 90, base_y + 94, base_y + 86, base_y + 96):
            if y >= 128:
                break
            countdown_text = _read_centered_countdown(frame, y, COLOR_HUD_NORMAL)
            if countdown_text and "IN" in countdown_text:
                m = re.search(r"(\d+)$", countdown_text.strip())
                if m:
                    result.countdown_secs = int(m.group(1))
                break

    result.panel_index = _classify_panel(frame, base_y)

    return result


def _read_self_sprite(frame: np.ndarray) -> tuple[int | None, PlayerShape | None]:
    """Read the centered own-player sprite from the role card, when present."""
    center_x = (SCREEN_WIDTH - PLAYER_W) // 2
    x_candidates = [
        center_x,
        center_x - 1,
        center_x + 1,
        center_x - 2,
        center_x + 2,
        center_x - 3,
        center_x + 3,
    ]
    for y in (8, 6, 10, 12, 4, 14):
        for x in x_candidates:
            if x < 0 or y < 0 or x + PLAYER_W > 128 or y + PLAYER_H > 128:
                continue
            shape = detect_sprite_shape(frame, x, y, outline_is_black=True)
            if shape is None:
                continue
            color = _dominant_player_color(frame[y : y + PLAYER_H, x : x + PLAYER_W])
            if color is not None:
                return color, shape
    return None, None


def _dominant_player_color(region: np.ndarray) -> int | None:
    """Return the most likely canonical player color in a sprite region."""
    counts: dict[int, int] = {}
    for observed in np.ravel(region):
        observed_int = int(observed)
        if observed_int in (0, 1):
            continue
        candidates = OBSERVED_TO_PLAYER_COLORS.get(observed_int)
        if not candidates:
            continue
        for candidate in candidates:
            counts[candidate] = counts.get(candidate, 0) + 1
    if not counts:
        return None

    # Prefer canonical player colors in normal render order for stable ties.
    return max(
        PLAYER_COLORS,
        key=lambda color: (counts.get(color, 0), -PLAYER_COLORS.index(color)),
    )


def _find_anchor(frame: np.ndarray) -> int | None:
    """Find the y position of the 'YOU ARE' anchor text.

    Tries multiple candidate y values. Returns the y where 'YOU ARE'
    is found in color 2, or None if not found.
    """
    for base_y in [18, 8, 12, 14, 16, 20, 22]:
        text = _read_centered_expected(frame, "YOU ARE", base_y, COLOR_HUD_NORMAL)
        if text and "YOU" in text.upper() and "ARE" in text.upper():
            return base_y
    return None


def _read_centered_role_name(frame: np.ndarray, y: int, color: int) -> str | None:
    return _read_centered_known(frame, y, color, _ROLE_NAMES_UPPER)


def _read_centered_room_name(frame: np.ndarray, y: int, color: int) -> str | None:
    return _read_centered_known(frame, y, color, _ROOM_NAMES_UPPER)


def _read_centered_known(
    frame: np.ndarray,
    y: int,
    color: int,
    expected_values: list[str],
) -> str | None:
    for expected in sorted(expected_values, key=len, reverse=True):
        text = _read_centered_expected(frame, expected, y, color)
        if text and text.upper().replace(" ", "") == expected.replace(" ", ""):
            return text.strip()
    return None


def _parse_role_card_info_at(
    frame: np.ndarray,
    y: int,
    result: RoleRevealPerception,
) -> None:
    # The renderer centers "{n}P  {w}x{h}", but the wide gap between columns
    # can stop OCR early. Read the two tokens independently around their
    # expected starts.
    for x in (36, 40, 32, 44):
        text = read_text_at(frame, x, y, COLOR_HUD_DIM, 4).strip()
        match = re.match(r"(\d+)P$", text)
        if match:
            result.player_count = int(match.group(1))
            break

    for x in (56, 60, 52, 64):
        text = read_text_at(frame, x, y, COLOR_HUD_DIM, 10).strip()
        match = re.match(r"(\d+)[Xx](\d+)", text)
        if match:
            result.room_size = int(match.group(1))
            break


def _read_centered_countdown(frame: np.ndarray, y: int, color: int) -> str | None:
    for x in (36, 34, 38, 40):
        text = read_text_at(frame, x, y, color, 16).strip()
        if text.upper().startswith("STARTING IN"):
            return text
    return None


def _scan_centered(frame: np.ndarray, y: int, color: int) -> str | None:
    """Scan for centered text at a given y position.

    Scans x from 0 to SCREEN_WIDTH in steps of 1 to avoid missing text
    that starts at odd pixel offsets. Requires at least 3 characters to
    filter out noise from stray pixels.
    """
    if y < 0 or y + 5 > 128:
        return None
    for x in range(0, SCREEN_WIDTH - 6):
        text = read_text_at(frame, x, y, color, 20)
        if text and len(text.strip()) >= 3:
            return text.strip()
    return None


def _classify_panel(frame: np.ndarray, role_card_anchor_y: int | None) -> int | None:
    """Classify RoleReveal intro sub-panel from distinctive OCR markers."""
    if role_card_anchor_y is not None:
        return 1
    if _has_round_schedule_header(frame):
        return 3
    if _has_role_summary_header(frame):
        return 2
    return None


def _has_round_schedule_header(frame: np.ndarray) -> bool:
    """Detect Panel 3 by its title or table header."""
    for y in [8, 6, 10, 12]:
        text = _read_centered_expected(
            frame,
            "ROUND SCHEDULE",
            y,
            COLOR_HUD_NORMAL,
        )
        if _contains_all(text, ("ROUND", "SCHEDULE")):
            return True

    for y in [20, 18, 22, 24]:
        text = read_text_at(frame, 10, y, COLOR_HUD_DIM, 24)
        if _contains_all(text, ("ROUND", "TIME", "HOSTAGE")):
            return True
    return False


def _has_role_summary_header(frame: np.ndarray) -> bool:
    """Detect Panel 2 by its MATCH ROLES header."""
    for y in [8, 6, 10, 12]:
        text = _read_centered_expected(frame, "MATCH ROLES", y, COLOR_HUD_NORMAL)
        if _contains_all(text, ("MATCH", "ROLES")):
            return True
    return False


def _read_centered_expected(
    frame: np.ndarray,
    expected: str,
    y: int,
    color: int,
) -> str | None:
    x = (SCREEN_WIDTH - measure_text(expected)) // 2
    for dx in (0, -1, 1, -2, 2):
        text = read_text_at(frame, x + dx, y, color, len(expected) + 2).strip()
        if text:
            return text
    return None


def _parse_role_summary(
    frame: np.ndarray,
) -> tuple[list[str], list[str], list[tuple[str, str]]]:
    """Parse Panel 2 match role membership and echo substitutions.

    The upstream renderer lists unique role names present in the match, then
    optional ``MISSING:`` and ``ECHO ACTIVE:`` sections. It does not render
    exact counts for duplicate grunt roles.
    """
    match_roles: list[str] = []
    missing_roles: list[str] = []
    echo_substitutions: list[tuple[str, str]] = []
    section = "roles"

    for _y, text, _color in _scan_role_summary_rows(frame):
        normalized = text.upper().strip()
        if not normalized:
            continue
        if "MATCH" in normalized and "ROLES" in normalized:
            continue
        if "STARTING" in normalized:
            continue
        if normalized.startswith("MISSING"):
            section = "missing"
            continue
        if "ECHO" in normalized and "ACTIVE" in normalized:
            section = "echo"
            continue

        roles = _extract_role_names(text)
        if not roles:
            continue
        if section == "roles":
            _extend_unique(match_roles, roles)
        elif section == "missing":
            _extend_unique(missing_roles, roles)
        else:
            if len(roles) >= 2:
                echo_substitutions.append((roles[0], roles[1]))

    return match_roles, missing_roles, echo_substitutions


def _scan_role_summary_rows(frame: np.ndarray) -> list[tuple[int, str, int]]:
    rows: list[tuple[int, str, int]] = []
    # Renderer draws role-summary content left-aligned at x=6, beginning just
    # below the centered header. Avoid full-frame x scans here: this runs every
    # intro frame in live play.
    colors = (COLOR_HUD_DIM, COLOR_HUD_NORMAL, 8, 11)
    for y in _left_text_baselines(frame, 20, SCREEN_HEIGHT - 10, colors):
        candidates: list[tuple[int, int, str]] = []
        for color in colors:
            text = read_text_at(frame, 6, y, color, 32).strip()
            if len(text) >= 3:
                candidates.append((6, color, text))
        if not candidates:
            continue

        x, color, text = max(candidates, key=lambda item: (len(item[2]), -item[0]))
        if rows and y - rows[-1][0] < 5 and rows[-1][1] == text:
            continue
        rows.append((y, text, color))
    return rows


def _left_text_baselines(
    frame: np.ndarray,
    start_y: int,
    end_y: int,
    colors: tuple[int, ...],
) -> list[int]:
    """Return likely text baselines for left-aligned intro text."""
    if start_y >= end_y:
        return []

    region = frame[start_y:end_y, 6 : SCREEN_WIDTH - 6]
    mask = np.isin(region, np.array(colors, dtype=frame.dtype))
    raw_ys = np.flatnonzero(mask.any(axis=1)) + start_y
    if raw_ys.size == 0:
        return []

    baselines: list[int] = []
    run_start = int(raw_ys[0])
    previous = run_start
    for raw_y in raw_ys[1:]:
        y = int(raw_y)
        if y - previous > 2:
            baselines.append(run_start)
            run_start = y
        previous = y
    baselines.append(run_start)
    return baselines


_ROLE_SUMMARY_ALIASES: tuple[tuple[str, str], ...] = tuple(
    sorted(
        [
            *[(name.upper(), name) for name in ECHO_ROLE_NAMES],
            *[(name.upper(), name) for name in ROLE_NAMES],
            ("SHADES", "Shade"),
            ("NYMPHS", "Nymph"),
            ("ECHO HADES", "Echo of Hades"),
            ("ECHO PERSEPHONE", "Echo of Persephone"),
            ("ECHO CERBERUS", "Echo of Cerberus"),
            ("ECHO DEMETER", "Echo of Demeter"),
        ],
        key=lambda item: len(item[0]),
        reverse=True,
    )
)


def _extract_role_names(text: str) -> list[str]:
    roles: list[str] = []
    normalized = text.upper()
    i = 0
    while i < len(normalized):
        for needle, role_name in _ROLE_SUMMARY_ALIASES:
            if normalized.startswith(needle, i):
                roles.append(role_name)
                i += len(needle)
                break
        else:
            i += 1
    return roles


def _extend_unique(target: list[str], values: list[str]) -> None:
    for value in values:
        if value not in target:
            target.append(value)


def _parse_round_schedule(frame: np.ndarray) -> list[tuple[int, int]]:
    """Parse Panel 3 round rows as ``(duration_secs, hostage_count)``."""
    rows: dict[int, tuple[int, int]] = {}
    for y in range(28, 68, 8):
        parsed = _parse_schedule_columns(frame, y)
        if parsed is not None:
            round_number, duration_secs, hostage_count = parsed
            rows.setdefault(round_number, (duration_secs, hostage_count))
    return [rows[key] for key in sorted(rows)]


def _parse_schedule_columns(frame: np.ndarray, y: int) -> tuple[int, int, int] | None:
    round_text = _scan_schedule_token(frame, y, (14, 18, 12, 16), max_chars=3)
    time_text = _scan_schedule_token(frame, y, (42, 46, 40, 44), max_chars=8)
    hostage_text = _scan_schedule_token(frame, y, (78, 82, 76, 80), max_chars=3)
    if round_text is None or time_text is None or hostage_text is None:
        return None

    round_text = _normalize_schedule_digits(round_text)
    time_text = _normalize_schedule_digits(time_text)
    hostage_text = _normalize_schedule_digits(hostage_text)
    if not round_text.isdigit() or not hostage_text.isdigit():
        return None
    duration = _parse_duration_secs(time_text)
    if duration is None:
        return None
    return int(round_text), duration, int(hostage_text)


def _scan_schedule_token(
    frame: np.ndarray,
    y: int,
    x_values: tuple[int, ...],
    *,
    max_chars: int,
) -> str | None:
    for color in (COLOR_HUD_NORMAL, COLOR_HUD_DIM):
        for x in x_values:
            text = read_text_at(frame, x, y, color, max_chars).strip()
            if not text:
                continue
            normalized = _normalize_schedule_digits(text)
            if normalized[0].isdigit():
                return normalized.split()[0]
    return None


def _parse_schedule_row(text: str | None) -> tuple[int, int, int] | None:
    if not text:
        return None
    normalized = _normalize_schedule_digits(text)
    match = re.search(
        r"\b(?P<round>\d+)\s+"
        r"(?P<time>\d+(?::\d{1,2})?)\s*"
        r"(?:S|SEC|SECS|SECONDS)?\s+"
        r"(?P<hostages>\d+)\b",
        normalized,
    )
    if match is None:
        return None

    duration = _parse_duration_secs(match.group("time"))
    if duration is None:
        return None
    return (
        int(match.group("round")),
        duration,
        int(match.group("hostages")),
    )


def _parse_duration_secs(value: str) -> int | None:
    if ":" not in value:
        return int(value) if value.isdigit() else None
    minutes_text, seconds_text = value.split(":", 1)
    if not minutes_text or not seconds_text:
        return None
    if not minutes_text.isdigit() or not seconds_text.isdigit():
        return None
    return int(minutes_text) * 60 + int(seconds_text)


def _normalize_schedule_digits(text: str) -> str:
    return text.upper().replace("O", "0").replace("I", "1").strip()


def _contains_all(text: str | None, needles: tuple[str, ...]) -> bool:
    if not text:
        return False
    norm = text.upper()
    return all(needle in norm for needle in needles)


def _match_role_name(text: str) -> str | None:
    """Match OCR'd text against known role names."""
    norm = text.upper().replace(" ", "")
    for i, upper in enumerate(_ROLE_NAMES_UPPER):
        if norm.startswith(upper.replace(" ", "")):
            return ROLE_NAMES[i]
    return text  # Return raw if no match (better than None)


def _match_room_name(text: str) -> str | None:
    """Match OCR'd text against known room names."""
    norm = text.upper().replace(" ", "")
    if "UNDERWORLD" in norm:
        return ROOM_A_NAME
    if "MORTAL" in norm:
        return ROOM_B_NAME
    return None
