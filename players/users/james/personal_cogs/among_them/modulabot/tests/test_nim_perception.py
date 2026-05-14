"""Phase 0 + Phase 1 smoke tests for :mod:`modulabot.nim_perception`.

Phase 0: verifies the build + load path so regressions in the Nim
toolchain or ctypes wiring surface early, not inside a hot perception
path.

Phase 1: pins Nim ≡ numpy parity on every real fixture frame for the
two vectorised sprite-matching kernels the FFI replaced. Running this
file before shipping catches any semantic drift between the native
kernel and the pure-Python fallback.

These tests are independent of the rest of the bot — they don't load
``BotCore``, the actor / voting / localize pipeline, or any policy
code. That keeps them useful as a bisection tool when something below
breaks: if this file fails, the library itself (or its Python wrapper)
is broken; if it passes and higher-level tests fail, the problem is
the caller.

Tests can't assume the library is built — a fresh checkout won't have
it — but :mod:`modulabot.nim_perception` is expected to build on
import. That means if Nim is on ``PATH`` we should have
``HAVE_NATIVE = True``; otherwise we skip gracefully.

The ``MODULABOT_DISABLE_NATIVE=1`` opt-out is also checked: setting it
in a subprocess should yield ``HAVE_NATIVE = False`` regardless of
library state.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

import numpy as np


_HERE = Path(__file__).resolve().parent
_MODULABOT_ROOT = _HERE.parent.parent  # among_them/
_FIXTURES = _HERE / "fixtures_frames.npy"


class NativeLoaderTests(unittest.TestCase):
    """Baseline checks on the module-level load state."""

    def test_exposes_expected_surface(self):
        """The module must expose the documented public attributes."""
        from modulabot import nim_perception

        self.assertIsInstance(nim_perception.ABI_VERSION, int)
        self.assertIn(nim_perception.HAVE_NATIVE, (True, False))
        self.assertTrue(
            nim_perception.LOAD_ERROR is None
            or isinstance(nim_perception.LOAD_ERROR, str)
        )

    def test_loads_when_nim_available(self):
        """If Nim is on ``PATH``, the library must load successfully.

        Skipped when Nim isn't available (e.g. a contributor without
        the Nim toolchain installed). On CI / tournament runners Nim
        is expected to be present.
        """
        if shutil.which("nim") is None:
            self.skipTest("nim not installed; skipping native-load assertion")
        # Reload in a subprocess so we pick up a fresh module cache.
        # That keeps this test honest even if a previous test already
        # cached HAVE_NATIVE under different env.
        code = (
            "from modulabot import nim_perception as n; "
            "print(int(n.HAVE_NATIVE), repr(n.LOAD_ERROR))"
        )
        env = {**os.environ}
        env.pop("MODULABOT_DISABLE_NATIVE", None)
        result = subprocess.run(
            [sys.executable, "-c", code],
            env={**env, "PYTHONPATH": str(_MODULABOT_ROOT)},
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(
            result.stdout.startswith("1 "),
            f"native library did not load: {result.stdout.strip()} / {result.stderr}",
        )

    def test_disable_env_var_opts_out(self):
        """``MODULABOT_DISABLE_NATIVE=1`` forces the numpy fallback."""
        env = {**os.environ, "MODULABOT_DISABLE_NATIVE": "1"}
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                "from modulabot import nim_perception as n; "
                "print(int(n.HAVE_NATIVE))",
            ],
            env={**env, "PYTHONPATH": str(_MODULABOT_ROOT)},
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "0")


class AbiCheckTests(unittest.TestCase):
    """ABI version sanity: Python constant must match the Nim source.

    This is brittle-on-purpose. If either side is bumped without the
    other, every future load will reject the library; catching the
    mismatch here at test time makes it a lot less confusing than a
    silent fallback in production.
    """

    def test_python_abi_matches_nim_source(self):
        """The Python-side ``ABI_VERSION`` must equal the constant in
        ``lib.nim``. We parse the Nim source rather than invoke the
        library — invoking it would only catch mismatches in an
        *already built* library; parsing catches source drift even
        before a rebuild."""
        from modulabot import nim_perception

        lib_nim = _HERE.parent / "nim_perception" / "lib.nim"
        self.assertTrue(lib_nim.exists(), f"{lib_nim} not found")
        text = lib_nim.read_text()
        # Match a line like:
        #   const ModulabotPerceptionAbiVersion* = 1
        import re

        m = re.search(
            r"ModulabotPerceptionAbiVersion\*?\s*=\s*(\d+)", text
        )
        self.assertIsNotNone(m, "could not find ModulabotPerceptionAbiVersion in lib.nim")
        self.assertEqual(int(m.group(1)), nim_perception.ABI_VERSION)

    def test_native_abi_matches_python_abi_when_loaded(self):
        """When the library is loaded, the exported
        ``mb_abi_version`` must match. Skip if native isn't available
        — the ``test_loads_when_nim_available`` test covers that
        dimension."""
        from modulabot import nim_perception

        if not nim_perception.HAVE_NATIVE:
            self.skipTest(f"native not loaded: {nim_perception.LOAD_ERROR}")
        assert nim_perception._lib is not None
        self.assertEqual(
            int(nim_perception._lib.mb_abi_version()),
            nim_perception.ABI_VERSION,
        )


class SpriteMatchParityTests(unittest.TestCase):
    """Nim ≡ numpy parity for the Phase-1 sprite-match kernels.

    Runs the full fixture (275 frames × 3 sprite types × 2 flips ×
    2 kernels = 3 300 calls) and asserts byte-for-byte equality
    between the Nim FFI output and the pure-Python numpy fallback.
    Fast enough to stay in the default suite (~0.2 s on an M-series
    Mac).

    These assertions are the floor for every future perception change.
    If they fail, the Nim kernel's semantics have drifted — do not
    trust any higher-level perception test result until this one is
    back green.
    """

    @classmethod
    def setUpClass(cls):
        from modulabot import nim_perception
        from modulabot.data import load_reference_data

        if not nim_perception.HAVE_NATIVE:
            raise unittest.SkipTest(
                f"native not loaded: {nim_perception.LOAD_ERROR}"
            )
        if not _FIXTURES.exists():
            raise unittest.SkipTest(f"fixtures_frames.npy not found at {_FIXTURES}")
        cls.frames = np.load(_FIXTURES)
        cls.data = load_reference_data()

    def _sprite_configs(self):
        """Return ``(name, sprite, max_misses, min_stable, min_tint)``
        for every sprite scan the actor module runs.

        Kept as an instance helper (not a class-level constant) so it
        imports lazily after ``setUpClass`` has verified the library
        loaded — importing ``actors`` triggers numpy + data module
        init we'd rather skip when the class has to skip itself.
        """
        from modulabot.actors import (
            BODY_MAX_MISSES,
            BODY_MIN_STABLE_PIXELS,
            BODY_MIN_TINT_PIXELS,
            GHOST_MAX_MISSES,
            GHOST_MIN_STABLE_PIXELS,
            GHOST_MIN_TINT_PIXELS,
        )
        from modulabot.sprite_match import (
            CREWMATE_MAX_MISSES,
            CREWMATE_MIN_BODY_PIXELS,
            CREWMATE_MIN_STABLE_PIXELS,
        )

        return (
            ("player", self.data.sprites.player,
             CREWMATE_MAX_MISSES, CREWMATE_MIN_STABLE_PIXELS, CREWMATE_MIN_BODY_PIXELS),
            ("body", self.data.sprites.body,
             BODY_MAX_MISSES, BODY_MIN_STABLE_PIXELS, BODY_MIN_TINT_PIXELS),
            ("ghost", self.data.sprites.ghost,
             GHOST_MAX_MISSES, GHOST_MIN_STABLE_PIXELS, GHOST_MIN_TINT_PIXELS),
        )

    def test_match_nim_equals_numpy_on_all_fixture_frames(self):
        """``mb_match_actor_sprite_all`` agrees with the numpy
        fallback on every frame / sprite / flip combination in the
        fixture."""
        from modulabot import nim_perception
        from modulabot.sprite_match import _match_actor_sprite_all_anchors_numpy

        mismatches: list[str] = []
        for fi, frame in enumerate(self.frames):
            for name, sprite, mm, ms, mt in self._sprite_configs():
                for flip in (False, True):
                    nim = nim_perception.match_actor_sprite_all(
                        frame, sprite.pixels, flip,
                        max_misses=mm,
                        min_stable_pixels=ms,
                        min_tint_pixels=mt,
                    )
                    npv = _match_actor_sprite_all_anchors_numpy(
                        frame, sprite, flip,
                        max_misses=mm,
                        min_stable_pixels=ms,
                        min_tint_pixels=mt,
                    )
                    if not np.array_equal(nim, npv):
                        diff = int(np.count_nonzero(nim != npv))
                        mismatches.append(
                            f"frame={fi} sprite={name} flip={flip} diff_count={diff}"
                        )
                        # Don't flood; 5 mismatches is enough to bisect.
                        if len(mismatches) >= 5:
                            break
                if len(mismatches) >= 5:
                    break
            if len(mismatches) >= 5:
                break
        self.assertEqual(mismatches, [], "Nim vs numpy mismatches: " + "; ".join(mismatches))

    def test_color_index_nim_equals_numpy_on_all_fixture_frames(self):
        """``mb_actor_color_index_all`` agrees with the numpy
        fallback on every frame / sprite / flip combination."""
        from modulabot import nim_perception
        from modulabot.sprite_match import _actor_color_index_all_anchors_numpy

        mismatches: list[str] = []
        for fi, frame in enumerate(self.frames):
            for name, sprite, _mm, _ms, _mt in self._sprite_configs():
                for flip in (False, True):
                    nim = nim_perception.actor_color_index_all(
                        frame, sprite.pixels, flip,
                    )
                    npv = _actor_color_index_all_anchors_numpy(frame, sprite, flip)
                    if not np.array_equal(nim, npv):
                        diff = int(np.count_nonzero(nim != npv))
                        mismatches.append(
                            f"frame={fi} sprite={name} flip={flip} diff_count={diff}"
                        )
                        if len(mismatches) >= 5:
                            break
                if len(mismatches) >= 5:
                    break
            if len(mismatches) >= 5:
                break
        self.assertEqual(mismatches, [], "Nim vs numpy mismatches: " + "; ".join(mismatches))

    def test_dispatcher_routes_through_nim(self):
        """The public :func:`match_actor_sprite_all_anchors` dispatcher
        must return the Nim result when ``HAVE_NATIVE`` is True.

        Checked by toggling ``HAVE_NATIVE`` off (simulating the
        fallback) and confirming the two code paths produce the same
        output on a sample frame. Restores the flag afterwards so
        later tests aren't affected.
        """
        from modulabot import nim_perception
        from modulabot.sprite_match import (
            CREWMATE_MAX_MISSES,
            CREWMATE_MIN_BODY_PIXELS,
            CREWMATE_MIN_STABLE_PIXELS,
            match_actor_sprite_all_anchors,
        )

        frame = self.frames[150]
        sprite = self.data.sprites.player

        # Native path.
        out_native = match_actor_sprite_all_anchors(
            frame, sprite, False,
            max_misses=CREWMATE_MAX_MISSES,
            min_stable_pixels=CREWMATE_MIN_STABLE_PIXELS,
            min_tint_pixels=CREWMATE_MIN_BODY_PIXELS,
        )

        # Force-fallback path.
        saved = nim_perception.HAVE_NATIVE
        try:
            nim_perception.HAVE_NATIVE = False
            out_numpy = match_actor_sprite_all_anchors(
                frame, sprite, False,
                max_misses=CREWMATE_MAX_MISSES,
                min_stable_pixels=CREWMATE_MIN_STABLE_PIXELS,
                min_tint_pixels=CREWMATE_MIN_BODY_PIXELS,
            )
        finally:
            nim_perception.HAVE_NATIVE = saved

        self.assertTrue(np.array_equal(out_native, out_numpy))


class LocalizeParityTests(unittest.TestCase):
    """Nim ≡ numpy parity for the Phase-2 localization kernels.

    Covers :func:`score_camera` (per-camera scoring with early-exit
    disabled for parity) and :func:`_hash_frame_patches` (frame
    8×8-patch FNV hashes). Fixture-driven: 275 real frames, multiple
    camera offsets per frame, all expected to produce byte-identical
    output across both code paths.

    If either of these diverge, every camera lock downstream is
    potentially broken — these assertions are the floor.
    """

    @classmethod
    def setUpClass(cls):
        from modulabot import nim_perception
        from modulabot.data import load_reference_data

        if not nim_perception.HAVE_NATIVE:
            raise unittest.SkipTest(
                f"native not loaded: {nim_perception.LOAD_ERROR}"
            )
        if not _FIXTURES.exists():
            raise unittest.SkipTest(f"fixtures_frames.npy not found at {_FIXTURES}")
        cls.frames = np.load(_FIXTURES)
        cls.data = load_reference_data()

    def _prepare_frame(self, frame):
        """Run scan_all + one localize pass on ``frame`` so we get a
        realistic ignore mask + camera lock to score against.
        Returns ``(bot, ignore_mask)`` or ``None`` on interstitial.
        """
        from modulabot.actors import scan_all
        from modulabot.frame import compute_ignore_mask, looks_like_interstitial
        from modulabot.localize import Localizer
        from modulabot.state import Bot

        if looks_like_interstitial(frame):
            return None
        bot = Bot(agent_id=0)
        scan_all(bot, self.data.sprites, frame, self.data.map)
        localizer = Localizer(self.data.map)
        localizer.update_location(bot, self.data.sprites, frame)
        if not bot.percep.localized:
            return None
        ignore = compute_ignore_mask(bot, self.data.sprites, frame)
        return bot, ignore

    def test_score_camera_parity(self):
        """Nim ``mb_score_camera`` returns ``(score, errors, compared)``
        byte-identical to :func:`_score_camera_numpy` for every tested
        camera offset.

        We score each frame against four cameras: the locked one,
        a small perturbation, a far-away off-map origin, and one
        just outside the map corner — to cover in-range, near-miss,
        and fully off-map arithmetic.
        """
        from modulabot import nim_perception
        from modulabot.localize import (
            FULL_FRAME_FIT_MAX_ERRORS,
            _score_camera_numpy,
        )

        mismatches = 0
        total = 0
        for fi in range(0, len(self.frames), 5):
            prep = self._prepare_frame(self.frames[fi])
            if prep is None:
                continue
            bot, ignore = prep
            cameras = [
                (bot.percep.camera_x, bot.percep.camera_y),
                (bot.percep.camera_x + 7, bot.percep.camera_y - 4),
                (10, 10),
                (-5, -5),
            ]
            for cx, cy in cameras:
                py = _score_camera_numpy(
                    self.frames[fi], self.data.map.map_pixels, ignore, cx, cy,
                    max_errors=FULL_FRAME_FIT_MAX_ERRORS,
                )
                nim_s, nim_e, nim_c = nim_perception.score_camera(
                    self.frames[fi], self.data.map.map_pixels, ignore, cx, cy,
                    FULL_FRAME_FIT_MAX_ERRORS,
                )
                total += 1
                if py.score != nim_s or py.errors != nim_e or py.compared != nim_c:
                    mismatches += 1
                    if mismatches <= 3:
                        # Report enough context to bisect which
                        # pixel diverged.
                        self.fail(
                            f"score_camera mismatch at fi={fi} cam=({cx},{cy}): "
                            f"numpy=(score={py.score},errors={py.errors},compared={py.compared}) "
                            f"nim=(score={nim_s},errors={nim_e},compared={nim_c})"
                        )
        self.assertGreater(total, 20, "no gameplay frames exercised")
        self.assertEqual(mismatches, 0)

    def test_hash_frame_patches_parity(self):
        """Nim ``mb_hash_frame_patches`` returns ``(hashes, valid)``
        byte-identical to :func:`_hash_frame_patches_numpy` for
        every gameplay frame in the fixture.

        The hash table + valid mask feed the patch-index lookup
        directly — any drift here would cause localisation to
        randomly un-lock in the field.
        """
        from modulabot import nim_perception
        from modulabot.localize import _hash_frame_patches_numpy

        tested = 0
        for fi in range(0, len(self.frames), 5):
            prep = self._prepare_frame(self.frames[fi])
            if prep is None:
                continue
            _bot, ignore = prep
            np_h, np_v = _hash_frame_patches_numpy(self.frames[fi], ignore)
            nim_h, nim_v = nim_perception.hash_frame_patches(
                self.frames[fi], ignore
            )
            self.assertTrue(
                np.array_equal(np_h, nim_h),
                f"hash mismatch at fi={fi}",
            )
            self.assertTrue(
                np.array_equal(np_v, nim_v),
                f"valid-mask mismatch at fi={fi}",
            )
            tested += 1
        self.assertGreater(tested, 20, "no gameplay frames exercised")

    def test_vote_camera_candidates_parity(self):
        """Nim bulk ``mb_vote_camera_candidates`` returns the same
        top-K candidate list as the Python per-patch vote loop.

        This is the Phase-2.5 kernel that made cold localize 5.6×
        faster. If the ordering / content diverges, every patch-
        based camera lock will pick a different candidate set, which
        turns into randomly different locks in the field (same
        validity → same final lock, but the intermediate ordering
        matters for tie-breaking when two cameras score equally).
        """
        from modulabot.localize import Localizer, _hash_frame_patches

        loc = Localizer(self.data.map)
        tested = 0
        for fi in range(0, len(self.frames), 5):
            prep = self._prepare_frame(self.frames[fi])
            if prep is None:
                continue
            _bot, ignore = prep
            fh, fv = _hash_frame_patches(self.frames[fi], ignore)
            # Fresh localizer for each call so the vote buffer starts
            # zero in both paths — _collect_candidates_native /
            # _collect_candidates_numpy both reset the buffer to zero
            # on exit, but defensive here because a shared buffer
            # with stale nonzero slots would bias one path.
            from modulabot.localize import Localizer as _Loc
            loc_np = _Loc(self.data.map)
            loc_nim = _Loc(self.data.map)
            c_np = loc_np._collect_candidates_numpy(fh, fv)
            c_nim = loc_nim._collect_candidates_native(fh, fv)
            self.assertEqual(
                c_np, c_nim,
                f"vote_camera_candidates mismatch at fi={fi}: "
                f"numpy={c_np[:5]} nim={c_nim[:5]}",
            )
            tested += 1
        self.assertGreater(tested, 20, "no gameplay frames exercised")


class ScanTaskIconsParityTests(unittest.TestCase):
    """Nim ≡ Python parity for :func:`modulabot.actors.scan_task_icons`.

    Phase-3 kernel. Task-icon matches feed the crewmate policy's
    "walk-to-task" target selection; any divergence would cause
    random task-targeting differences between the Nim and fallback
    paths.
    """

    @classmethod
    def setUpClass(cls):
        from modulabot import nim_perception
        from modulabot.data import load_reference_data

        if not nim_perception.HAVE_NATIVE:
            raise unittest.SkipTest(
                f"native not loaded: {nim_perception.LOAD_ERROR}"
            )
        if not _FIXTURES.exists():
            raise unittest.SkipTest(f"fixtures_frames.npy not found at {_FIXTURES}")
        cls.frames = np.load(_FIXTURES)
        cls.data = load_reference_data()

    def test_task_icons_parity_on_fixture(self):
        """Native and pure-Python :func:`scan_all` produce the same
        ``bot.percep.visible_task_icons`` list on every gameplay
        frame.

        Runs the full ``scan_all`` (not just ``scan_task_icons``) so
        the test also pins the surrounding state — role inference,
        body/ghost scans — behind the task-icon call. This is the
        end-to-end guarantee callers actually rely on.
        """
        from modulabot import nim_perception
        from modulabot.actors import scan_all
        from modulabot.frame import looks_like_interstitial
        from modulabot.state import Bot

        tested = 0
        for fi in range(0, len(self.frames), 3):
            frame = self.frames[fi]
            if looks_like_interstitial(frame):
                continue
            # Native
            bot_native = Bot(agent_id=0)
            scan_all(bot_native, self.data.sprites, frame, self.data.map)
            native = sorted(
                (m.x, m.y) for m in bot_native.percep.visible_task_icons
            )
            # Fallback (native forced off)
            saved = nim_perception.HAVE_NATIVE
            try:
                nim_perception.HAVE_NATIVE = False
                bot_py = Bot(agent_id=0)
                scan_all(bot_py, self.data.sprites, frame, self.data.map)
                py = sorted(
                    (m.x, m.y) for m in bot_py.percep.visible_task_icons
                )
            finally:
                nim_perception.HAVE_NATIVE = saved
            self.assertEqual(
                native, py,
                f"task-icon mismatch at fi={fi}: native={native} py={py}",
            )
            tested += 1
        self.assertGreater(tested, 20, "no gameplay frames exercised")


class OcrParityTests(unittest.TestCase):
    """Nim ≡ Python parity for the Phase-4 OCR kernels.

    Covers :func:`best_glyph` (per-position glyph pick) and
    :func:`text_matches` (fixed-phrase check). Both feed the
    voting-chat parse and interstitial banner detection, so any
    drift here breaks OCR-dependent policy decisions in the field.

    Fixture strategy: build synthetic frames that exercise each
    glyph in isolation and each char in common voting / banner
    phrases. No captured fixture voting frames exist yet; once
    they do we should add a regression test against them.
    """

    @classmethod
    def setUpClass(cls):
        from modulabot import nim_perception
        from modulabot.data import load_reference_data

        if not nim_perception.HAVE_NATIVE:
            raise unittest.SkipTest(
                f"native not loaded: {nim_perception.LOAD_ERROR}"
            )
        cls.data = load_reference_data()

    def _paint(self, text: str, x: int, y: int) -> np.ndarray:
        """Render ``text`` at ``(x, y)`` on a black 128×128 frame
        using the live font. Same code the voting-frame builder
        uses, repeated here to keep the test self-contained."""
        from modulabot import ascii as ascii_mod

        frame = np.zeros((128, 128), dtype=np.uint8)
        pen = x
        for ch in text:
            g = ascii_mod.glyph_at(self.data.font, ch)
            for py in range(g.height):
                for px in range(g.width):
                    if g.pixels[py, px]:
                        frame[y + py, pen + px] = 2
            pen += ascii_mod.glyph_advance(self.data.font, ch)
        return frame

    def test_best_glyph_every_printable_ascii(self):
        """Render each printable ASCII char in isolation and verify
        Nim picks the same glyph as the vectorised-numpy path."""
        from modulabot import nim_perception
        from modulabot import ascii as ascii_mod

        mismatches: list[str] = []
        for code in range(32, 127):
            ch = chr(code)
            g = ascii_mod.glyph_at(self.data.font, ch)
            if g.width == 0:
                continue
            frame = self._paint(ch, 10, 20)
            py = ascii_mod._best_glyph_numpy(frame, self.data.font, 10, 20)
            nim_c, _, _ = nim_perception.best_glyph(
                frame, self.data.font, 10, 20,
            )
            if py != nim_c:
                mismatches.append(f"{ch!r}: py={py!r} nim={nim_c!r}")
        self.assertEqual(mismatches, [], "; ".join(mismatches))

    def test_best_glyph_reads_multi_char_phrase(self):
        """Walk across a rendered phrase, reading one glyph at each
        pen position. Nim and numpy must produce the same string."""
        from modulabot import nim_perception
        from modulabot import ascii as ascii_mod

        phrases = (
            "HELLO 123",
            "sus red in elec",
            "VOTE BLUE",
            "body near CAFE",
        )
        for phrase in phrases:
            frame = self._paint(phrase, 10, 20)
            py_chars: list[str] = []
            nim_chars: list[str] = []
            pen = 10
            for ch in phrase:
                py_chars.append(
                    ascii_mod._best_glyph_numpy(frame, self.data.font, pen, 20)
                )
                nim_c, _, _ = nim_perception.best_glyph(
                    frame, self.data.font, pen, 20,
                )
                nim_chars.append(nim_c)
                pen += ascii_mod.glyph_advance(self.data.font, ch)
            self.assertEqual(
                "".join(py_chars), "".join(nim_chars),
                f"phrase={phrase!r}: py={''.join(py_chars)!r} nim={''.join(nim_chars)!r}",
            )

    def test_text_matches_pass_and_fail(self):
        """text_matches returns True on the painted phrase and
        False on a mismatched phrase, via both code paths."""
        from modulabot import nim_perception
        from modulabot import ascii as ascii_mod

        for phrase in ("HELLO", "SKIP", "CREWMATE", "IMPS WIN"):
            frame = self._paint(phrase, 10, 20)
            self.assertTrue(
                ascii_mod._text_matches_numpy(
                    frame, self.data.font, phrase, 10, 20
                )
            )
            self.assertTrue(
                nim_perception.text_matches(
                    frame, self.data.font, phrase, 10, 20
                )
            )
            # Negative check: wrong phrase at same position.
            wrong = phrase[::-1]
            if wrong != phrase:  # palindromes would trivially match
                self.assertEqual(
                    ascii_mod._text_matches_numpy(
                        frame, self.data.font, wrong, 10, 20
                    ),
                    nim_perception.text_matches(
                        frame, self.data.font, wrong, 10, 20
                    ),
                )


if __name__ == "__main__":
    unittest.main()