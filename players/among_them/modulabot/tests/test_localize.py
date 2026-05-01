"""Tests for the camera localizer.

Three layers:

1. **Unit tests** for :func:`modulabot.localize.score_camera` and the
   patch-index builder — synthetic maps and hand-constructed frames so
   the expected outputs are obvious.
2. **Cache / invariant tests** — patch index is cached per GameMap;
   hash table is sorted; camera anchor ranges match the public geometry
   helpers.
3. **Fixture tests** — run :class:`~modulabot.localize.Localizer`
   against every non-interstitial frame in ``fixtures_frames.npy`` and
   pin the lock success rate at 100% plus a max-wall-clock budget.
   This is the backstop that catches any regression in the
   vectorisation tricks or the seed-acceptance shortcut.
"""

from __future__ import annotations

import time
import unittest
from pathlib import Path

import numpy as np

from modulabot.actors import scan_all
from modulabot.data import MAP_VOID_COLOR, load_reference_data
from modulabot.frame import looks_like_interstitial
from modulabot.localize import (
    FULL_FRAME_FIT_MAX_ERRORS,
    PATCH_SIZE,
    Localizer,
    get_patch_index,
    score_camera,
)
from modulabot.state import Bot, CameraLock, Role


_FIXTURES = Path(__file__).resolve().parent / "fixtures_frames.npy"


class ScoreCameraUnitTests(unittest.TestCase):
    """Score a hand-built frame against a hand-built map."""

    def _empty_ignore(self) -> np.ndarray:
        from modulabot.data import SCREEN_HEIGHT, SCREEN_WIDTH
        return np.zeros((SCREEN_HEIGHT, SCREEN_WIDTH), dtype=bool)

    def test_exact_match_zero_errors(self):
        """A frame that exactly equals a map window should score
        zero errors and ``compared == 128*128``."""
        from modulabot.data import SCREEN_HEIGHT, SCREEN_WIDTH
        map_pixels = np.random.default_rng(0).integers(
            0, 16, size=(300, 300), dtype=np.uint8
        )
        cx, cy = 42, 17
        frame = map_pixels[cy : cy + SCREEN_HEIGHT, cx : cx + SCREEN_WIDTH].copy()
        s = score_camera(frame, map_pixels, self._empty_ignore(), cx, cy)
        self.assertEqual(s.errors, 0)
        self.assertEqual(s.compared, SCREEN_HEIGHT * SCREEN_WIDTH)
        self.assertEqual(s.score, SCREEN_HEIGHT * SCREEN_WIDTH)

    def test_completely_wrong_camera_many_errors(self):
        """A frame against an off-match camera should produce many
        errors. We don't pin the exact count (depends on random
        collisions), just that it exceeds the max-errors budget."""
        from modulabot.data import SCREEN_HEIGHT, SCREEN_WIDTH
        map_pixels = np.full((300, 300), 3, dtype=np.uint8)
        frame = np.full((SCREEN_HEIGHT, SCREEN_WIDTH), 11, dtype=np.uint8)
        s = score_camera(frame, map_pixels, self._empty_ignore(), 0, 0)
        self.assertGreater(s.errors, FULL_FRAME_FIT_MAX_ERRORS)

    def test_ignore_mask_reduces_compared(self):
        """Every masked pixel should neither count toward compared nor
        toward errors."""
        from modulabot.data import SCREEN_HEIGHT, SCREEN_WIDTH
        map_pixels = np.full((SCREEN_HEIGHT, SCREEN_WIDTH), 7, dtype=np.uint8)
        frame = np.full((SCREEN_HEIGHT, SCREEN_WIDTH), 7, dtype=np.uint8)
        frame[0:32, 0:32] = 9  # 1024 mismatches
        ignore = np.zeros((SCREEN_HEIGHT, SCREEN_WIDTH), dtype=bool)
        ignore[0:32, 0:32] = True  # masked out

        s_masked = score_camera(frame, map_pixels, ignore, 0, 0)
        self.assertEqual(s_masked.errors, 0)
        self.assertEqual(s_masked.compared, SCREEN_HEIGHT * SCREEN_WIDTH - 1024)

        # Without the mask, we'd see 1024 errors.
        s_unmasked = score_camera(
            frame, map_pixels, np.zeros_like(ignore), 0, 0,
            max_errors=10_000,
        )
        self.assertEqual(s_unmasked.errors, 1024)
        self.assertEqual(
            s_unmasked.compared, SCREEN_HEIGHT * SCREEN_WIDTH
        )

    def test_off_map_pixels_treated_as_void(self):
        """Scoring with a camera that falls outside the map should
        compare void colour against the frame and still return
        sensible counts (rather than raising)."""
        from modulabot.data import SCREEN_HEIGHT, SCREEN_WIDTH
        map_pixels = np.full((20, 20), 7, dtype=np.uint8)  # tiny map
        frame = np.full((SCREEN_HEIGHT, SCREEN_WIDTH), MAP_VOID_COLOR, dtype=np.uint8)
        s = score_camera(frame, map_pixels, self._empty_ignore(), -500, -500)
        # Frame is all void; map window is entirely off-map → filled with
        # void → zero errors.
        self.assertEqual(s.errors, 0)
        self.assertEqual(s.compared, SCREEN_HEIGHT * SCREEN_WIDTH)

    def test_max_errors_early_cap_reports_penalty_score(self):
        """When errors exceed the budget the score is a negative
        penalty — it shouldn't rank above any legitimate score."""
        from modulabot.data import SCREEN_HEIGHT, SCREEN_WIDTH
        map_pixels = np.full((SCREEN_HEIGHT, SCREEN_WIDTH), 1, dtype=np.uint8)
        frame = np.full((SCREEN_HEIGHT, SCREEN_WIDTH), 5, dtype=np.uint8)
        s = score_camera(frame, map_pixels, self._empty_ignore(), 0, 0, max_errors=10)
        self.assertGreater(s.errors, 10)
        self.assertLess(s.score, 0)


