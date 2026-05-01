"""Benchmark modulabot perception kernels against the captured frame fixture.

Run before and after each phase of the Nim-perception port to track
progress against the targets in ``modulabot/PERCEPTION_PERF_PLAN.md``.

Usage::

    PYTHONPATH=among_them .venv/bin/python \\
        among_them/scripts/bench_perception.py

Reports p50 / p95 / p99 / mean / max microseconds for each kernel, plus
end-to-end ``BotCore.step`` times split by phase (gameplay /
interstitial). Honours ``MODULABOT_DISABLE_NATIVE=1`` so we can compare
numpy-fallback vs. Nim side-by-side by running the script twice.

The fixture (``modulabot/tests/fixtures_frames.npy``) holds 275 real
gameplay frames captured via ``scripts/capture_frames.py``. We skip
voting kernels' fixture runs for now because no captured voting frame
exists; a synthetic frame is constructed instead so the OCR kernel
still gets exercised.
"""

from __future__ import annotations

import argparse
import os
import statistics
import sys
import time
from pathlib import Path
from typing import Callable

import numpy as np

# Make ``modulabot`` importable whether the script is run from the repo
# root or from ``among_them/``.
_HERE = Path(__file__).resolve().parent
_AMONG_THEM = _HERE.parent
if str(_AMONG_THEM) not in sys.path:
    sys.path.insert(0, str(_AMONG_THEM))

from modulabot.actors import scan_all  # noqa: E402
from modulabot.bot import BotCore  # noqa: E402
from modulabot.data import load_reference_data  # noqa: E402
from modulabot.frame import looks_like_interstitial  # noqa: E402
from modulabot.localize import Localizer, score_camera  # noqa: E402
from modulabot.state import Bot, Phase  # noqa: E402
from modulabot import voting as voting_mod  # noqa: E402

# Voting synthetic frame builder lives in the test module — we reimport
# it here instead of duplicating the 60-line constructor.
sys.path.insert(0, str(_AMONG_THEM / "modulabot" / "tests"))
from test_pixel_pipeline import _build_voting_frame  # type: ignore  # noqa: E402


# ---------------------------------------------------------------------------
# Timing helpers
# ---------------------------------------------------------------------------


def _time_one(fn: Callable[[], None]) -> float:
    """Return wall-clock seconds for a single call, measured with
    ``perf_counter_ns`` to reduce jitter."""
    start = time.perf_counter_ns()
    fn()
    return (time.perf_counter_ns() - start) / 1e9


def _report(name: str, samples_s: list[float]) -> None:
    if not samples_s:
        print(f"{name:<42} (no samples)")
        return
    us = [s * 1e6 for s in samples_s]
    us.sort()
    n = len(us)

    def _pct(p: float) -> float:
        idx = min(n - 1, max(0, int(round(p * (n - 1)))))
        return us[idx]

    print(
        f"{name:<42} n={n:>4}  "
        f"p50={_pct(0.50):>8.1f}  "
        f"p95={_pct(0.95):>8.1f}  "
        f"p99={_pct(0.99):>8.1f}  "
        f"max={us[-1]:>8.1f}  "
        f"mean={statistics.fmean(us):>8.1f}  "
        f"(µs)"
    )


# ---------------------------------------------------------------------------
# Benchmark drivers
# ---------------------------------------------------------------------------


def bench_scan_all(frames: np.ndarray, data, warmups: int, max_frames: int) -> None:
    """Time :func:`modulabot.actors.scan_all` per frame.

    Uses a fresh ``Bot`` each call so internal state (``ghost_icon_frames``
    etc.) doesn't drift across frames and perturb miss counts. Warmup runs
    are discarded.
    """
    samples: list[float] = []
    for i, frame in enumerate(frames[:max_frames]):
        bot = Bot(agent_id=0)
        if i < warmups:
            scan_all(bot, data.sprites, frame, data.map)
            continue
        samples.append(_time_one(lambda: scan_all(bot, data.sprites, frame, data.map)))
    _report("actors.scan_all (all frames)", samples)


