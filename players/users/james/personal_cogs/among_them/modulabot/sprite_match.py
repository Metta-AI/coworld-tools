"""Sprite-matching primitives.

Port of ``sprite_match.nim``. Used by :mod:`modulabot.perception.actors`
(scan crewmates / bodies / ghosts / task icons / radar dots / HUD
role icon) and :mod:`modulabot.perception.tasks` (icon / radar).

All matchers take a ``(128, 128) uint8`` frame and a :class:`~modulabot.
data.Sprite`. They do not take ``Bot``; nothing here mutates state.

Miss budgets are kept here (rather than in :mod:`~modulabot.tuning`)
because they're internal to the matching algorithm and unlikely targets
for A/B testing at the policy level.

Three tiers of matcher live here:

- **Scalar / single-anchor** matchers (:func:`sprite_misses`,
  :func:`matches_crewmate`, :func:`matches_actor_sprite`, …). Used by
  ignore-pixel checks, single-HUD-slot matches
  (:func:`~modulabot.actors.update_role`), and any caller that only
  needs one anchor answered. Direct port of the Nim scalar matchers.
- **Vectorised / all-anchor** matchers
  (:func:`_match_actor_sprite_all_anchors_numpy`,
  :func:`_actor_color_index_all_anchors_numpy`). Pure-Python fallback
  kernels that sweep the sprite against every valid anchor in one
  numpy pass. Used when :mod:`modulabot.nim_perception` can't load
  its shared library (``HAVE_NATIVE=False``).
- **Native dispatchers** (:func:`match_actor_sprite_all_anchors`,
  :func:`actor_color_index_all_anchors`). Pick between the Nim FFI
  kernel (``HAVE_NATIVE=True``) and the numpy fallback; exported as
  the public API. See :mod:`modulabot.nim_perception` for the FFI.

Parity between all three tiers is pinned by
``tests/test_perception_snapshots.py::VectorisedParityTests`` and
``tests/test_nim_perception.py::SpriteMatchParityTests``.
"""

from __future__ import annotations

import numpy as np

from . import nim_perception as _nim_perception
from .data import (
    PLAYER_COLOR_COUNT,
    PLAYER_COLORS,
    SCREEN_HEIGHT,
    SCREEN_WIDTH,
    SHADE_TINT_COLOR,
    SHADOW_MAP,
    TINT_COLOR,
    TRANSPARENT_INDEX,
    Sprite,
)

# Miss budgets (ported from sprite_match.nim).
TASK_ICON_MAX_MISSES = 4
TASK_ICON_MAYBE_MISSES = 12
KILL_ICON_MAX_MISSES = 5
CREWMATE_MAX_MISSES = 8
CREWMATE_MIN_STABLE_PIXELS = 8
CREWMATE_MIN_BODY_PIXELS = 8


# ---------------------------------------------------------------------------
# Low-level match core
# ---------------------------------------------------------------------------


def sprite_misses(frame: np.ndarray, sprite: Sprite, x: int, y: int) -> tuple[int, int]:
    """Return ``(misses, opaque)`` for one sprite anchor against a frame.

    Matches ``spriteMisses`` in ``sprite_match.nim``. Non-transparent
    sprite pixels that fall off-screen count as misses.
    """
    misses = 0
    opaque = 0
    for sy in range(sprite.height):
        for sx in range(sprite.width):
            color = int(sprite.pixels[sy, sx])
            if color == TRANSPARENT_INDEX:
                continue
            opaque += 1
            fx = x + sx
            fy = y + sy
            if fx < 0 or fy < 0 or fx >= SCREEN_WIDTH or fy >= SCREEN_HEIGHT:
                misses += 1
            elif int(frame[fy, fx]) != color:
                misses += 1
    return misses, opaque


def matches_sprite(frame: np.ndarray, sprite: Sprite, x: int, y: int) -> bool:
    """Strict match (miss budget ≤ :data:`TASK_ICON_MAX_MISSES`)."""
    misses, opaque = sprite_misses(frame, sprite, x, y)
    return opaque > 0 and misses <= TASK_ICON_MAX_MISSES


def maybe_matches_sprite(frame: np.ndarray, sprite: Sprite, x: int, y: int) -> bool:
    """Loose match (miss budget ≤ :data:`TASK_ICON_MAYBE_MISSES`)."""
    misses, opaque = sprite_misses(frame, sprite, x, y)
    return opaque > 0 and misses <= TASK_ICON_MAYBE_MISSES


