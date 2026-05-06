"""Sprite utilities: color reading, shape detection, and shadow-aware matching.

The game renders player sprites as 7x7 pixel grids with three pixel types:
  0 = transparent (background shows through)
  1 = outline (always palette index 1 in normal light, 12 in shadow)
  2 = fill (player's assigned palette color, or its SHADOW_MAP value in fog)

Shape detection works by matching observed pixel patterns against the 12
known player sprite templates. Matching is shadow-aware: each fill/outline
pixel is tested against BOTH its normal and shadow-mapped color, handling
fully lit, fully shadowed, and partially shadowed sprites uniformly.
"""

from __future__ import annotations

import numpy as np

from ._common import (
    OBSERVED_TO_PLAYER_COLORS,
    OUTLINE_COLORS,
    PLAYER_COLOR_PAIRS,
    PLAYER_COLORS,
    PLAYER_H,
    PLAYER_W,
    SCREEN_HEIGHT,
    SCREEN_WIDTH,
    SHADOW_MAP,
    SHAPE_MATCH_THRESHOLD,
)
from .types import PlayerShape


# ---------------------------------------------------------------------------
# Template data (ported from bitworld/common/sprites.ts)
#
# Each template is a 7x7 list-of-lists: 0=transparent, 1=outline, 2=fill.
# Order matches PlayerShape enum values (0-11).
# ---------------------------------------------------------------------------