def bench_score_camera(frames: np.ndarray, data, warmups: int, max_frames: int) -> None:
    """Time a single :func:`score_camera` call against a known-good camera.

    We feed the localizer's own locked camera back in so scoring hits the
    typical in-gameplay workload (vs. e.g. a deliberately off camera).
    """
    from modulabot.frame import compute_ignore_mask

    samples: list[float] = []
    localizer = Localizer(data.map)
    for i, frame in enumerate(frames[:max_frames]):
        if looks_like_interstitial(frame):
            continue
        bot = Bot(agent_id=0)
        # One scan + localize to seed a realistic camera + ignore mask.
        scan_all(bot, data.sprites, frame, data.map)
        localizer.update_location(bot, data.sprites, frame)
        if not bot.percep.localized:
            continue
        ignore = compute_ignore_mask(bot, data.sprites, frame)
        cx, cy = bot.percep.camera_x, bot.percep.camera_y
        if i < warmups:
            score_camera(frame, data.map.map_pixels, ignore, cx, cy)
            continue
        samples.append(
            _time_one(
                lambda f=frame, ig=ignore, x=cx, y=cy: score_camera(
                    f, data.map.map_pixels, ig, x, y
                )
            )
        )
    _report("localize.score_camera (single call)", samples)


def bench_update_location(frames: np.ndarray, data, warmups: int, max_frames: int) -> None:
    """Time the full localizer.update_location per non-interstitial frame.

    Measures the realistic cold + warm path together: fresh localizer +
    fresh bot for each frame so we don't accidentally benchmark the cached
    warm path only.
    """
    samples_warm: list[float] = []
    samples_cold: list[float] = []
    for i, frame in enumerate(frames[:max_frames]):
        if looks_like_interstitial(frame):
            continue
        localizer = Localizer(data.map)  # fresh → cold path on first call
        bot = Bot(agent_id=0)
        scan_all(bot, data.sprites, frame, data.map)
        if i < warmups:
            localizer.update_location(bot, data.sprites, frame)
            continue
        # Cold (first call on this fresh localizer).
        samples_cold.append(
            _time_one(lambda: localizer.update_location(bot, data.sprites, frame))
        )
        # Warm (second call on the same localizer; camera already locked).
        samples_warm.append(
            _time_one(lambda: localizer.update_location(bot, data.sprites, frame))
        )
    _report("localize.update_location (cold)", samples_cold)
    _report("localize.update_location (warm)", samples_warm)


def bench_voting_parse(data, warmups: int, iterations: int) -> None:
    """Time :func:`voting.parse_voting_screen` on a synthetic voting frame.

    No captured fixture contains a voting screen yet; use the synthetic
    builder shared with ``test_pixel_pipeline``. Two configurations:

    - ``empty`` — just the slot grid + SKIP label (no chat).
    - ``chat`` — same but with manually painted chat lines to exercise
      the OCR path (the slow bit on real voting frames).
    """
    # Empty-chat baseline.
    frame_empty = _build_voting_frame(data, 8, cursor_index=2)

    # Chat-heavy variant: paint chat lines ourselves so we don't need
    # to change the shared synthetic builder. Mirrors the sim-side
    # ``drawVoteChat`` layout (icon at VOTE_CHAT_ICON_X, text at
    # VOTE_CHAT_TEXT_X, one row every TextLineHeight pixels starting at
    # skip_y + 10).
    from modulabot import ascii as ascii_mod
    from modulabot.voting import VOTE_CHAT_ICON_X, VOTE_CHAT_TEXT_X
    from modulabot.data import SCREEN_HEIGHT

    frame_chat = frame_empty.copy()
    # Rough skip_y derivation — the builder paints SKIP below the grid.
    # Walk down from the grid and paint chat lines at 7-pixel intervals.
    line_y = 90
    for line in ("RED SUS", "CYAN IN ELEC", "BODY IN CAFE", "VOTE BLUE", "SKIP NO EVID"):
        pen = VOTE_CHAT_TEXT_X
        for ch in line:
            glyph = ascii_mod.glyph_at(data.font, ch)
            for py in range(glyph.height):
                for px in range(glyph.width):
                    if glyph.pixels[py, px]:
                        fy = line_y + py
                        fx = pen + px
                        if 0 <= fy < SCREEN_HEIGHT and 0 <= fx < 128:
                            frame_chat[fy, fx] = 2
            pen += ascii_mod.glyph_advance(data.font, ch)
        line_y += 7

    for label, frame in (("empty", frame_empty), ("chat", frame_chat)):
        samples: list[float] = []
        for i in range(iterations):
            bot = Bot(agent_id=0)
            if i < warmups:
                voting_mod.parse_voting_screen(bot, data.sprites, data.font, frame, 0)
                continue
            samples.append(
                _time_one(
                    lambda f=frame, b=bot: voting_mod.parse_voting_screen(
                        b, data.sprites, data.font, f, 0
                    )
                )
            )
        _report(f"voting.parse_voting_screen ({label})", samples)