def matches_sprite_shadowed(frame: np.ndarray, sprite: Sprite, x: int, y: int) -> bool:
    """Match the sprite against its shadow-map variant.

    The sprite's pixels are compared via :data:`modulabot.data.SHADOW_MAP`
    before matching — used for HUD icons that render shadowed (e.g. the
    ghost icon when present).

    Early-exits once misses exceed :data:`KILL_ICON_MAX_MISSES`.
    """
    misses = 0
    opaque = 0
    for sy in range(sprite.height):
        for sx in range(sprite.width):
            color = int(sprite.pixels[sy, sx])
            if color == TRANSPARENT_INDEX:
                continue
            opaque += 1
            fx = x + sx
            fy = y + sy
            if fx < 0 or fy < 0 or fx >= SCREEN_WIDTH or fy >= SCREEN_HEIGHT:
                misses += 1
            elif int(frame[fy, fx]) != int(SHADOW_MAP[color & 0x0F]):
                misses += 1
            if misses > KILL_ICON_MAX_MISSES:
                return False
    return opaque > 0 and misses <= KILL_ICON_MAX_MISSES


# ---------------------------------------------------------------------------
# Palette helpers
# ---------------------------------------------------------------------------


def stable_crewmate_color(color: int) -> bool:
    """True for sprite pixels that don't vary by player tint.

    Those are the outline + visor pixels — the "stable" signal used as
    the bulk of the crewmate sprite matcher.
    """
    return color != TRANSPARENT_INDEX and color != TINT_COLOR and color != SHADE_TINT_COLOR


def player_body_color(color: int) -> bool:
    """True when a frame colour is plausibly a player tint (lit or shadowed)."""
    for pc in PLAYER_COLORS:
        ipc = int(pc)
        if color == ipc:
            return True
        if color == int(SHADOW_MAP[ipc & 0x0F]):
            return True
    return False


def player_color_index(color: int) -> int:
    """Return the tracked player-colour index for a palette colour, or -1.

    Does *not* match shadowed versions — only the lit tint. Used by
    :func:`crewmate_color_index` to count tint-pixel agreements.
    """
    for i, pc in enumerate(PLAYER_COLORS):
        if color == int(pc):
            return i
    return -1


def crewmate_pixel_matches(sprite_color: int, frame_color: int) -> bool:
    """True when one crewmate sprite pixel matches the frame.

    Tint pixels match any plausible body colour. Non-tint pixels match
    exactly.
    """
    if sprite_color == TINT_COLOR or sprite_color == SHADE_TINT_COLOR:
        return player_body_color(frame_color)
    return sprite_color == frame_color


# ---------------------------------------------------------------------------
# Crewmate / actor matchers
# ---------------------------------------------------------------------------


def crewmate_color_index(
    frame: np.ndarray, sprite: Sprite, x: int, y: int, flip_h: bool
) -> int:
    """Infer the most likely visible player colour at a crewmate anchor.

    Counts how many tint pixels agree with each player-colour palette
    index in the frame and returns the winner (-1 if no tint pixels line
    up).
    """
    counts = np.zeros(PLAYER_COLOR_COUNT, dtype=np.int32)
    for sy in range(sprite.height):
        for sx in range(sprite.width):
            src_x = sprite.width - 1 - sx if flip_h else sx
            color = int(sprite.pixels[sy, src_x])
            if color != TINT_COLOR:
                continue
            fx = x + sx
            fy = y + sy
            if fx < 0 or fy < 0 or fx >= SCREEN_WIDTH or fy >= SCREEN_HEIGHT:
                continue
            idx = player_color_index(int(frame[fy, fx]))
            if idx >= 0:
                counts[idx] += 1
    best = int(np.argmax(counts))
    return best if counts[best] > 0 else -1