_RAW_TEMPLATES: dict[PlayerShape, list[list[int]]] = {
    PlayerShape.CIRCLE: [
        [0, 0, 1, 1, 1, 0, 0],
        [0, 1, 2, 2, 2, 1, 0],
        [1, 2, 2, 2, 2, 2, 1],
        [1, 2, 2, 2, 2, 2, 1],
        [1, 2, 2, 2, 2, 2, 1],
        [0, 1, 2, 2, 2, 1, 0],
        [0, 0, 1, 1, 1, 0, 0],
    ],
    PlayerShape.SQUARE: [
        [0, 1, 1, 1, 1, 1, 0],
        [1, 2, 2, 2, 2, 2, 1],
        [1, 2, 2, 2, 2, 2, 1],
        [1, 2, 2, 2, 2, 2, 1],
        [1, 2, 2, 2, 2, 2, 1],
        [1, 2, 2, 2, 2, 2, 1],
        [0, 1, 1, 1, 1, 1, 0],
    ],
    PlayerShape.TRIANGLE: [
        [0, 0, 0, 1, 0, 0, 0],
        [0, 0, 1, 2, 1, 0, 0],
        [0, 0, 1, 2, 1, 0, 0],
        [0, 1, 2, 2, 2, 1, 0],
        [0, 1, 2, 2, 2, 1, 0],
        [1, 2, 2, 2, 2, 2, 1],
        [1, 1, 1, 1, 1, 1, 1],
    ],
    PlayerShape.DIAMOND: [
        [0, 0, 0, 1, 0, 0, 0],
        [0, 0, 1, 2, 1, 0, 0],
        [0, 1, 2, 2, 2, 1, 0],
        [1, 2, 2, 2, 2, 2, 1],
        [0, 1, 2, 2, 2, 1, 0],
        [0, 0, 1, 2, 1, 0, 0],
        [0, 0, 0, 1, 0, 0, 0],
    ],
    PlayerShape.STAR: [
        [0, 0, 0, 1, 0, 0, 0],
        [0, 1, 1, 2, 1, 1, 0],
        [1, 2, 2, 2, 2, 2, 1],
        [0, 1, 2, 2, 2, 1, 0],
        [1, 2, 2, 2, 2, 2, 1],
        [0, 1, 1, 2, 1, 1, 0],
        [0, 0, 0, 1, 0, 0, 0],
    ],
    PlayerShape.CROSS: [
        [0, 0, 1, 1, 1, 0, 0],
        [0, 0, 1, 2, 1, 0, 0],
        [1, 1, 1, 2, 1, 1, 1],
        [1, 2, 2, 2, 2, 2, 1],
        [1, 1, 1, 2, 1, 1, 1],
        [0, 0, 1, 2, 1, 0, 0],
        [0, 0, 1, 1, 1, 0, 0],
    ],
    PlayerShape.X_SHAPE: [
        [1, 1, 0, 0, 0, 1, 1],
        [1, 2, 1, 0, 1, 2, 1],
        [0, 1, 2, 1, 2, 1, 0],
        [0, 0, 1, 2, 1, 0, 0],
        [0, 1, 2, 1, 2, 1, 0],
        [1, 2, 1, 0, 1, 2, 1],
        [1, 1, 0, 0, 0, 1, 1],
    ],
    PlayerShape.HEART: [
        [0, 0, 0, 0, 0, 0, 0],
        [0, 1, 1, 0, 1, 1, 0],
        [1, 2, 2, 1, 2, 2, 1],
        [1, 2, 2, 2, 2, 2, 1],
        [0, 1, 2, 2, 2, 1, 0],
        [0, 0, 1, 2, 1, 0, 0],
        [0, 0, 0, 1, 0, 0, 0],
    ],
    PlayerShape.CRESCENT: [
        [0, 0, 1, 1, 1, 0, 0],
        [0, 1, 2, 2, 1, 0, 0],
        [1, 2, 2, 1, 0, 0, 0],
        [1, 2, 2, 1, 0, 0, 0],
        [1, 2, 2, 1, 0, 0, 0],
        [0, 1, 2, 2, 1, 0, 0],
        [0, 0, 1, 1, 1, 0, 0],
    ],
    PlayerShape.BOLT: [
        [0, 0, 0, 1, 1, 0, 0],
        [0, 0, 1, 2, 1, 0, 0],
        [0, 1, 2, 2, 1, 0, 0],
        [1, 2, 2, 2, 2, 1, 0],
        [0, 0, 1, 2, 2, 1, 0],
        [0, 0, 1, 2, 1, 0, 0],
        [0, 0, 1, 1, 0, 0, 0],
    ],
    PlayerShape.HOURGLASS: [
        [1, 1, 1, 1, 1, 1, 1],
        [0, 1, 2, 2, 2, 1, 0],
        [0, 0, 1, 2, 1, 0, 0],
        [0, 0, 1, 2, 1, 0, 0],
        [0, 0, 1, 2, 1, 0, 0],
        [0, 1, 2, 2, 2, 1, 0],
        [1, 1, 1, 1, 1, 1, 1],
    ],
    PlayerShape.RING: [
        [0, 0, 1, 1, 1, 0, 0],
        [0, 1, 2, 2, 2, 1, 0],
        [1, 2, 2, 1, 2, 2, 1],
        [1, 2, 1, 0, 1, 2, 1],
        [1, 2, 2, 1, 2, 2, 1],
        [0, 1, 2, 2, 2, 1, 0],
        [0, 0, 1, 1, 1, 0, 0],
    ],
}

# ---------------------------------------------------------------------------
# Precomputed masks (built once at import time)
#
# _TEMPLATE_ARRAYS: (12, 7, 7) uint8 — raw template values
# _FILL_MASKS: (12, 7, 7) bool — True where template == 2
# _OUTLINE_MASKS: (12, 7, 7) bool — True where template == 1
# _NON_TRANSPARENT_COUNTS: (12,) int — total fill + outline pixels per shape
# _SHAPE_ORDER: list of PlayerShape in array index order
# ---------------------------------------------------------------------------

_SHAPE_ORDER: list[PlayerShape] = sorted(
    _RAW_TEMPLATES.keys(), key=lambda s: s.value
)

_TEMPLATE_ARRAYS = np.array(
    [_RAW_TEMPLATES[s] for s in _SHAPE_ORDER], dtype=np.uint8
)  # (12, 7, 7)

