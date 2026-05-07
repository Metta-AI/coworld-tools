"""Unit tests for sprite shape detection."""

from __future__ import annotations

import numpy as np
import pytest

from orpheus.perception._common import (
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
from orpheus.perception._sprites import (
    _RAW_TEMPLATES,
    _SHAPE_ORDER,
    detect_sprite_shape,
    read_sprite,
    read_sprite_color,
    resolve_player_color,
    scan_sprite_row_with_shapes,
)
from orpheus.perception.types import PlayerShape


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _render_sprite(
    shape: PlayerShape,
    player_color: int,
    x: int = 10,
    y: int = 10,
    shadow: bool = False,
) -> np.ndarray:
    """Render a single sprite into a 128x128 black frame.

    Args:
        shape: Which shape to render.
        player_color: Canonical player color (pre-shadow).
        x, y: Top-left position.
        shadow: If True, render using shadow-mapped colors.

    Returns:
        (128, 128) uint8 frame with the sprite rendered.
    """
    frame = np.zeros((SCREEN_HEIGHT, SCREEN_WIDTH), dtype=np.uint8)
    template = _RAW_TEMPLATES[shape]

    fill_c = SHADOW_MAP[player_color] if shadow else player_color
    outline_c = SHADOW_MAP[1] if shadow else 1

    for dy in range(PLAYER_H):
        for dx in range(PLAYER_W):
            val = template[dy][dx]
            if val == 2:
                frame[y + dy, x + dx] = fill_c
            elif val == 1:
                frame[y + dy, x + dx] = outline_c
            # val == 0 → transparent (leave as 0)

    return frame


def _render_partial_shadow_sprite(
    shape: PlayerShape,
    player_color: int,
    x: int = 10,
    y: int = 10,
    shadow_cols: int = 4,
) -> np.ndarray:
    """Render a sprite where the left portion is shadowed, right is normal.

    Simulates a fog boundary cutting through the sprite at column shadow_cols.
    """
    frame = np.zeros((SCREEN_HEIGHT, SCREEN_WIDTH), dtype=np.uint8)
    template = _RAW_TEMPLATES[shape]

    for dy in range(PLAYER_H):
        for dx in range(PLAYER_W):
            val = template[dy][dx]
            in_shadow = dx < shadow_cols
            if val == 2:
                fill_c = SHADOW_MAP[player_color] if in_shadow else player_color
                frame[y + dy, x + dx] = fill_c
            elif val == 1:
                outline_c = SHADOW_MAP[1] if in_shadow else 1
                frame[y + dy, x + dx] = outline_c

    return frame


# ---------------------------------------------------------------------------
# Tests: detect_sprite_shape — all 12 shapes, normal light
# ---------------------------------------------------------------------------


class TestDetectShapeNormal:
    """Test shape detection for all 12 shapes in normal (unfogged) light."""

    @pytest.mark.parametrize("shape", list(PlayerShape))
    def test_detects_each_shape(self, shape: PlayerShape) -> None:
        """Each shape renders and classifies correctly."""
        color = 3  # RED
        frame = _render_sprite(shape, color, x=20, y=30)
        result = detect_sprite_shape(frame, 20, 30, player_color=color)
        assert result == shape, f"Expected {shape.name}, got {result}"

    @pytest.mark.parametrize("shape", list(PlayerShape))
    def test_detects_without_explicit_color(self, shape: PlayerShape) -> None:
        """Shape detection works when player_color is not provided."""
        color = 14  # BLUE
        frame = _render_sprite(shape, color, x=50, y=50)
        result = detect_sprite_shape(frame, 50, 50)
        assert result == shape

    @pytest.mark.parametrize("color", PLAYER_COLORS)
    def test_detects_with_all_player_colors(self, color: int) -> None:
        """Shape detection works across all 8 player colors."""
        shape = PlayerShape.STAR
        frame = _render_sprite(shape, color, x=10, y=10)
        result = detect_sprite_shape(frame, 10, 10)
        assert result == shape

    def test_returns_none_for_empty_region(self) -> None:
        """Returns None when the region is all black."""
        frame = np.zeros((SCREEN_HEIGHT, SCREEN_WIDTH), dtype=np.uint8)
        result = detect_sprite_shape(frame, 50, 50)
        assert result is None

    def test_returns_none_out_of_bounds(self) -> None:
        """Returns None when sprite would exceed screen bounds."""
        frame = np.zeros((SCREEN_HEIGHT, SCREEN_WIDTH), dtype=np.uint8)
        # Sprite at x=125 would need x+7=132 > 128
        assert detect_sprite_shape(frame, 125, 50) is None
        assert detect_sprite_shape(frame, 50, 125) is None
        assert detect_sprite_shape(frame, -1, 50) is None
        assert detect_sprite_shape(frame, 50, -1) is None

    def test_distinguishes_similar_shapes(self) -> None:
        """Circle vs Ring: both round, but ring has hollow center."""
        color = 10  # GREEN
        # Circle
        frame_circle = _render_sprite(PlayerShape.CIRCLE, color)
        assert detect_sprite_shape(frame_circle, 10, 10) == PlayerShape.CIRCLE
        # Ring
        frame_ring = _render_sprite(PlayerShape.RING, color)
        assert detect_sprite_shape(frame_ring, 10, 10) == PlayerShape.RING


# ---------------------------------------------------------------------------
# Tests: shadow-aware detection
# ---------------------------------------------------------------------------


class TestDetectShapeShadow:
    """Test shape detection in fogged/shadowed conditions."""

    @pytest.mark.parametrize("shape", list(PlayerShape))
    def test_fully_shadowed(self, shape: PlayerShape) -> None:
        """All 12 shapes classify correctly when fully shadowed."""
        color = 3  # RED → shadow 5
        frame = _render_sprite(shape, color, shadow=True)
        # Without providing player_color, it infers from center pixel
        result = detect_sprite_shape(frame, 10, 10)
        assert result == shape

    @pytest.mark.parametrize("shape", list(PlayerShape))
    def test_fully_shadowed_with_explicit_color(self, shape: PlayerShape) -> None:
        """Shadowed sprite matches when we provide the canonical color.

        Exception: BLUE(14) and PURPLE(9) shadow to 12, which is also the
        shadow outline color. In full shadow, fill and outline are visually
        identical for these colors, making shape detection impossible.
        This is the correct/honest result — the information is genuinely lost.
        """
        color = 14  # BLUE → shadow 12 (collides with shadow outline)
        frame = _render_sprite(shape, color, shadow=True)
        result = detect_sprite_shape(frame, 10, 10, player_color=color)
        # BLUE in full shadow: fill=12, outline=12 → indistinguishable
        assert result is None, (
            f"Expected None for fully-shadowed BLUE (shadow collision), "
            f"got {result}"
        )

    @pytest.mark.parametrize("shape", list(PlayerShape))
    def test_fully_shadowed_non_colliding_color(self, shape: PlayerShape) -> None:
        """Shadowed sprite matches for colors where shadow != outline shadow.

        YELLOW(8) → shadow 5. Since 5 != 12 (outline shadow), the fill
        and outline are still distinguishable in full shadow.
        """
        color = 8  # YELLOW → shadow 5 (no collision with outline shadow 12)
        frame = _render_sprite(shape, color, shadow=True)
        result = detect_sprite_shape(frame, 10, 10, player_color=color)
        assert result == shape, f"Expected {shape.name}, got {result}"

    @pytest.mark.parametrize("shape", list(PlayerShape))
    def test_partial_shadow(self, shape: PlayerShape) -> None:
        """Sprite with left half shadowed, right half normal still matches."""
        color = 8  # YELLOW → shadow 5
        frame = _render_partial_shadow_sprite(shape, color, shadow_cols=4)
        result = detect_sprite_shape(frame, 10, 10, player_color=color)
        assert result == shape

    def test_shadow_color_collision_resolved(self) -> None:
        """When shadow color matches another player color, shape disambiguates.

        RED(3), YELLOW(8), ORANGE(7) all shadow to 5. But a shadowed RED circle
        vs shadowed YELLOW triangle are distinguishable by shape pattern.
        """
        # Shadowed RED circle
        frame_red = _render_sprite(PlayerShape.CIRCLE, 3, shadow=True)
        # Shadowed YELLOW triangle
        frame_yellow = _render_sprite(PlayerShape.TRIANGLE, 8, shadow=True)

        # Both have fill color 5, but different structural patterns
        result_red = detect_sprite_shape(frame_red, 10, 10)
        result_yellow = detect_sprite_shape(frame_yellow, 10, 10)

        assert result_red == PlayerShape.CIRCLE
        assert result_yellow == PlayerShape.TRIANGLE


# ---------------------------------------------------------------------------
# Tests: threshold behavior
# ---------------------------------------------------------------------------


class TestThreshold:
    """Test threshold tuning behavior."""

    def test_perfect_match_scores_one(self) -> None:
        """A perfectly rendered sprite scores 1.0 and matches any threshold."""
        frame = _render_sprite(PlayerShape.DIAMOND, 3)
        # Even at threshold 0.99, it should match
        result = detect_sprite_shape(frame, 10, 10, player_color=3, threshold=0.99)
        assert result == PlayerShape.DIAMOND

    def test_corrupted_below_threshold_returns_none(self) -> None:
        """A heavily corrupted sprite below threshold returns None."""
        frame = _render_sprite(PlayerShape.STAR, 3)
        # Corrupt most fill pixels to random colors
        template = _RAW_TEMPLATES[PlayerShape.STAR]
        corrupted = 0
        for dy in range(PLAYER_H):
            for dx in range(PLAYER_W):
                if template[dy][dx] == 2:
                    frame[10 + dy, 10 + dx] = 7  # Wrong color
                    corrupted += 1
                    if corrupted >= 10:  # Corrupt enough to fail
                        break
            if corrupted >= 10:
                break
        # With very high threshold, this should fail
        result = detect_sprite_shape(frame, 10, 10, player_color=3, threshold=0.95)
        assert result is None

    def test_threshold_is_configurable(self) -> None:
        """Lower threshold accepts weaker matches."""
        frame = _render_sprite(PlayerShape.CROSS, 3)
        # Corrupt a couple of fill pixels
        template = _RAW_TEMPLATES[PlayerShape.CROSS]
        corrupted = 0
        for dy in range(PLAYER_H):
            for dx in range(PLAYER_W):
                if template[dy][dx] == 2 and corrupted < 3:
                    frame[10 + dy, 10 + dx] = 0  # Black out
                    corrupted += 1
        # Still matches at default threshold (only 3 of ~15 fill pixels lost)
        result = detect_sprite_shape(frame, 10, 10, player_color=3)
        assert result == PlayerShape.CROSS

    def test_default_threshold_value(self) -> None:
        """The default threshold is 0.70."""
        assert SHAPE_MATCH_THRESHOLD == 0.70


# ---------------------------------------------------------------------------
# Tests: resolve_player_color
# ---------------------------------------------------------------------------


class TestResolvePlayerColor:
    """Test the shadow → canonical color reverse lookup."""

    def test_normal_colors_resolve_to_self(self) -> None:
        """Each player color maps to itself (singleton frozenset)."""
        for color in PLAYER_COLORS:
            result = resolve_player_color(color)
            assert result is not None
            assert color in result

    def test_shadow_colors_resolve(self) -> None:
        """Shadow colors map back to their source player color(s)."""
        # RED(3) shadows to 5
        result = resolve_player_color(5)
        assert result is not None
        assert 3 in result  # RED
        assert 8 in result  # YELLOW also shadows to 5
        assert 7 in result  # ORANGE also shadows to 5

    def test_non_player_color_returns_none(self) -> None:
        """Colors that are neither player nor shadow return None."""
        # Color 2 is HUD normal, not a player or shadow color
        result = resolve_player_color(2)
        assert result is None

    def test_color_0_returns_none(self) -> None:
        """Black (0) is not a player color."""
        assert resolve_player_color(0) is None


# ---------------------------------------------------------------------------
# Tests: read_sprite_color
# ---------------------------------------------------------------------------


class TestReadSpriteColor:
    """Test basic center-pixel color reading."""

    def test_reads_center_pixel(self) -> None:
        """Returns the color at the center of the sprite region."""
        frame = _render_sprite(PlayerShape.CIRCLE, 14, x=20, y=30)
        result = read_sprite_color(frame, 20, 30)
        assert result == 14

    def test_shadowed_returns_shadow_color(self) -> None:
        """In fog, returns the raw shadow color (not canonical)."""
        frame = _render_sprite(PlayerShape.CIRCLE, 14, shadow=True)
        # BLUE(14) → shadow 12
        result = read_sprite_color(frame, 10, 10)
        assert result == 12  # Raw shadow color

    def test_returns_none_for_empty(self) -> None:
        """Returns None when center pixel is black."""
        frame = np.zeros((SCREEN_HEIGHT, SCREEN_WIDTH), dtype=np.uint8)
        assert read_sprite_color(frame, 50, 50) is None

    def test_returns_none_out_of_bounds(self) -> None:
        """Returns None for positions that would overflow the screen."""
        frame = np.zeros((SCREEN_HEIGHT, SCREEN_WIDTH), dtype=np.uint8)
        assert read_sprite_color(frame, 126, 50) is None  # cx=129 > 128
        assert read_sprite_color(frame, 50, 126) is None


# ---------------------------------------------------------------------------
# Tests: read_sprite (combined color + shape)
# ---------------------------------------------------------------------------


class TestReadSprite:
    """Test the combined color + shape reader."""

    def test_returns_both(self) -> None:
        """Returns (color, shape) tuple for a valid sprite."""
        frame = _render_sprite(PlayerShape.HEART, 10, x=40, y=40)
        color, shape = read_sprite(frame, 40, 40)
        assert color == 10
        assert shape == PlayerShape.HEART

    def test_empty_returns_none_none(self) -> None:
        """Returns (None, None) for empty region."""
        frame = np.zeros((SCREEN_HEIGHT, SCREEN_WIDTH), dtype=np.uint8)
        color, shape = read_sprite(frame, 50, 50)
        assert color is None
        assert shape is None


# ---------------------------------------------------------------------------
# Tests: scan_sprite_row_with_shapes
# ---------------------------------------------------------------------------


class TestScanSpriteRowWithShapes:
    """Test row scanning with shape classification."""

    def test_scans_multiple_sprites(self) -> None:
        """Detects color and shape for a row of sprites."""
        frame = np.zeros((SCREEN_HEIGHT, SCREEN_WIDTH), dtype=np.uint8)
        # Render 3 sprites in a row with stride=9
        sprites = [
            (PlayerShape.CIRCLE, 3),
            (PlayerShape.TRIANGLE, 14),
            (PlayerShape.STAR, 8),
        ]
        for i, (shape, color) in enumerate(sprites):
            x = 10 + i * 9
            template = _RAW_TEMPLATES[shape]
            for dy in range(PLAYER_H):
                for dx in range(PLAYER_W):
                    val = template[dy][dx]
                    if val == 2:
                        frame[20 + dy, x + dx] = color
                    elif val == 1:
                        frame[20 + dy, x + dx] = 1

        result = scan_sprite_row_with_shapes(frame, 10, 20, 9, max_slots=5)
        assert len(result) == 3
        assert result[0] == (3, PlayerShape.CIRCLE)
        assert result[1] == (14, PlayerShape.TRIANGLE)
        assert result[2] == (8, PlayerShape.STAR)

    def test_stops_at_empty_slot(self) -> None:
        """Stops scanning when no sprite is detected at a slot."""
        frame = np.zeros((SCREEN_HEIGHT, SCREEN_WIDTH), dtype=np.uint8)
        # Only one sprite
        template = _RAW_TEMPLATES[PlayerShape.SQUARE]
        for dy in range(PLAYER_H):
            for dx in range(PLAYER_W):
                val = template[dy][dx]
                if val == 2:
                    frame[20 + dy, 10 + dx] = 3
                elif val == 1:
                    frame[20 + dy, 10 + dx] = 1

        result = scan_sprite_row_with_shapes(frame, 10, 20, 9, max_slots=5)
        assert len(result) == 1
        assert result[0] == (3, PlayerShape.SQUARE)


# ---------------------------------------------------------------------------
# Tests: PLAYER_COLOR_PAIRS consistency
# ---------------------------------------------------------------------------


class TestColorPairs:
    """Verify the precomputed color pair mappings."""

    def test_all_player_colors_have_pairs(self) -> None:
        """Every player color has a (normal, shadow) pair."""
        for color in PLAYER_COLORS:
            assert color in PLAYER_COLOR_PAIRS
            normal, shadow = PLAYER_COLOR_PAIRS[color]
            assert normal == color
            assert shadow == SHADOW_MAP[color]

    def test_outline_colors(self) -> None:
        """Outline colors are (1, SHADOW_MAP[1])."""
        assert OUTLINE_COLORS == (1, 12)