def matches_crewmate(
    frame: np.ndarray, sprite: Sprite, x: int, y: int, flip_h: bool
) -> bool:
    """True when stable + body pixels both clear their floors at this anchor.

    Algorithm (verbatim from ``matchesCrewmate`` in ``sprite_match.nim``):
    count stable (outline/visor) hits and body (tint/shade) hits
    separately; early-exit if misses exceed :data:`CREWMATE_MAX_MISSES`;
    accept only if both stable and body hit counts clear
    :data:`CREWMATE_MIN_STABLE_PIXELS` / :data:`CREWMATE_MIN_BODY_PIXELS`.
    """
    body_matched = 0
    body_pixels = 0
    matched_stable = 0
    misses = 0
    stable_pixels = 0
    for sy in range(sprite.height):
        for sx in range(sprite.width):
            src_x = sprite.width - 1 - sx if flip_h else sx
            color = int(sprite.pixels[sy, src_x])
            if color == TRANSPARENT_INDEX:
                continue
            is_stable = stable_crewmate_color(color)
            if is_stable:
                stable_pixels += 1
            else:
                body_pixels += 1
            fx = x + sx
            fy = y + sy
            if fx < 0 or fy < 0 or fx >= SCREEN_WIDTH or fy >= SCREEN_HEIGHT:
                misses += 1
            elif crewmate_pixel_matches(color, int(frame[fy, fx])):
                if is_stable:
                    matched_stable += 1
                else:
                    body_matched += 1
            else:
                misses += 1
            if misses > CREWMATE_MAX_MISSES:
                return False
    return (
        stable_pixels >= CREWMATE_MIN_STABLE_PIXELS
        and matched_stable >= CREWMATE_MIN_STABLE_PIXELS
        and body_pixels >= CREWMATE_MIN_BODY_PIXELS
        and body_matched >= CREWMATE_MIN_BODY_PIXELS
    )


def matches_actor_sprite(
    frame: np.ndarray,
    sprite: Sprite,
    x: int,
    y: int,
    flip_h: bool,
    max_misses: int,
    min_stable_pixels: int,
    min_tint_pixels: int,
) -> bool:
    """Generalised crewmate matcher with caller-provided budgets.

    Used for body and ghost sprites, which have different stable/tint
    pixel proportions than the player sprite.
    """
    tint_matched = 0
    tint_pixels = 0
    stable_matched = 0
    misses = 0
    stable_pixels = 0
    for sy in range(sprite.height):
        for sx in range(sprite.width):
            src_x = sprite.width - 1 - sx if flip_h else sx
            color = int(sprite.pixels[sy, src_x])
            if color == TRANSPARENT_INDEX:
                continue
            is_stable = stable_crewmate_color(color)
            if is_stable:
                stable_pixels += 1
            else:
                tint_pixels += 1
            fx = x + sx
            fy = y + sy
            if fx < 0 or fy < 0 or fx >= SCREEN_WIDTH or fy >= SCREEN_HEIGHT:
                misses += 1
            elif crewmate_pixel_matches(color, int(frame[fy, fx])):
                if is_stable:
                    stable_matched += 1
                else:
                    tint_matched += 1
            else:
                misses += 1
            if misses > max_misses:
                return False
    return (
        stable_pixels >= min_stable_pixels
        and stable_matched >= min_stable_pixels
        and tint_pixels >= min_tint_pixels
        and tint_matched >= min_tint_pixels
    )


def actor_color_index(
    frame: np.ndarray, sprite: Sprite, x: int, y: int, flip_h: bool
) -> int:
    """Infer tint colour for a body / ghost match. Same logic as
    :func:`crewmate_color_index`."""
    return crewmate_color_index(frame, sprite, x, y, flip_h)


__all__ = [
    "TASK_ICON_MAX_MISSES",
    "TASK_ICON_MAYBE_MISSES",
    "KILL_ICON_MAX_MISSES",
    "CREWMATE_MAX_MISSES",
    "CREWMATE_MIN_STABLE_PIXELS",
    "CREWMATE_MIN_BODY_PIXELS",
    "sprite_misses",
    "matches_sprite",
    "maybe_matches_sprite",
    "matches_sprite_shadowed",
    "stable_crewmate_color",
    "player_body_color",
    "player_color_index",
    "crewmate_pixel_matches",
    "matches_crewmate",
    "crewmate_color_index",
    "matches_actor_sprite",
    "actor_color_index",
    "match_actor_sprite_all_anchors",
    "actor_color_index_all_anchors",
]


# ---------------------------------------------------------------------------
# Vectorised all-anchor matchers
# ---------------------------------------------------------------------------
#
# These replace the O(anchors × sprite_pixels) scalar-Python scan loop
# used by :mod:`modulabot.actors` with an O(sprite_pixels) number of
# numpy-broadcast operations — each one processes every anchor in the
# frame simultaneously. On a 128×128 frame scanning a 12×12 sprite,
# there are 117×117 = 13,689 candidate anchors and ~60–100 opaque sprite
# pixels; Python-per-anchor loops spend most of their time in the
# interpreter. The numpy version hits the CPU cache instead.
#
# The semantics are identical to running :func:`matches_actor_sprite`
# scalar-wise at every anchor, verified by side-by-side equivalence
# tests.