def bench_end_to_end(frames: np.ndarray, data, warmups: int, max_frames: int) -> None:
    """Time the full :meth:`BotCore.step` per frame, split by phase.

    Reuses one ``BotCore`` across frames so motion / evidence /
    localisation-warm state carry over (matches tournament behaviour).
    """
    core = BotCore(agent_id=0, reference_data=data)
    playing: list[float] = []
    interstitial: list[float] = []
    for i, frame in enumerate(frames[:max_frames]):
        if i < warmups:
            core.step(frame)
            continue
        t = _time_one(lambda f=frame: core.step(f))
        if core.bot.percep.phase == Phase.PLAYING:
            playing.append(t)
        else:
            interstitial.append(t)
    _report("BotCore.step (playing)", playing)
    _report("BotCore.step (interstitial)", interstitial)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--fixtures",
        type=Path,
        default=_AMONG_THEM / "modulabot" / "tests" / "fixtures_frames.npy",
        help="Path to fixtures_frames.npy (default: tests bundle).",
    )
    parser.add_argument(
        "--warmups",
        type=int,
        default=3,
        help="Number of warmup frames/iterations to discard (default: 3).",
    )
    parser.add_argument(
        "--max-frames",
        type=int,
        default=275,
        help="Cap on frames per benchmark (default: 275, full fixture).",
    )
    parser.add_argument(
        "--voting-iterations",
        type=int,
        default=60,
        help="Iterations for the synthetic voting benchmark (default: 60).",
    )
    parser.add_argument(
        "--skip",
        nargs="*",
        default=(),
        choices=("scan", "score", "localize", "voting", "end_to_end"),
        help="Skip individual benchmarks.",
    )
    args = parser.parse_args()

    if not args.fixtures.exists():
        print(f"fixtures not found at {args.fixtures}", file=sys.stderr)
        return 1

    native_disabled = os.environ.get("MODULABOT_DISABLE_NATIVE")
    print(
        f"modulabot perception bench — "
        f"native={'disabled' if native_disabled else 'auto'}"
    )
    print(f"fixture: {args.fixtures}")
    frames = np.load(args.fixtures)
    data = load_reference_data()
    print(f"loaded {len(frames)} frames, {len(data.map.tasks)} tasks, "
          f"{len(data.sprites.player.pixels):,} player-sprite pixels")
    print()

    if "scan" not in args.skip:
        bench_scan_all(frames, data, args.warmups, args.max_frames)
    if "score" not in args.skip:
        bench_score_camera(frames, data, args.warmups, args.max_frames)
    if "localize" not in args.skip:
        bench_update_location(frames, data, args.warmups, args.max_frames)
    if "voting" not in args.skip:
        bench_voting_parse(data, args.warmups, args.voting_iterations)
    if "end_to_end" not in args.skip:
        bench_end_to_end(frames, data, args.warmups, args.max_frames)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
