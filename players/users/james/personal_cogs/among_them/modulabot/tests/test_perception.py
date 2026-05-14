"""Perception-layer smoke tests.

These exercise the new pixel-perception modules (``data``, ``geometry``,
``frame``, ``sprite_match``, ``actors``) against synthetic frames. They
do NOT currently test against captured real-game frames — that's the
next step; see :mod:`modulabot.tests.test_perception_snapshots`.

The goal here is to catch integration regressions (bad palette loads,
missing fields on sub-records, wrong sprite sheet slice) quickly.
"""

from __future__ import annotations

import unittest

import numpy as np

from modulabot.actors import update_role, scan_radar_dots
from modulabot.data import (
    PLAYER_COLORS,
    PLAYER_COLOR_COUNT,
    SCREEN_HEIGHT,
    SCREEN_WIDTH,
    SHADOW_MAP,
    TINT_COLOR,
    TRANSPARENT_INDEX,
    load_reference_data,
)
from modulabot.frame import (
    KILL_ICON_X,
    KILL_ICON_Y,
    PLAYER_IGNORE_RADIUS,
    RADAR_TASK_COLOR,
    ignore_frame_pixel,
    looks_like_interstitial,
    sprite_covers,
    unpack4bpp,
)
from modulabot.geometry import (
    PLAYER_SCREEN_X,
    PLAYER_SCREEN_Y,
    PLAYER_WORLD_OFF_X,
    PLAYER_WORLD_OFF_Y,
    button_camera_x,
    button_camera_y,
    camera_index,
    camera_index_x,
    camera_index_y,
    heuristic,
)
from modulabot.sprite_match import (
    matches_sprite,
    player_body_color,
    player_color_index,
    stable_crewmate_color,
)
from modulabot.state import Bot, Role


class DataLoadTests(unittest.TestCase):
    def test_load_reference_data(self):
        d = load_reference_data()
        self.assertEqual(d.map.width, 952)
        self.assertEqual(d.map.height, 534)
        self.assertEqual(len(d.map.tasks), 40)
        self.assertGreaterEqual(len(d.map.rooms), 0)
        self.assertEqual(d.map.map_pixels.shape, (534, 952))
        self.assertEqual(d.map.walk_mask.shape, (534, 952))
        self.assertEqual(d.map.wall_mask.shape, (534, 952))

    def test_player_sprite_has_tint_pixels(self):
        """Player sprite body should include TINT_COLOR pixels.

        This is the regression test for the 'wrong palette' bug caught
        during the data-layer port: the bitworld palette is not standard
        PICO-8; TINT_COLOR = 3 = red in that palette.
        """
        d = load_reference_data()
        pixels = d.sprites.player.pixels
        self.assertIn(TINT_COLOR, pixels.flatten().tolist())
        # And should contain the shade tint too.
        self.assertIn(9, pixels.flatten().tolist())

    def test_palette_mapping_stable(self):
        """PLAYER_COLORS and SHADOW_MAP sanity."""
        self.assertEqual(len(PLAYER_COLORS), PLAYER_COLOR_COUNT)
        self.assertEqual(len(SHADOW_MAP), 16)
        # Every player colour should have an entry in the shadow map.
        for color in PLAYER_COLORS:
            self.assertLess(int(SHADOW_MAP[int(color)]), 16)


class GeometryTests(unittest.TestCase):
    def test_player_offsets_non_negative(self):
        self.assertGreater(PLAYER_SCREEN_X, 0)
        self.assertGreater(PLAYER_SCREEN_Y, 0)
        self.assertGreater(PLAYER_WORLD_OFF_X, 0)
        self.assertGreater(PLAYER_WORLD_OFF_Y, 0)

    def test_camera_index_roundtrip(self):
        for x in (-50, 0, 100, 500, 900):
            for y in (-50, 0, 100, 300, 500):
                idx = camera_index(x, y)
                self.assertEqual(camera_index_x(idx), x)
                self.assertEqual(camera_index_y(idx), y)

    def test_button_camera_stays_in_bounds(self):
        d = load_reference_data()
        bcx = button_camera_x(d.map)
        bcy = button_camera_y(d.map)
        self.assertLessEqual(bcx, 952)
        self.assertLessEqual(bcy, 534)

    def test_heuristic_symmetric(self):
        self.assertEqual(heuristic(0, 0, 3, 4), heuristic(3, 4, 0, 0))
        self.assertEqual(heuristic(0, 0, 3, 4), 7)