class PatchIndexTests(unittest.TestCase):
    """Invariants on :func:`get_patch_index`."""

    @classmethod
    def setUpClass(cls):
        cls.data = load_reference_data()
        cls.index = get_patch_index(cls.data.map)

    def test_index_cached(self):
        """Second call should return the same instance."""
        again = get_patch_index(self.data.map)
        self.assertIs(again, self.index)

    def test_hashes_sorted(self):
        # Ascending order is the precondition for the np.searchsorted
        # lookup in the patch-hash locator.
        diffs = np.diff(self.index.hashes)
        self.assertTrue((diffs >= 0).all(), "patch-index hashes not sorted ascending")

    def test_index_sizes_consistent(self):
        self.assertEqual(self.index.hashes.shape, self.index.cam_xs.shape)
        self.assertEqual(self.index.hashes.shape, self.index.cam_ys.shape)
        self.assertEqual(self.index.hashes.shape[0], self.index.width * self.index.height)

    def test_known_map_patch_hash_is_findable(self):
        """A patch hash computed from a known map region should appear
        at least once in the index."""
        from modulabot.localize import (
            PATCH_HASH_BASE,
            PATCH_HASH_SEED,
        )
        map_pixels = self.data.map.map_pixels

        # Hash one concrete 8×8 patch at an interior spot. The
        # `errstate(over='ignore')` suppresses the uint64 overflow
        # warning — overflow is the intended hash-mixing behaviour,
        # matched by the Nim bot's unsigned arithmetic.
        x0, y0 = 400, 200
        with np.errstate(over="ignore"):
            h = PATCH_HASH_SEED
            for py in range(PATCH_SIZE):
                for px in range(PATCH_SIZE):
                    h = (
                        h * PATCH_HASH_BASE
                        + np.uint64(int(map_pixels[y0 + py, x0 + px]) & 0x0F)
                        + np.uint64(1)
                    )
        first = int(np.searchsorted(self.index.hashes, h, side="left"))
        last = int(np.searchsorted(self.index.hashes, h, side="right"))
        self.assertGreater(last - first, 0)
        # One of the matches should have (camX, camY) == (x0, y0).
        ranges = list(zip(
            self.index.cam_xs[first:last].tolist(),
            self.index.cam_ys[first:last].tolist(),
        ))
        self.assertIn((x0, y0), ranges)


