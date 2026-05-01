"""Perception snapshot tests against real captured frames.

Pins the output of :func:`modulabot.actors.scan_all` on a few specific
frames from a real local-episode capture. If perception regresses (e.g.
someone fiddles a threshold and suddenly misses every crewmate), these
fail loudly.

The capture lives at ``tests/fixtures_frames.npy`` — 275 frames of real
Among Them gameplay. Regenerate with::

    cd among_them
    PYTHONPATH=. python scripts/capture.py \
        --duration 12 --output modulabot/tests/fixtures_frames.npy

We intentionally test *counts* and *roles* rather than exact match
positions — those are noisy under minor perception changes. Position
assertions would slow down iteration on the matcher without buying much
regression coverage.

This file also hosts :class:`VectorisedParityTests`, which pins that
the vectorised scanners in :mod:`modulabot.actors` return the same
anchors as running the scalar matchers at every anchor. It's the
safety net for future tuning of the vectorised path.
"""

from __future__ import annotations

import unittest
from pathlib import Path

import numpy as np

from modulabot.actors import (
    BODY_MAX_MISSES,
    BODY_MIN_STABLE_PIXELS,
    BODY_MIN_TINT_PIXELS,
    GHOST_MAX_MISSES,
    GHOST_MIN_STABLE_PIXELS,
    GHOST_MIN_TINT_PIXELS,
    scan_all,
    scan_bodies,
    scan_crewmates,
    scan_ghosts,
)
from modulabot.data import load_reference_data
from modulabot.frame import looks_like_interstitial
from modulabot.sprite_match import (
    CREWMATE_MAX_MISSES,
    CREWMATE_MIN_BODY_PIXELS,
    CREWMATE_MIN_STABLE_PIXELS,
    match_actor_sprite_all_anchors,
    matches_actor_sprite,
    matches_crewmate,
)
from modulabot.state import Bot, Role

_FIXTURES = Path(__file__).resolve().parent / "fixtures_frames.npy"


class PerceptionSnapshotTests(unittest.TestCase):
    """Current snapshots, recorded 2026-04-30. Update when the bot improves."""

    @classmethod
    def setUpClass(cls):
        if not _FIXTURES.exists():
            raise unittest.SkipTest(
                f"fixtures_frames.npy not found at {_FIXTURES}; "
                "run scripts/capture_frames.py to regenerate"
            )
        cls.frames = np.load(_FIXTURES)
        cls.data = load_reference_data()

    def _scan(self, frame_idx: int) -> Bot:
        bot = Bot(agent_id=0, role=Role.UNKNOWN)
        scan_all(bot, self.data.sprites, self.frames[frame_idx], self.data.map)
        return bot

    def test_interstitial_frames_produce_no_visible_actors(self):
        """The 30%-black gate must suppress sprite matches on interstitial frames.

        Frames 0..~130 in the capture are pre-round splash + role reveal
        + ready animations — mostly black. Without gating, the body/ghost
        matchers fire on outline-heavy patterns. With gating, every
        list should be empty.
        """
        for idx in (0, 25, 50, 75, 100):
            bot = self._scan(idx)
            self.assertTrue(
                looks_like_interstitial(self.frames[idx]),
                f"frame {idx} expected to be interstitial",
            )
            self.assertEqual(len(bot.percep.visible_crewmates), 0)
            self.assertEqual(len(bot.percep.visible_bodies), 0)
            self.assertEqual(len(bot.percep.visible_ghosts), 0)
            self.assertEqual(len(bot.percep.visible_task_icons), 0)

    def test_gameplay_frame_detects_at_least_one_crewmate(self):
        """Frame 150 shows multiple crewmates on screen; we should find ≥1.

        Not an exact-count assertion: the sprite matcher is tuned against
        the canonical standing pose, and walking crewmates match less
        reliably. Improving recall is explicit next-session work —
        locking in ≥1 keeps us from silently regressing to 0.
        """
        bot = self._scan(150)
        self.assertFalse(looks_like_interstitial(self.frames[150]))
        self.assertGreaterEqual(
            len(bot.percep.visible_crewmates),
            1,
            "expected at least one crewmate detected on an active-gameplay frame",
        )

    def test_role_inference_settles(self):
        """The role HUD icon matcher should lock in a role on in-game frames.

        We run scan_all on frame 150, then assert the role is CREWMATE or
        IMPOSTER (never UNKNOWN). This catches regressions where the
        kill-icon matcher stops firing.
        """
        bot = self._scan(150)
        self.assertIn(bot.role, (Role.CREWMATE, Role.IMPOSTER))