def _body_color_lookup() -> np.ndarray:
    """16-entry boolean lookup: ``lut[c]`` True iff palette index ``c``
    plausibly represents a player body (lit or shadowed tint).

    Matches :func:`player_body_color` for every palette index. Computed
    once per module import; the vectorised matchers index into it via
    ``lut[frame_slice]`` which is a single numpy fancy-index.
    """
    lut = np.zeros(16, dtype=bool)
    for pc in PLAYER_COLORS:
        lut[int(pc) & 0x0F] = True
        lut[int(SHADOW_MAP[int(pc) & 0x0F]) & 0x0F] = True
    return lut


_BODY_COLOR_LOOKUP = _body_color_lookup()


def _oriented_pixels(sprite: Sprite, flip_h: bool) -> np.ndarray:
    """Return the sprite's pixels, reflected horizontally if ``flip_h``.

    The scalar path reflects by indexing ``sprite.pixels[sy, sw-1-sx]``
    on the fly. Precomputing once is cheap (12×12) and lets the
    vectorised path iterate the reflected sprite pixel by pixel.
    """
    if flip_h:
        return np.ascontiguousarray(sprite.pixels[:, ::-1])
    return sprite.pixels


def match_actor_sprite_all_anchors(
    frame: np.ndarray,
    sprite: Sprite,
    flip_h: bool,
    *,
    max_misses: int,
    min_stable_pixels: int,
    min_tint_pixels: int,
) -> np.ndarray:
    """Public dispatcher: Nim FFI when available, numpy fallback otherwise.

    Shape / dtype / semantics are exactly as documented on
    :func:`_match_actor_sprite_all_anchors_numpy` — both kernels are
    pinned to agree pixel-for-pixel on the 275-frame fixture
    (``tests/test_nim_perception.py::SpriteMatchParityTests``).

    Callers in :mod:`modulabot.actors` never check ``HAVE_NATIVE``
    themselves — this dispatcher is the single decision point. That
    keeps the fallback behaviour consistent across the codebase and
    makes ``MODULABOT_DISABLE_NATIVE=1`` a one-switch rollback.
    """
    if _nim_perception.HAVE_NATIVE:
        return _nim_perception.match_actor_sprite_all(
            frame,
            sprite.pixels,
            flip_h,
            max_misses=max_misses,
            min_stable_pixels=min_stable_pixels,
            min_tint_pixels=min_tint_pixels,
        )
    return _match_actor_sprite_all_anchors_numpy(
        frame, sprite, flip_h,
        max_misses=max_misses,
        min_stable_pixels=min_stable_pixels,
        min_tint_pixels=min_tint_pixels,
    )


def actor_color_index_all_anchors(
    frame: np.ndarray,
    sprite: Sprite,
    flip_h: bool,
) -> np.ndarray:
    """Public dispatcher: Nim FFI when available, numpy fallback otherwise.

    Shape / dtype / semantics match
    :func:`_actor_color_index_all_anchors_numpy` byte-for-byte.
    """
    if _nim_perception.HAVE_NATIVE:
        return _nim_perception.actor_color_index_all(
            frame, sprite.pixels, flip_h,
        )
    return _actor_color_index_all_anchors_numpy(frame, sprite, flip_h)


