"""Pixel-observation fallback perception.

A minimal pixel path used when callers don't supply a
``ReferenceData`` bundle. Doesn't run in tournament play — the
production pipeline is :mod:`modulabot.perception.pixel_pipeline`,
which has full sprite matching, camera localization, voting parser,
task-icon scanning, and the radar/checkout/icon-miss machinery
documented in ``CREWMATE_TASK_FIX_PLAN.md``.

This module implements just enough pixel reasoning to keep tests
moving when those heavy dependencies are unavailable:

- Interstitial detection (≥30% black pixels ⇒ voting/result screen).
- Radar-dot direction: scan the screen periphery for the task-radar
  palette colour and aim toward its centroid.
- Kill-icon detection: a corner-of-HUD heuristic. If the kill icon
  is on, we're an imposter.

Everything else (player positions, bodies, tasks-in-view) stays
empty when we take this fallback path. Policies must tolerate that —
see :meth:`modulabot.policies.base.Policy.fallback_action`.
"""

from __future__ import annotations

import numpy as np

from ..state import Bot, Phase, Point, Role
from ..tuning import (
    INTERSTITIAL_BLACK_PERCENT,
    KILL_ICON_SIZE,
    KILL_ICON_X,
    KILL_ICON_Y,
    RADAR_MARGIN,
    SCREEN_HEIGHT,
    SCREEN_WIDTH,
    TASK_RADAR_COLOR,
)


def update_from_pixel_obs(bot: Bot, observation: np.ndarray) -> None:
    frame = _latest_pixel_frame(observation)
    percep = bot.percep

    percep.interstitial = _looks_like_interstitial(frame)
    percep.phase = Phase.INTERSTITIAL if percep.interstitial else Phase.PLAYING
    percep.interstitial_text = ""
    percep.localized = False  # pixel path doesn't run localization
    percep.task_progress = 0.0
    percep.players.clear()
    percep.bodies.clear()
    percep.tasks.clear()

    percep.kill_icon_visible = _looks_like_kill_icon(frame)
    if percep.kill_icon_visible and bot.role != Role.IMPOSTER:
        bot.role = Role.IMPOSTER

    percep.radar_target = _radar_target(frame)


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


def _latest_pixel_frame(observation: np.ndarray) -> np.ndarray:
    """Return the most recent (H, W) uint8 indexed frame."""
    if observation.ndim == 4:
        return observation[-1, -1, :, :]
    if observation.ndim == 3:
        return observation[-1, :, :]
    if observation.ndim == 2:
        if observation.shape == (SCREEN_HEIGHT, SCREEN_WIDTH):
            return observation
        # Packed 4-bit frames: (frame_stack, packed_bytes). Take last, unpack.
        if observation.shape[1] * 2 == SCREEN_HEIGHT * SCREEN_WIDTH:
            return _unpack_packed(observation[-1])
    if observation.ndim == 1 and observation.shape[0] * 2 == SCREEN_HEIGHT * SCREEN_WIDTH:
        return _unpack_packed(observation)
    raise ValueError(f"pixel observation shape {observation.shape} not understood")


def _unpack_packed(packed: np.ndarray) -> np.ndarray:
    pixels = np.empty(packed.shape[0] * 2, dtype=np.uint8)
    pixels[0::2] = packed & 0x0F
    pixels[1::2] = packed >> 4
    return pixels.reshape(SCREEN_HEIGHT, SCREEN_WIDTH)


def _looks_like_interstitial(frame: np.ndarray) -> bool:
    return int(np.count_nonzero(frame == 0)) * 100 >= INTERSTITIAL_BLACK_PERCENT * frame.size


def _looks_like_kill_icon(frame: np.ndarray) -> bool:
    icon = frame[
        KILL_ICON_Y : KILL_ICON_Y + KILL_ICON_SIZE,
        KILL_ICON_X : KILL_ICON_X + KILL_ICON_SIZE,
    ]
    # The kill-button sprite uses a mix of reds/oranges/blues from the
    # PICO-8 palette; matching *any* of those saturated colours is enough
    # to avoid most false positives from map decoration.
    sat = (icon == 8) | (icon == 2) | (icon == 4)
    return int(np.count_nonzero(sat)) >= 10


def _radar_target(frame: np.ndarray) -> Point | None:
    task_pixels = frame == TASK_RADAR_COLOR
    periphery = np.zeros_like(task_pixels)
    periphery[:RADAR_MARGIN, :] = True
    periphery[-RADAR_MARGIN:, :] = True
    periphery[:, :RADAR_MARGIN] = True
    periphery[:, -RADAR_MARGIN:] = True
    ys, xs = np.nonzero(task_pixels & periphery)
    if xs.size == 0:
        return None
    return Point(x=int(np.mean(xs)), y=int(np.mean(ys)))