class VectorisedParityTests(unittest.TestCase):
    """Vectorised all-anchor matchers must agree with the scalar path.

    The scalar :func:`matches_crewmate` / :func:`matches_actor_sprite`
    are the reference implementations (direct port of the Nim bot).
    :func:`match_actor_sprite_all_anchors` is the numpy rewrite.
    Running both over a real frame and asserting identical accept
    masks is the strongest correctness check we have short of
    synthetic frames.

    Uses a gameplay frame (body + ghost + crewmate sprites all make
    sense to scan) and a harder full-sweep frame for each sprite.
    """

    @classmethod
    def setUpClass(cls):
        fixtures = Path(__file__).resolve().parent / "fixtures_frames.npy"
        if not fixtures.exists():
            raise unittest.SkipTest(f"fixtures_frames.npy not found at {fixtures}")
        cls.frames = np.load(fixtures)
        cls.data = load_reference_data()

    def _scalar_accept_mask(
        self,
        frame: np.ndarray,
        sprite,
        flip_h: bool,
        *,
        max_misses: int,
        min_stable: int,
        min_tint: int,
        crewmate: bool,
    ) -> np.ndarray:
        sh, sw = sprite.height, sprite.width
        max_y = frame.shape[0] - sh + 1
        max_x = frame.shape[1] - sw + 1
        out = np.zeros((max_y, max_x), dtype=bool)
        for y in range(max_y):
            for x in range(max_x):
                if crewmate:
                    out[y, x] = matches_crewmate(frame, sprite, x, y, flip_h)
                else:
                    out[y, x] = matches_actor_sprite(
                        frame, sprite, x, y, flip_h,
                        max_misses, min_stable, min_tint,
                    )
        return out

    def test_crewmate_matcher_parity_on_gameplay_frame(self):
        frame = self.frames[150]
        for flip_h in (False, True):
            vec = match_actor_sprite_all_anchors(
                frame,
                self.data.sprites.player,
                flip_h,
                max_misses=CREWMATE_MAX_MISSES,
                min_stable_pixels=CREWMATE_MIN_STABLE_PIXELS,
                min_tint_pixels=CREWMATE_MIN_BODY_PIXELS,
            )
            scalar = self._scalar_accept_mask(
                frame,
                self.data.sprites.player,
                flip_h,
                max_misses=CREWMATE_MAX_MISSES,
                min_stable=CREWMATE_MIN_STABLE_PIXELS,
                min_tint=CREWMATE_MIN_BODY_PIXELS,
                crewmate=True,
            )
            np.testing.assert_array_equal(
                vec, scalar,
                err_msg=f"flip_h={flip_h}: vectorised accepted {int(vec.sum())} "
                        f"anchors vs scalar {int(scalar.sum())}",
            )

    def test_body_matcher_parity_on_gameplay_frame(self):
        frame = self.frames[150]
        vec = match_actor_sprite_all_anchors(
            frame,
            self.data.sprites.body,
            False,
            max_misses=BODY_MAX_MISSES,
            min_stable_pixels=BODY_MIN_STABLE_PIXELS,
            min_tint_pixels=BODY_MIN_TINT_PIXELS,
        )
        scalar = self._scalar_accept_mask(
            frame,
            self.data.sprites.body,
            False,
            max_misses=BODY_MAX_MISSES,
            min_stable=BODY_MIN_STABLE_PIXELS,
            min_tint=BODY_MIN_TINT_PIXELS,
            crewmate=False,
        )
        np.testing.assert_array_equal(vec, scalar)

    def test_ghost_matcher_parity_on_gameplay_frame(self):
        frame = self.frames[150]
        for flip_h in (False, True):
            vec = match_actor_sprite_all_anchors(
                frame,
                self.data.sprites.ghost,
                flip_h,
                max_misses=GHOST_MAX_MISSES,
                min_stable_pixels=GHOST_MIN_STABLE_PIXELS,
                min_tint_pixels=GHOST_MIN_TINT_PIXELS,
            )
            scalar = self._scalar_accept_mask(
                frame,
                self.data.sprites.ghost,
                flip_h,
                max_misses=GHOST_MAX_MISSES,
                min_stable=GHOST_MIN_STABLE_PIXELS,
                min_tint=GHOST_MIN_TINT_PIXELS,
                crewmate=False,
            )
            np.testing.assert_array_equal(
                vec, scalar,
                err_msg=f"ghost flip_h={flip_h}: vec {int(vec.sum())} vs "
                        f"scalar {int(scalar.sum())}",
            )


if __name__ == "__main__":
    unittest.main()