def _match_actor_sprite_all_anchors_numpy(
    frame: np.ndarray,
    sprite: Sprite,
    flip_h: bool,
    *,
    max_misses: int,
    min_stable_pixels: int,
    min_tint_pixels: int,
) -> np.ndarray:
    """Pure-Python numpy fallback for :func:`match_actor_sprite_all_anchors`.

    Kept so ``MODULABOT_DISABLE_NATIVE=1`` still produces correct (if
    slower) results. Also serves as the parity oracle in
    ``tests/test_nim_perception.py``.

    Returns a ``(max_y, max_x) bool`` array where ``max_y = SCREEN_HEIGHT
    - sprite.height + 1`` and similarly for ``max_x``. ``True`` at
    ``(y, x)`` means the sprite matches at that top-left anchor under
    the given miss / stable / body budgets.

    Semantics are 1:1 with running :func:`matches_actor_sprite` at every
    anchor:

    - **Stable** sprite pixels (neither ``TINT_COLOR`` nor
      ``SHADE_TINT_COLOR``; not transparent) must match the frame
      exactly.
    - **Tint** sprite pixels (``TINT_COLOR`` / ``SHADE_TINT_COLOR``)
      match any plausible player body colour (lit or shadowed, via
      :data:`_BODY_COLOR_LOOKUP`).
    - An anchor is rejected if cumulative misses exceed ``max_misses``,
      or if either the matched-stable or matched-tint count falls below
      its floor.

    Unlike the scalar matcher this does not early-exit per-anchor — the
    miss-budget check is applied at the end. That's fine: numpy
    vectorised ops are bound by memory bandwidth, not instruction
    count, so the per-anchor "wasted" comparisons are free compared
    with the interpreter overhead the scalar matcher pays. For a 12×12
    sprite on a 128×128 frame the whole pass is ~1-2 ms in Python.
    """
    sh, sw = sprite.height, sprite.width
    max_y = SCREEN_HEIGHT - sh + 1
    max_x = SCREEN_WIDTH - sw + 1

    oriented = _oriented_pixels(sprite, flip_h)

    matched_stable = np.zeros((max_y, max_x), dtype=np.int32)
    matched_tint = np.zeros((max_y, max_x), dtype=np.int32)
    misses = np.zeros((max_y, max_x), dtype=np.int32)

    stable_pixels = 0
    tint_pixels = 0

    for sy in range(sh):
        for sx in range(sw):
            color = int(oriented[sy, sx])
            if color == TRANSPARENT_INDEX:
                continue
            frame_slice = frame[sy : sy + max_y, sx : sx + max_x]
            if color == TINT_COLOR or color == SHADE_TINT_COLOR:
                tint_pixels += 1
                matched_here = _BODY_COLOR_LOOKUP[frame_slice]
                matched_tint += matched_here
            else:
                stable_pixels += 1
                matched_here = frame_slice == color
                matched_stable += matched_here
            misses += ~matched_here

    return (
        (misses <= max_misses)
        & (matched_stable >= min_stable_pixels)
        & (stable_pixels >= min_stable_pixels)
        & (matched_tint >= min_tint_pixels)
        & (tint_pixels >= min_tint_pixels)
    )


def _actor_color_index_all_anchors_numpy(
    frame: np.ndarray,
    sprite: Sprite,
    flip_h: bool,
) -> np.ndarray:
    """Pure-Python numpy fallback for :func:`actor_color_index_all_anchors`.

    Kept so ``MODULABOT_DISABLE_NATIVE=1`` still produces correct (if
    slower) results. Also serves as the parity oracle in
    ``tests/test_nim_perception.py``.

    Returns a ``(max_y, max_x) int8`` array. ``-1`` at ``(y, x)`` means
    no lit-tint pixels voted for any player colour at that anchor;
    otherwise the value is the index into :data:`~modulabot.data.
    PLAYER_COLORS` with the highest vote count (ties broken by lower
    index, matching numpy ``argmax``).

    Semantics match :func:`crewmate_color_index` run at every anchor.
    Caller is responsible for only reading this array at positions
    where :func:`match_actor_sprite_all_anchors` returned ``True``.
    """
    sh, sw = sprite.height, sprite.width
    max_y = SCREEN_HEIGHT - sh + 1
    max_x = SCREEN_WIDTH - sw + 1

    oriented = _oriented_pixels(sprite, flip_h)

    # Per-player-colour hit counts, stacked on axis 0.
    counts = np.zeros((PLAYER_COLOR_COUNT, max_y, max_x), dtype=np.int32)
    for sy in range(sh):
        for sx in range(sw):
            if int(oriented[sy, sx]) != TINT_COLOR:
                continue
            frame_slice = frame[sy : sy + max_y, sx : sx + max_x]
            # Compare this sprite tint pixel against each tracked player
            # colour. Only lit (not shadowed) matches count, matching
            # the scalar `player_color_index` semantics.
            for p_idx, pc in enumerate(PLAYER_COLORS):
                counts[p_idx] += frame_slice == int(pc)

    best_idx = counts.argmax(axis=0).astype(np.int8)
    best_votes = counts.max(axis=0)
    best_idx[best_votes == 0] = -1
    return best_idx
