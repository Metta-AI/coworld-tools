"""Sprite-matching kernels. Port of
``users/james/personal_cogs/among_them/common/perception_kernels/sprite_match.nim``.

Two public procs, names mirrored 1:1 to the Nim symbols (snake_cased) so the
parity rig can assert symbol-by-symbol equality:

- :func:`match_actor_sprite_all` -- all-anchors sprite match under
  stable/tint/transparent/budget semantics.
- :func:`actor_color_index_all` -- per-anchor dominant-tint player-color
  index (or -1 if no tint pixel voted).

Numpy-first per PLAN section 5.3. Both kernels use ``sliding_window_view``
to materialise per-anchor patches, then broadcast over the sprite mask.
Numba is intentionally left off and is only promoted if measurement under
``tests/test_sprite_match.py`` shows the perf budget breached.
"""

from __future__ import annotations

import numpy as np
from numpy.lib.stride_tricks import sliding_window_view

from .data.palette import (
    SHADE_TINT_COLOR,
    TINT_COLOR,
    TRANSPARENT_INDEX,
)
from .frame import SCREEN_HEIGHT, SCREEN_WIDTH

# Player color slots -> lit palette index. Must match
# ``sim.nim``'s ``PlayerColors`` and
# ``common/perception_kernels/sprite_match.nim``'s ``PlayerColors``. The
# 16 slots cover every PICO-8 palette entry exactly once (a permutation),
# which has implications for ``actor_color_index_all`` -- see below.
PLAYER_COLORS: np.ndarray = np.array(
    [3, 7, 8, 14, 4, 11, 13, 15, 1, 2, 5, 6, 9, 10, 12, 0], dtype=np.uint8
)
PLAYER_COLORS.flags.writeable = False

# Palette index -> shadowed variant. Mirrors ``sim.nim``'s ``ShadowMap``.
SHADOW_MAP: np.ndarray = np.array(
    [0, 12, 9, 5, 5, 0, 5, 5, 5, 12, 9, 9, 0, 12, 12, 9], dtype=np.uint8
)
SHADOW_MAP.flags.writeable = False


def _build_player_body_lut() -> np.ndarray:
    """256-entry bool LUT: index ``c`` is True iff ``c`` is a plausible
    player-body palette index (lit color OR its shadowed variant).

    Mirrors ``isPlayerBodyColor`` in the Nim kernel. The Nim version does a
    linear scan over PlayerColors per pixel; numpy prefers a precomputed LUT
    for SIMD-friendly indexing.
    """
    lut = np.zeros(256, dtype=bool)
    for pc in PLAYER_COLORS:
        lut[int(pc)] = True
        lut[int(SHADOW_MAP[int(pc) & 0x0F])] = True
    return lut


PLAYER_BODY_LUT: np.ndarray = _build_player_body_lut()
PLAYER_BODY_LUT.flags.writeable = False


def _build_palette_to_slot() -> np.ndarray:
    """256-entry LUT: palette index -> player-color slot.

    ``PLAYER_COLORS`` maps slot -> palette index; this is the inverse on
    the lit-color path. Used by :func:`actor_color_index_all` to convert
    per-tint frame samples into slot indices in one shot before the
    per-anchor histogram. Palette indices outside the 0..15 range map to
    a sentinel slot (``PLAYER_COLORS.size`` == 16) that drops out of the
    argmax via ``minlength``.
    """
    lut = np.full(256, PLAYER_COLORS.size, dtype=np.int64)
    for slot, c in enumerate(PLAYER_COLORS):
        lut[int(c)] = slot
    return lut


_PALETTE_TO_SLOT: np.ndarray = _build_palette_to_slot()
_PALETTE_TO_SLOT.flags.writeable = False