class FrameTests(unittest.TestCase):
    def test_unpack4bpp(self):
        packed = np.array([0xAB, 0xCD], dtype=np.uint8)
        # Need 8192 bytes to reshape — pad with zeros.
        padded = np.zeros(8192, dtype=np.uint8)
        padded[:2] = packed
        frame = unpack4bpp(padded)
        self.assertEqual(frame.shape, (128, 128))
        # First two bytes unpacked: 0xAB → [B, A], 0xCD → [D, C]
        self.assertEqual(int(frame[0, 0]), 0xB)
        self.assertEqual(int(frame[0, 1]), 0xA)
        self.assertEqual(int(frame[0, 2]), 0xD)
        self.assertEqual(int(frame[0, 3]), 0xC)

    def test_looks_like_interstitial(self):
        # All-black frame → interstitial
        self.assertTrue(looks_like_interstitial(np.zeros((128, 128), dtype=np.uint8)))
        # Non-black frame → not interstitial
        self.assertFalse(looks_like_interstitial(np.full((128, 128), 5, dtype=np.uint8)))

    def test_sprite_covers(self):
        d = load_reference_data()
        sprite = d.sprites.player
        # Centre of the sprite should be covered.
        self.assertTrue(sprite_covers(sprite, 0, 0, sprite.width // 2, sprite.height // 2))
        # Off the sprite should not be covered.
        self.assertFalse(sprite_covers(sprite, 0, 0, -1, -1))
        self.assertFalse(sprite_covers(sprite, 0, 0, sprite.width, sprite.height))

    def test_ignore_frame_pixel_radar(self):
        d = load_reference_data()
        bot = Bot(agent_id=0, role=Role.CREWMATE)
        self.assertTrue(ignore_frame_pixel(bot, d.sprites, RADAR_TASK_COLOR, 60, 60))
        self.assertFalse(ignore_frame_pixel(bot, d.sprites, 5, 100, 100))

    def test_ignore_frame_pixel_player_mask(self):
        d = load_reference_data()
        bot = Bot(agent_id=0, role=Role.CREWMATE)
        # Dead centre → always ignored (player mask).
        self.assertTrue(
            ignore_frame_pixel(bot, d.sprites, 5, PLAYER_SCREEN_X, PLAYER_SCREEN_Y)
        )


class SpriteMatchTests(unittest.TestCase):
    def test_stable_crewmate_color(self):
        self.assertFalse(stable_crewmate_color(TINT_COLOR))
        self.assertFalse(stable_crewmate_color(TRANSPARENT_INDEX))
        # Outline (0) and visor (e.g., 14 blue) are stable.
        self.assertTrue(stable_crewmate_color(0))
        self.assertTrue(stable_crewmate_color(14))

    def test_player_color_index(self):
        # PLAYER_COLORS[0] = red (index 3)
        self.assertEqual(player_color_index(int(PLAYER_COLORS[0])), 0)
        # Unknown colour returns -1.
        self.assertEqual(player_color_index(77), -1)

    def test_player_body_color(self):
        # Lit tint.
        self.assertTrue(player_body_color(int(PLAYER_COLORS[0])))
        # Shadowed variant.
        self.assertTrue(player_body_color(int(SHADOW_MAP[int(PLAYER_COLORS[0])])))
        # Completely unrelated colour.
        self.assertFalse(player_body_color(77))

    def test_matches_sprite_on_self(self):
        """A frame with the exact player sprite painted should match it."""
        d = load_reference_data()
        sprite = d.sprites.task  # use the task sprite — it has no tint pixels
        frame = np.zeros((SCREEN_HEIGHT, SCREEN_WIDTH), dtype=np.uint8)
        # Paint the sprite at (40, 50).
        for sy in range(sprite.height):
            for sx in range(sprite.width):
                c = int(sprite.pixels[sy, sx])
                if c != TRANSPARENT_INDEX:
                    frame[50 + sy, 40 + sx] = c
        self.assertTrue(matches_sprite(frame, sprite, 40, 50))
        # Shifted match should fail (too many misses).
        self.assertFalse(matches_sprite(frame, sprite, 60, 50))


class ActorsTests(unittest.TestCase):
    def test_scan_radar_dots(self):
        d = load_reference_data()
        bot = Bot(agent_id=0, role=Role.CREWMATE)
        frame = np.zeros((SCREEN_HEIGHT, SCREEN_WIDTH), dtype=np.uint8)
        # Put a radar dot on the right edge.
        frame[60, 127] = RADAR_TASK_COLOR
        scan_radar_dots(bot, frame)
        self.assertGreaterEqual(len(bot.percep.radar_dots), 1)

    def test_update_role_unknown_stays_crewmate(self):
        d = load_reference_data()
        bot = Bot(agent_id=0, role=Role.UNKNOWN)
        # Empty frame → kill icon absent → role defaults to CREWMATE.
        frame = np.zeros((SCREEN_HEIGHT, SCREEN_WIDTH), dtype=np.uint8)
        update_role(bot, d.sprites, frame)
        self.assertEqual(bot.role, Role.CREWMATE)
        self.assertFalse(bot.imposter.kill_ready)


if __name__ == "__main__":
    unittest.main()