_FILL_MASKS = _TEMPLATE_ARRAYS == 2  # (12, 7, 7)
_OUTLINE_MASKS = _TEMPLATE_ARRAYS == 1  # (12, 7, 7)
_NON_TRANSPARENT_COUNTS = _FILL_MASKS.sum(axis=(1, 2)) + _OUTLINE_MASKS.sum(
    axis=(1, 2)
)  # (12,)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def read_sprite_color(frame: np.ndarray, x: int, y: int) -> int | None:
    """Read the fill color of a 7x7 sprite at (x, y) from its center pixel.

    Reads the center pixel (x+3, y+3) which is a fill pixel for 10 of the
    12 player shapes. CRESCENT has outline at center, RING has transparent
    at center — for these shapes, this function returns None even when a
    sprite is present. Use detect_sprite_shape() for robust detection of
    all 12 shapes.

    Returns None if out of bounds, black (0), or outline (1).

    Note: this returns the RAW observed color. In fog-of-war the color
    may be shadow-mapped. Use resolve_player_color() to map it back to
    the canonical player color.
    """
    cx = x + PLAYER_W // 2  # x + 3
    cy = y + PLAYER_H // 2  # y + 3
    if cx < 0 or cy < 0 or cx >= SCREEN_WIDTH or cy >= SCREEN_HEIGHT:
        return None
    c = int(frame[cy, cx])
    if c == 0 or c == 1:  # Black or dark border
        return None
    return c


def resolve_player_color(observed: int) -> frozenset[int] | None:
    """Map an observed pixel color to candidate canonical player color(s).

    Args:
        observed: A palette index read from a sprite's fill region.

    Returns:
        A frozenset of possible canonical player colors. Unambiguous when
        the observed color is a normal player color (returns a singleton).
        Ambiguous when it's a shadow color shared by multiple players
        (e.g., shadow color 5 → {RED, YELLOW, ORANGE}).
        Returns None if the color is not recognizable as any player
        (normal or shadowed).
    """
    return OBSERVED_TO_PLAYER_COLORS.get(observed)


def detect_sprite_shape(
    frame: np.ndarray,
    x: int,
    y: int,
    player_color: int | None = None,
    threshold: float = SHAPE_MATCH_THRESHOLD,
) -> PlayerShape | None:
    """Classify the shape of a 7x7 player sprite at screen position (x, y).

    Matching is shadow-aware: fill pixels are accepted if they match EITHER
    the normal player color OR its SHADOW_MAP counterpart. Outline pixels
    are accepted as either 1 (normal) or 12 (shadowed). This handles fully
    lit, fully shadowed, and partially shadowed sprites uniformly.

    Args:
        frame: (128, 128) uint8 pixel array.
        x: Left edge of the sprite (screen x coordinate).
        y: Top edge of the sprite (screen y coordinate).
        player_color: Expected canonical player color. If None, inferred
            from the center pixel (may be ambiguous in fog).
        threshold: Minimum fraction of non-transparent template pixels
            that must match. Defaults to SHAPE_MATCH_THRESHOLD from
            _common.py. Pass a higher value (e.g. 0.90) when you know the
            sprite is unoccluded for stricter matching.

    Returns:
        The detected PlayerShape, or None if no template scores above
        the threshold (partial sprite, off-screen, not a player sprite).
    """
    # Bounds check
    if x < 0 or y < 0 or x + PLAYER_W > SCREEN_WIDTH or y + PLAYER_H > SCREEN_HEIGHT:
        return None

    region = frame[y : y + PLAYER_H, x : x + PLAYER_W]  # (7, 7)

    # Determine the player color (and its shadow variant) for fill matching
    if player_color is None:
        # Collect all candidate player colors from the observed pixels in the
        # region. We union all resolved candidates from every unique non-
        # background color present.
        candidates = _resolve_region_candidates(region)
        if not candidates:
            return None
        return _best_match_multi(region, candidates, threshold)

    # Single known color — direct match
    if player_color not in PLAYER_COLOR_PAIRS:
        return None
    return _best_match(region, player_color, threshold)