class LocalizerFixtureTests(unittest.TestCase):
    """Drive a :class:`Localizer` through every real captured frame.

    These tests are the strongest correctness + perf net we have —
    they run the full pipeline (actor scans → localize) on 275
    captured frames of live gameplay. Regressions that pass the
    synthetic unit tests but break on real data (e.g. overly
    aggressive seed acceptance that loses track of a moving bot,
    wrong shadow-colour handling, buggy ignore mask) show up here
    as drops in the lock-success rate or blown wall-clock budgets.

    Pipeline results are computed once per test class via
    :meth:`setUpClass` and shared across the three test cases —
    running the 144-frame pipeline three times would triple suite
    time for no additional coverage.
    """

    @classmethod
    def setUpClass(cls):
        if not _FIXTURES.exists():
            raise unittest.SkipTest(f"fixtures_frames.npy not found at {_FIXTURES}")
        cls.frames = np.load(_FIXTURES)
        cls.data = load_reference_data()
        cls.results = cls._run_pipeline(cls.frames, cls.data)

    @staticmethod
    def _run_pipeline(frames, data):
        bot = Bot(agent_id=0, role=Role.UNKNOWN)
        localizer = Localizer(data.map)
        results = []
        for idx, frame in enumerate(frames):
            if looks_like_interstitial(frame):
                continue
            scan_all(bot, data.sprites, frame, data.map)
            t0 = time.perf_counter()
            localizer.update_location(bot, data.sprites, frame)
            elapsed = (time.perf_counter() - t0) * 1000
            results.append({
                "idx": idx,
                "elapsed_ms": elapsed,
                "localized": bot.percep.localized,
                "camera_x": bot.percep.camera_x,
                "camera_y": bot.percep.camera_y,
                "lock": bot.percep.camera_lock,
            })
        return results

    def test_every_non_interstitial_frame_localizes(self):
        self.assertGreater(len(self.results), 100, "need enough non-interstitial frames to be meaningful")
        fails = [r for r in self.results if not r["localized"]]
        self.assertEqual(
            len(fails), 0,
            f"{len(fails)}/{len(self.results)} frames failed to localize: "
            f"first 5 = {fails[:5]}",
        )

    def test_first_lock_is_global_subsequent_are_local(self):
        """The first non-interstitial frame should cold-start via the
        patch-hash global search (``FRAME_MAP_LOCK``). Every later
        frame in the captured sequence should hit the cheap local
        refit. If this reverses, something broke the seed continuity
        (e.g. we're failing to carry ``last_camera_*`` across frames).
        """
        self.assertEqual(self.results[0]["lock"], CameraLock.FRAME_MAP_LOCK)
        non_local_after_first = sum(
            1 for r in self.results[1:] if r["lock"] != CameraLock.LOCAL_FRAME_MAP_LOCK
        )
        self.assertLess(
            non_local_after_first, max(2, len(self.results) // 50),
            f"too many non-local locks post-cold-start: {non_local_after_first}",
        )

    def test_localize_stays_under_wall_clock_budget(self):
        """p95 localize wall time < 5 ms. Gives us ~37 ms of slack
        under a 42 ms/frame 24Hz budget for the rest of the pipeline.
        Bumped on cold-cache runs because the first scoreCamera pays
        a JIT-style warm-up, so we check p95 not max."""
        times = sorted(r["elapsed_ms"] for r in self.results)
        p95 = times[int(0.95 * len(times))]
        self.assertLess(
            p95, 5.0,
            f"localize p95 regressed to {p95:.2f}ms "
            f"(mean={sum(times)/len(times):.2f}ms max={max(times):.2f}ms)",
        )


if __name__ == "__main__":
    unittest.main()