def match_actor_sprite_all(
    frame: np.ndarray,
    sprite: np.ndarray,
    flip_h: bool,
    max_misses: int,
    min_stable: int,
    min_tint: int,
) -> np.ndarray:
    """Vectorised all-anchors sprite match.

    Returns a ``(max_y, max_x)`` ``uint8`` 0/1 mask where
    ``max_y = SCREEN_HEIGHT - sh + 1`` and similarly for x. ``out[ay, ax] == 1``
    iff sprite anchored at ``(ay, ax)`` clears the budgets.

    Semantics (per anchor, mirroring the upstream Nim kernel):

    - **Stable** sprite pixels (not transparent, not tint, not shade-tint):
      must match the frame palette index exactly.
    - **Tint** sprite pixels (tint OR shade-tint): match if the frame pixel
      is any plausible player-body color (lit OR shadowed).
    - **Transparent** sprite pixels are ignored.
    - Anchor accepts iff ``misses <= max_misses`` AND
      ``matched_stable >= min_stable`` AND ``matched_tint >= min_tint``.

    Pre-flight short-circuit: if the sprite simply doesn't have enough
    stable / tint pixels to clear the floor, the whole sweep is skipped and
    the output is all-zero (matching the Nim early-out).
    """
    frame = np.asarray(frame, dtype=np.uint8)
    sprite = np.asarray(sprite, dtype=np.uint8)
    if flip_h:
        sprite = np.ascontiguousarray(sprite[:, ::-1])

    sh, sw = sprite.shape
    max_y = SCREEN_HEIGHT - sh + 1
    max_x = SCREEN_WIDTH - sw + 1
    if max_y <= 0 or max_x <= 0:
        return np.zeros((max(0, max_y), max(0, max_x)), dtype=np.uint8)

    transparent = sprite == TRANSPARENT_INDEX
    tint = (sprite == TINT_COLOR) | (sprite == SHADE_TINT_COLOR)
    stable = ~transparent & ~tint
    stable_positions = np.argwhere(stable)  # (n_stable, 2)
    tint_positions = np.argwhere(tint)      # (n_tint, 2)
    total_stable = stable_positions.shape[0]
    total_tint = tint_positions.shape[0]
    if total_stable < min_stable or total_tint < min_tint:
        return np.zeros((max_y, max_x), dtype=np.uint8)

    # (max_y, max_x, sh, sw) view onto frame; no copy.
    windows = sliding_window_view(frame, (sh, sw))

    # Extract per-anchor frame patches just at the sprite positions we care
    # about. n_stable + n_tint is typically ~60-80 out of sh*sw=144; doing
    # full-window comparisons here cost ~2x in benchmarks because the bool
    # AND with the sprite mask kept allocating (max_y, max_x, sh, sw) bool
    # buffers. This formulation hits only the elements we actually consume.
    sprite_stable_vals = sprite[stable_positions[:, 0], stable_positions[:, 1]]
    windows_stable = windows[:, :, stable_positions[:, 0], stable_positions[:, 1]]
    matched_stable = (windows_stable == sprite_stable_vals).sum(axis=-1)

    windows_tint = windows[:, :, tint_positions[:, 0], tint_positions[:, 1]]
    matched_tint = PLAYER_BODY_LUT[windows_tint].sum(axis=-1)
    misses = (total_stable - matched_stable) + (total_tint - matched_tint)

    accept = (
        (misses <= max_misses)
        & (matched_stable >= min_stable)
        & (matched_tint >= min_tint)
    )
    return accept.astype(np.uint8)


def actor_color_index_all(
    frame: np.ndarray,
    sprite: np.ndarray,
    flip_h: bool,
) -> np.ndarray:
    """Per-anchor dominant-tint color index.

    Returns a ``(max_y, max_x)`` ``int8`` array. ``out[ay, ax]`` is the
    index into ``PLAYER_COLORS`` that received the most tint-pixel votes
    at that anchor, or ``-1`` if no tint pixel voted.

    Mirrors ``mb_actor_color_index_all``. Important asymmetry with
    :func:`match_actor_sprite_all`: only sprite pixels equal to
    ``TINT_COLOR`` (the lit tint, palette 3) trigger color votes;
    ``SHADE_TINT_COLOR`` (palette 9) does **not** vote.

    Frame pixels also only count if they're a lit player color
    (``PLAYER_COLORS[i]``). Shadowed variants do not vote -- that's the
    asymmetry on the *frame* side that matches the upstream Nim.

    Ties are broken by lowest index, matching ``np.argmax`` default.
    """
    frame = np.asarray(frame, dtype=np.uint8)
    sprite = np.asarray(sprite, dtype=np.uint8)
    if flip_h:
        sprite = np.ascontiguousarray(sprite[:, ::-1])

    sh, sw = sprite.shape
    max_y = SCREEN_HEIGHT - sh + 1
    max_x = SCREEN_WIDTH - sw + 1
    if max_y <= 0 or max_x <= 0:
        return np.zeros((max(0, max_y), max(0, max_x)), dtype=np.int8)

    tint_positions = np.argwhere(sprite == TINT_COLOR)  # (n_tint, 2)
    if tint_positions.shape[0] == 0:
        return np.full((max_y, max_x), -1, dtype=np.int8)

    windows = sliding_window_view(frame, (sh, sw))
    # Pull just the tint-pixel frame samples per anchor: shape
    # (max_y, max_x, n_tint). n_tint ~ 30 vs sh*sw=144 for the player
    # sprite, so this is much cheaper than running 16 full-window compares.
    tint_frame = windows[:, :, tint_positions[:, 0], tint_positions[:, 1]]

    # Map every sampled palette index to its lit player-color slot in a
    # single LUT pass, then build the per-anchor histogram via bincount
    # on a flattened (anchor_idx, slot) composite index. This avoids 16
    # boolean comparisons / sums on the (max_y, max_x, n_tint) array and
    # is the meaningful perf win for the kernel.
    n_anchors = max_y * max_x
    n_slots = PLAYER_COLORS.size  # 16
    slots = _PALETTE_TO_SLOT[tint_frame]  # (max_y, max_x, n_tint), int64 in [0, 16]
    anchor_offsets = np.arange(n_anchors, dtype=np.int64).reshape(max_y, max_x, 1)
    # (n_slots + 1) to give the out-of-range sentinel a parking slot.
    flat_idx = (anchor_offsets * (n_slots + 1) + slots).ravel()
    counts_flat = np.bincount(flat_idx, minlength=n_anchors * (n_slots + 1))
    counts = counts_flat.reshape(max_y, max_x, n_slots + 1)[..., :n_slots]

    best = counts.argmax(axis=-1).astype(np.int8)
    no_vote = counts.sum(axis=-1) == 0
    best[no_vote] = -1
    return best