def read_sprite(
    frame: np.ndarray, x: int, y: int
) -> tuple[int | None, PlayerShape | None]:
    """Read both color and shape from a sprite at (x, y).

    Convenience function that combines read_sprite_color and
    detect_sprite_shape in a single call, avoiding redundant pixel reads.

    Returns:
        (player_color, player_shape) where either may be None.
        player_color is the raw observed color (use resolve_player_color()
        to map to canonical).
    """
    color = read_sprite_color(frame, x, y)
    if color is None:
        return (None, None)
    # Use the observed color for shape detection — detect_sprite_shape
    # handles shadow resolution internally when player_color is not provided
    shape = detect_sprite_shape(frame, x, y)
    return (color, shape)


def scan_sprite_row(
    frame: np.ndarray,
    start_x: int,
    y: int,
    stride: int,
    max_slots: int = 12,
) -> list[int]:
    """Scan a horizontal row of sprites and return their colors.

    Used for chatroom occupant sprites, hostage grid, etc.

    Args:
        frame: (128, 128) pixel array.
        start_x: X position of the first sprite.
        y: Y position of all sprites.
        stride: Pixel distance between sprite starts.
        max_slots: Maximum sprites to check.

    Returns:
        List of player colors, stopping at the first empty slot.
    """
    colors: list[int] = []
    for slot in range(max_slots):
        sx = start_x + slot * stride
        if sx + PLAYER_W > SCREEN_WIDTH:
            break
        c = read_sprite_color(frame, sx, y)
        if c is None:
            break  # First empty slot = end of occupants
        colors.append(c)
    return colors


def scan_sprite_row_with_shapes(
    frame: np.ndarray,
    start_x: int,
    y: int,
    stride: int,
    max_slots: int = 12,
) -> list[tuple[int, PlayerShape | None]]:
    """Scan a horizontal row of sprites, returning (color, shape) pairs.

    Like scan_sprite_row, but also classifies the shape of each sprite.
    Stops at the first empty slot.

    Args:
        frame: (128, 128) pixel array.
        start_x: X position of the first sprite.
        y: Y position of all sprites.
        stride: Pixel distance between sprite starts.
        max_slots: Maximum sprites to check.

    Returns:
        List of (color, shape) tuples. Shape may be None if classification
        fails for a given slot.
    """
    results: list[tuple[int, PlayerShape | None]] = []
    for slot in range(max_slots):
        sx = start_x + slot * stride
        if sx + PLAYER_W > SCREEN_WIDTH:
            break
        c = read_sprite_color(frame, sx, y)
        if c is None:
            break
        shape = detect_sprite_shape(frame, sx, y)
        results.append((c, shape))
    return results


# ---------------------------------------------------------------------------
# Internal matching helpers
# ---------------------------------------------------------------------------


def _best_match(
    region: np.ndarray,
    player_color: int,
    threshold: float,
) -> PlayerShape | None:
    """Find the best-matching shape for a single known player color.

    Tests all 12 templates against the region, scoring each by the fraction
    of non-transparent pixels that match (fill = normal or shadow color,
    outline = 1 or 12).

    Special case: when shadow_fill == shadow_outline (e.g. BLUE/PURPLE both
    shadow to 12), fill matching only uses the normal color. In full shadow,
    fill and outline are indistinguishable by color and shape detection
    honestly returns None rather than guessing.
    """
    normal_c, shadow_c = PLAYER_COLOR_PAIRS[player_color]
    outline_a, outline_b = OUTLINE_COLORS

    # When shadow_fill == shadow_outline, using shadow_c for fill would
    # match outline pixels too — making all shapes score equally. Only
    # match fill against normal color in this degenerate case. Similarly,
    # outline can only match normal outline (1), since 12 is ambiguous.
    if shadow_c == outline_b:
        fill_ok = region == normal_c
        outline_ok = region == outline_a  # Only normal outline (1)
    else:
        fill_ok = (region == normal_c) | (region == shadow_c)
        outline_ok = (region == outline_a) | (region == outline_b)

    # Score each template: count matching pixels at expected positions
    fill_scores = (_FILL_MASKS & fill_ok).sum(axis=(1, 2))  # (12,)
    outline_scores = (_OUTLINE_MASKS & outline_ok).sum(axis=(1, 2))  # (12,)
    total_scores = fill_scores + outline_scores  # (12,)

    # Normalize by non-transparent pixel count per template
    with np.errstate(divide="ignore", invalid="ignore"):
        fractions = total_scores / _NON_TRANSPARENT_COUNTS  # (12,)

    best_idx = int(np.argmax(fractions))
    if fractions[best_idx] >= threshold:
        return _SHAPE_ORDER[best_idx]
    return None


def _best_match_multi(
    region: np.ndarray,
    candidates: frozenset[int],
    threshold: float,
) -> PlayerShape | None:
    """Find the best-matching shape across multiple candidate player colors.

    Used when the center pixel is a shadow color that maps to multiple
    possible players. Tests each candidate and returns the overall best.
    """
    best_shape: PlayerShape | None = None
    best_score: float = 0.0

    outline_a, outline_b = OUTLINE_COLORS

    for candidate_color in candidates:
        if candidate_color not in PLAYER_COLOR_PAIRS:
            continue
        normal_c, shadow_c = PLAYER_COLOR_PAIRS[candidate_color]

        # Skip shadow colors when they collide with shadow outline
        if shadow_c == outline_b:
            fill_ok = region == normal_c
            outline_ok = region == outline_a
        else:
            fill_ok = (region == normal_c) | (region == shadow_c)
            outline_ok = (region == outline_a) | (region == outline_b)

        fill_scores = (_FILL_MASKS & fill_ok).sum(axis=(1, 2))
        outline_scores = (_OUTLINE_MASKS & outline_ok).sum(axis=(1, 2))
        total_scores = fill_scores + outline_scores

        with np.errstate(divide="ignore", invalid="ignore"):
            fractions = total_scores / _NON_TRANSPARENT_COUNTS

        idx = int(np.argmax(fractions))
        if fractions[idx] > best_score:
            best_score = fractions[idx]
            best_shape = _SHAPE_ORDER[idx]

    if best_score >= threshold:
        return best_shape
    return None


def _find_dominant_color(region: np.ndarray) -> int | None:
    """Find the most common non-background color in a 7x7 region.

    Used as fallback when center pixel is not a fill pixel (CRESCENT and
    RING have outline/transparent at center). Ignores colors 0 (black/
    transparent) and 1 (outline).

    Returns the most frequent qualifying color, or None if the region
    contains only background/outline colors.
    """
    flat = region.ravel()
    # Mask out 0 and 1
    mask = (flat != 0) & (flat != 1)
    candidates = flat[mask]
    if candidates.size == 0:
        return None
    # Find mode (most common value)
    counts = np.bincount(candidates, minlength=16)
    best = int(np.argmax(counts))
    if counts[best] == 0:
        return None
    return best


def _resolve_region_candidates(region: np.ndarray) -> frozenset[int]:
    """Find all plausible canonical player colors from a sprite region.

    Scans the 7x7 region for all unique non-0, non-1 colors, resolves each
    through OBSERVED_TO_PLAYER_COLORS, and returns the union of all
    candidates. This handles CRESCENT/RING (center pixel is not fill) and
    shadow scenarios (where fill and outline may both map to non-obvious
    values).
    """
    flat = region.ravel()
    unique = set(int(v) for v in np.unique(flat) if v > 1)
    if not unique:
        return frozenset()

    all_candidates: set[int] = set()
    for observed in unique:
        resolved = OBSERVED_TO_PLAYER_COLORS.get(observed)
        if resolved:
            all_candidates.update(resolved)
    return frozenset(all_candidates)
