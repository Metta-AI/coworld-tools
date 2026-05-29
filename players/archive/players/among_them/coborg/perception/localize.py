"""Camera localization. Port of
``users/james/personal_cogs/among_them/guided_bot/perception/localize.nim``
plus the shared kernels in
``users/james/personal_cogs/among_them/common/perception_kernels/localize.nim``.

The localizer finds the camera offset ``(camera_x, camera_y)`` such that
the on-screen map pixels best match the static baked map. Three tiers,
tried in order:

1. **Local refit** — try last frame's camera; if it doesn't fit, sweep
   a 17x17 window around it. Cheap.
2. **Patch-hash global search** — hash 256 frame patches, vote each
   against a pre-built map-patch index, full-frame rescore the top 16
   candidates. The heavy hammer; recovers from any camera position.
3. **Spiral fallback** — last resort. Spirals outward from the best
   seed up to 48 px radius.

Match semantics: a non-ignored frame pixel "matches" if it equals the
map pixel at the corresponding camera offset OR the shadow-map variant
of that map pixel. Off-map pixels in the map slice are filled with
``MAP_VOID_COLOR`` (palette 12). Score formula:
``compared - errors * SCREEN_WIDTH`` (or ``-errors`` over budget);
higher is better. Acceptance: ``errors <= max_errors AND compared >=
FRAME_FIT_MIN_COMPARED``.

**Pythonic departures from the upstream Nim:** the per-pixel scoring
loop collapses from ~30 lines of Nim to ~5 lines of numpy boolean
broadcast (see :func:`score_camera`). I evaluated a batched form
that scores N candidates in one numpy expression; benchmarks showed
it was consistently 2-3x **slower** than the sequential per-candidate
form across N from 1 to 289 (the tier-1 worst case). Reason: the
(N, H, W) intermediate tensors blow out L2 cache while the
per-candidate form keeps (H, W) intermediates in L1. Sequential
wins. The orchestrator therefore calls :func:`score_camera` once
per candidate.

State threading: the orchestrator's :class:`LocalizerState` holds the
camera fields the bridge / belief layer reads each tick.
:func:`update_location` returns a fresh state derived from the prior
one (functional shape), so callers can rewind by re-binding their
state reference.
"""

from __future__ import annotations

import functools
from dataclasses import dataclass, replace
from enum import Enum

import numpy as np

from .data import MAP_VOID_COLOR, SHADOW_MAP, load_map_pixels
from .frame import SCREEN_HEIGHT, SCREEN_WIDTH
from .geometry import (
    button_camera_x,
    button_camera_y,
    camera_can_hold_player,
    camera_height,
    camera_width,
    camera_x_for_world,
    camera_y_for_world,
    max_camera_x,
    max_camera_y,
    min_camera_x,
    min_camera_y,
    player_world_x,
    player_world_y,
)


# --- localization constants (mirror upstream localize.nim) ---------------

# Max per-frame mismatches the global search will accept on a lock.
FULL_FRAME_FIT_MAX_ERRORS: int = 420
# Max per-frame mismatches the cheap local refit will accept.
LOCAL_FRAME_FIT_MAX_ERRORS: int = 320
# Minimum non-ignored opaque pixels for a score to be trusted. Guards
# against degenerate "everything is ignored" frames.
FRAME_FIT_MIN_COMPARED: int = 12000
# Local refit search half-extent (square window of 17x17).
LOCAL_FRAME_SEARCH_RADIUS: int = 8

# Patch geometry. Must agree with upstream `kLocalize.PatchSize` (=8).
PATCH_SIZE: int = 8
PATCH_GRID_W: int = SCREEN_WIDTH // PATCH_SIZE   # 16
PATCH_GRID_H: int = SCREEN_HEIGHT // PATCH_SIZE  # 16
PATCH_TOTAL_COUNT: int = PATCH_GRID_W * PATCH_GRID_H  # 256

# FNV-style hash constants. The base is the 32-bit FNV prime widened to
# uint64; the seed is the standard 64-bit FNV offset basis (0xCBF29CE484222325).
# uint64 arithmetic wraps mod 2^64 in both numpy and Nim.
PATCH_HASH_BASE: np.uint64 = np.uint64(16777619)
PATCH_HASH_SEED: np.uint64 = np.uint64(0xCBF29CE484222325)

# Skip frame patches whose hash matches more than this many map entries
# — too ambiguous (large featureless regions like floor tiles).
PATCH_MAX_MATCHES: int = 4096
# Keep this many top-voted candidates for full-frame scoring.
PATCH_TOP_CANDIDATES: int = 16
# Minimum patch votes for a camera offset to be considered.
PATCH_MIN_VOTES: int = 3

# Maximum spiral search radius in pixels. See upstream comment block in
# localize.nim — 48 px caps the worst-case spiral at ~10 ms.
SPIRAL_MAX_RADIUS: int = 48


# --- types ----------------------------------------------------------------


@dataclass
class CameraScore:
    """Result of one :func:`score_camera` call. Same shape as upstream
    `CameraScore` in localize.nim. ``score`` is the rank value (higher
    is better, ``compared - errors * SCREEN_WIDTH`` in budget else
    ``-errors``); ``errors`` and ``compared`` are pixel counts."""

    score: int
    errors: int
    compared: int


_NO_SCORE = CameraScore(score=-(1 << 30), errors=(1 << 30), compared=0)


class CameraLock(Enum):
    """Provenance of the most recent camera lock. Mirrors upstream
    `CameraLock`. String values are lowercase so sidecars are
    human-readable."""

    NO_LOCK = "no_lock"
    LOCAL_FRAME_MAP_LOCK = "local_frame_map_lock"
    FRAME_MAP_LOCK = "frame_map_lock"


@dataclass
class Candidate:
    """One patch-vote candidate. Output of
    :func:`vote_camera_candidates`."""

    cx: int
    cy: int
    votes: int


@dataclass
class LocalizerState:
    """All camera-related state threaded across frames. The belief layer
    (P2) will compose this with the rest of the bot's perception state;
    here it stands alone so the localizer can be exercised in isolation
    by tests and the parity rig."""

    camera_x: int = 0
    camera_y: int = 0
    camera_score: int = 0
    camera_lock: CameraLock = CameraLock.NO_LOCK
    localized: bool = False
    last_localized_tick: int = -1
    last_camera_x: int = 0
    last_camera_y: int = 0
    home_x: int = 0
    home_y: int = 0
    home_set: bool = False
    game_started: bool = False
    self_x: int = 0
    self_y: int = 0


# --- padded map helper (shared by score_camera + score_cameras_batched) --


def _padded_map(map_pixels: np.ndarray) -> np.ndarray:
    """Return the map padded with :data:`MAP_VOID_COLOR` by
    (SCREEN_HEIGHT, SCREEN_WIDTH) on all sides. Lazily cached at module
    scope keyed on ``map_pixels`` identity — :func:`load_map_pixels` is
    ``lru_cache``-stable so the same ndarray is returned each call, and
    the cache key stays stable through normal use."""
    cached = getattr(_padded_map, "_cache", None)
    if cached is not None and cached[0] is map_pixels:
        return cached[1]
    h, w = map_pixels.shape
    padded = np.full(
        (h + 2 * SCREEN_HEIGHT, w + 2 * SCREEN_WIDTH),
        MAP_VOID_COLOR,
        dtype=np.uint8,
    )
    padded[SCREEN_HEIGHT : SCREEN_HEIGHT + h, SCREEN_WIDTH : SCREEN_WIDTH + w] = map_pixels
    padded.flags.writeable = False
    _padded_map._cache = (map_pixels, padded)  # type: ignore[attr-defined]
    return padded


def _map_slice(map_pixels: np.ndarray, cx: int, cy: int) -> np.ndarray:
    """Return the (SCREEN_HEIGHT, SCREEN_WIDTH) slice of ``map_pixels``
    anchored at ``(cx, cy)``, with off-map pixels filled with
    :data:`MAP_VOID_COLOR`. Uses the padded-map cache so the common
    case (camera inside the legal range) falls out of a single
    view-only slice.

    For pathological cameras outside the padded range, returns an
    all-:data:`MAP_VOID_COLOR` slice. The orchestrator never asks for
    those, but the public function is exposed so we make it total."""
    padded = _padded_map(map_pixels)
    ph, pw = padded.shape
    py = cy + SCREEN_HEIGHT
    px = cx + SCREEN_WIDTH
    if py < 0 or px < 0 or py + SCREEN_HEIGHT > ph or px + SCREEN_WIDTH > pw:
        return np.full((SCREEN_HEIGHT, SCREEN_WIDTH), MAP_VOID_COLOR, dtype=np.uint8)
    return padded[py : py + SCREEN_HEIGHT, px : px + SCREEN_WIDTH]


# --- score_camera + score_cameras_batched --------------------------------


def score_camera(
    frame: np.ndarray,
    map_pixels: np.ndarray,
    ignore_mask: np.ndarray,
    cx: int,
    cy: int,
    max_errors: int = FULL_FRAME_FIT_MAX_ERRORS,
) -> CameraScore:
    """Score one camera offset. Mirrors upstream
    `kLocalize.mb_score_camera`. Counts non-ignored frame pixels that
    don't match the map at offset ``(cx, cy)`` (or its shadow-map
    variant). No early exit — the upstream Nim kernel deliberately
    counts every pixel so the score-better ordering is well-defined
    even for over-budget candidates."""
    map_slice = _map_slice(map_pixels, cx, cy)
    considered = ~ignore_mask
    matches = (frame == map_slice) | (frame == SHADOW_MAP[map_slice & 0x0F])
    errors = int(np.count_nonzero(considered & ~matches))
    compared = int(np.count_nonzero(considered))
    if errors > max_errors:
        score = -errors
    else:
        score = compared - errors * SCREEN_WIDTH
    return CameraScore(score=score, errors=errors, compared=compared)


# --- patch hashing --------------------------------------------------------


def _fnv_hash_64(patches_flat: np.ndarray) -> np.ndarray:
    """FNV-style 64-bit hash. ``patches_flat`` is an ``(N, 64) uint8``
    array of palette pixels (one row per patch). Returns ``(N,) uint64``.

    The hash iteration is sequential (each step depends on the previous),
    but we vectorise *across* patches at each iteration step — 64 numpy
    ops instead of N*64 scalars. Bytewise equivalent to the upstream
    Nim per-pixel loop."""
    h = np.full(patches_flat.shape[0], PATCH_HASH_SEED, dtype=np.uint64)
    one = np.uint64(1)
    for i in range(patches_flat.shape[1]):
        c = (patches_flat[:, i] & 0x0F).astype(np.uint64)
        h = h * PATCH_HASH_BASE + c + one
    return h


def hash_frame_patches(
    frame: np.ndarray, ignore_mask: np.ndarray
) -> tuple[np.ndarray, np.ndarray]:
    """Compute the 16x16 grid of per-patch hashes plus per-patch validity.

    Returns ``(hashes, valid)`` where:
    - ``hashes``: ``(256,) uint64``. FNV-style hash of each 8x8 patch
      (palette indices mod 16), in raster-order patch indexing
      (``py * 16 + px``).
    - ``valid``: ``(256,) bool``. False iff any pixel in the patch is
      ignored.

    Mirrors upstream `kLocalize.mb_hash_frame_patches`."""
    # (128, 128) -> (16, 8, 16, 8) -> transpose to (16, 16, 8, 8) -> (256, 64)
    patches = (
        frame.reshape(PATCH_GRID_H, PATCH_SIZE, PATCH_GRID_W, PATCH_SIZE)
        .transpose(0, 2, 1, 3)
        .reshape(PATCH_TOTAL_COUNT, PATCH_SIZE * PATCH_SIZE)
    )
    ignore_patches = (
        ignore_mask.reshape(PATCH_GRID_H, PATCH_SIZE, PATCH_GRID_W, PATCH_SIZE)
        .transpose(0, 2, 1, 3)
        .reshape(PATCH_TOTAL_COUNT, PATCH_SIZE * PATCH_SIZE)
    )
    hashes = _fnv_hash_64(patches)
    valid = ~ignore_patches.any(axis=1)
    return hashes, valid


# --- patch index ----------------------------------------------------------


@dataclass(frozen=True)
class PatchIndex:
    """Sorted-by-hash global lookup over every valid 8x8 anchor in the
    padded map. ``cam_xs`` / ``cam_ys`` are the anchor's upper-left
    world coordinates (NOT the player-centred camera the localizer
    ultimately reports — the vote step subtracts the frame patch offset
    to recover the camera)."""

    hashes: np.ndarray  # (N,) uint64, sorted ascending
    cam_xs: np.ndarray  # (N,) int32, co-sorted
    cam_ys: np.ndarray  # (N,) int32, co-sorted
    width: int          # anchor-grid width
    height: int


@functools.lru_cache(maxsize=1)
def get_patch_index() -> PatchIndex:
    """Return the cached patch index, building it on first use against
    the baked reference map. One map per process; the cache is
    effectively permanent. Cost: ~0.2-0.5 s of numpy work on first call;
    sub-millisecond thereafter (lru_cache hit)."""
    return _build_patch_index(load_map_pixels())


def _build_patch_index(map_pixels: np.ndarray) -> PatchIndex:
    """Compute patch hashes for every valid camera-anchor offset on the
    padded map. Mirrors upstream `localize.buildPatchIndex` —
    vectorised in numpy where the upstream is scalar Nim."""
    min_x = min_camera_x()
    max_x = max_camera_x() + SCREEN_WIDTH - PATCH_SIZE
    min_y = min_camera_y()
    max_y = max_camera_y() + SCREEN_HEIGHT - PATCH_SIZE
    width = max_x - min_x + 1
    height = max_y - min_y + 1

    h, w = map_pixels.shape
    pad_x_lo = max(0, -min_x)
    pad_x_hi = max(0, max_x + PATCH_SIZE - w)
    pad_y_lo = max(0, -min_y)
    pad_y_hi = max(0, max_y + PATCH_SIZE - h)
    padded = np.full(
        (h + pad_y_lo + pad_y_hi, w + pad_x_lo + pad_x_hi),
        MAP_VOID_COLOR,
        dtype=np.uint8,
    )
    padded[pad_y_lo : pad_y_lo + h, pad_x_lo : pad_x_lo + w] = map_pixels

    # Sliding-window view over the padded map. Each (ay, ax, oy, ox)
    # entry is one map pixel at anchor (ay, ax) and patch offset
    # (oy, ox). Zero-copy.
    from numpy.lib.stride_tricks import sliding_window_view

    windows = sliding_window_view(padded, (PATCH_SIZE, PATCH_SIZE))
    # Anchor (min_x, min_y) sits at padded (min_y + pad_y_lo, min_x +
    # pad_x_lo). By construction, both are 0 — the padding is sized
    # exactly to cover the anchor range.
    anchor_windows = windows[0 : height, 0 : width]  # (height, width, 8, 8)

    # Vectorise the FNV hash across all (height, width) anchors at each
    # of the 64 patch-pixel positions. Same byte sequence as upstream.
    h_arr = np.full((height, width), PATCH_HASH_SEED, dtype=np.uint64)
    one = np.uint64(1)
    for sy in range(PATCH_SIZE):
        for sx in range(PATCH_SIZE):
            c = (anchor_windows[:, :, sy, sx] & 0x0F).astype(np.uint64)
            h_arr = h_arr * PATCH_HASH_BASE + c + one

    count = width * height
    cam_xs = np.broadcast_to(
        np.arange(width, dtype=np.int32) + min_x, (height, width)
    ).reshape(count)
    cam_ys = np.broadcast_to(
        (np.arange(height, dtype=np.int32) + min_y)[:, None], (height, width)
    ).reshape(count)
    hashes_flat = h_arr.reshape(count)

    # Sort by hash ascending; stable sort keeps anchor-grid raster order
    # within equal-hash runs (matches upstream's stable indirect sort).
    order = np.argsort(hashes_flat, kind="stable")
    return PatchIndex(
        hashes=hashes_flat[order],
        cam_xs=np.ascontiguousarray(cam_xs[order]),
        cam_ys=np.ascontiguousarray(cam_ys[order]),
        width=width,
        height=height,
    )


# --- vote_camera_candidates ----------------------------------------------


def vote_camera_candidates(
    frame_hashes: np.ndarray,
    frame_valid: np.ndarray,
    index: PatchIndex,
    *,
    top_k: int = PATCH_TOP_CANDIDATES,
    min_votes: int = PATCH_MIN_VOTES,
    max_matches_per_patch: int = PATCH_MAX_MATCHES,
) -> list[Candidate]:
    """Vote-based camera localization over the precomputed patch index.

    Each valid frame patch casts one vote per matching map anchor
    (camera = anchor - patch_offset_in_frame), clipped to the camera
    range. Patches matching more than ``max_matches_per_patch`` index
    entries are skipped (ambiguous floor tiles). Returns the top-K
    ``(cx, cy, votes)`` candidates in descending vote order, ties
    broken by ascending ``(cy, cx)`` — matches upstream
    `mb_vote_camera_candidates` byte-for-byte."""
    cam_w = camera_width()
    cam_h = camera_height()
    min_cx = min_camera_x()
    max_cx = max_camera_x()
    min_cy = min_camera_y()
    max_cy = max_camera_y()

    # Collect all (camera_y, camera_x) vote indices in a single flat
    # array, then bincount. Faster than np.add.at over a dense
    # accumulator for sparse vote patterns.
    all_flat_idx: list[np.ndarray] = []
    valid_patch_indices = np.where(frame_valid)[0]
    for p in valid_patch_indices.tolist():
        h = frame_hashes[p]
        first = int(np.searchsorted(index.hashes, h, side="left"))
        last = int(np.searchsorted(index.hashes, h, side="right"))
        count = last - first
        if count <= 0 or count > max_matches_per_patch:
            continue
        py = p // PATCH_GRID_W
        px = p % PATCH_GRID_W
        dx = px * PATCH_SIZE
        dy = py * PATCH_SIZE
        match_xs = index.cam_xs[first:last].astype(np.int64) - dx
        match_ys = index.cam_ys[first:last].astype(np.int64) - dy
        in_range = (
            (match_xs >= min_cx)
            & (match_xs <= max_cx)
            & (match_ys >= min_cy)
            & (match_ys <= max_cy)
        )
        if not in_range.any():
            continue
        match_xs = match_xs[in_range]
        match_ys = match_ys[in_range]
        flat = (match_ys - min_cy) * cam_w + (match_xs - min_cx)
        all_flat_idx.append(flat.astype(np.intp))

    if not all_flat_idx:
        return []

    flat_idx = np.concatenate(all_flat_idx)
    votes_flat = np.bincount(flat_idx, minlength=cam_h * cam_w)

    # Top-K by votes, ties broken by ascending (cy, cx).
    candidate_positions = np.where(votes_flat >= min_votes)[0]
    if len(candidate_positions) == 0:
        return []
    cys = (candidate_positions // cam_w).astype(np.int64) + min_cy
    cxs = (candidate_positions % cam_w).astype(np.int64) + min_cx
    cand_votes = votes_flat[candidate_positions]

    # np.lexsort: last key is primary. Want (-votes desc, cy asc, cx asc).
    order = np.lexsort((cxs, cys, -cand_votes.astype(np.int64)))[:top_k]
    return [
        Candidate(cx=int(cxs[i]), cy=int(cys[i]), votes=int(cand_votes[i]))
        for i in order
    ]


# --- acceptance + ordering helpers ---------------------------------------


def _accept_camera_score(score: CameraScore, max_errors: int) -> bool:
    return score.errors <= max_errors and score.compared >= FRAME_FIT_MIN_COMPARED


def _score_better(new_sc: CameraScore, best_sc: CameraScore) -> bool:
    """Nim-side ordering: fewer errors first, then more compared.
    Mirrors upstream `scoreBetter`."""
    if new_sc.errors != best_sc.errors:
        return new_sc.errors < best_sc.errors
    return new_sc.compared > best_sc.compared


def _accept_lock(
    state: LocalizerState,
    cx: int,
    cy: int,
    score: CameraScore,
    lock: CameraLock,
    tick: int,
) -> None:
    """Commit a successful localization into the state in place. Used
    by the three internal tier functions which build a fresh state per
    `update_location` call and pass it through."""
    state.camera_x = cx
    state.camera_y = cy
    state.camera_score = score.score
    state.camera_lock = lock
    state.localized = True
    state.game_started = True
    state.last_localized_tick = tick
    state.self_x = player_world_x(cx)
    state.self_y = player_world_y(cy)
    if not state.home_set:
        state.home_x = state.self_x
        state.home_y = state.self_y
        state.home_set = True


# --- tier 1: local refit -------------------------------------------------


def _locate_near_frame(
    state: LocalizerState,
    frame: np.ndarray,
    map_pixels: np.ndarray,
    ignore_mask: np.ndarray,
    tick: int,
) -> bool:
    """Try the seed first; if it doesn't fit, sweep the 17x17 window
    around it in raster order. Mirrors upstream `locateNearFrame`
    semantics (first-zero-error short-circuit)."""
    seed_x = state.camera_x
    seed_y = state.camera_y
    seed_score = score_camera(
        frame, map_pixels, ignore_mask, seed_x, seed_y, LOCAL_FRAME_FIT_MAX_ERRORS
    )
    if _accept_camera_score(seed_score, LOCAL_FRAME_FIT_MAX_ERRORS):
        _accept_lock(state, seed_x, seed_y, seed_score, CameraLock.LOCAL_FRAME_MAP_LOCK, tick)
        return True

    lo_x = max(min_camera_x(), seed_x - LOCAL_FRAME_SEARCH_RADIUS)
    hi_x = min(max_camera_x(), seed_x + LOCAL_FRAME_SEARCH_RADIUS)
    lo_y = max(min_camera_y(), seed_y - LOCAL_FRAME_SEARCH_RADIUS)
    hi_y = min(max_camera_y(), seed_y + LOCAL_FRAME_SEARCH_RADIUS)

    best = seed_score
    best_x = seed_x
    best_y = seed_y
    for y in range(lo_y, hi_y + 1):
        for x in range(lo_x, hi_x + 1):
            if x == seed_x and y == seed_y:
                continue
            sc = score_camera(
                frame, map_pixels, ignore_mask, x, y, LOCAL_FRAME_FIT_MAX_ERRORS
            )
            if _score_better(sc, best):
                best = sc
                best_x = x
                best_y = y
                if sc.errors == 0 and sc.compared >= FRAME_FIT_MIN_COMPARED:
                    _accept_lock(
                        state, best_x, best_y, best, CameraLock.LOCAL_FRAME_MAP_LOCK, tick
                    )
                    return True

    if not _accept_camera_score(best, LOCAL_FRAME_FIT_MAX_ERRORS):
        return False
    _accept_lock(state, best_x, best_y, best, CameraLock.LOCAL_FRAME_MAP_LOCK, tick)
    return True


# --- tier 2: patch-hash global search -----------------------------------


def _locate_by_patches(
    state: LocalizerState,
    frame: np.ndarray,
    map_pixels: np.ndarray,
    ignore_mask: np.ndarray,
    tick: int,
) -> bool:
    """Patch-hash vote + full-frame rescore of the top candidates."""
    frame_hashes, frame_valid = hash_frame_patches(frame, ignore_mask)
    candidates = vote_camera_candidates(frame_hashes, frame_valid, get_patch_index())
    if not candidates:
        return False

    best = _NO_SCORE
    best_x = state.camera_x
    best_y = state.camera_y
    for cand in candidates:
        if not camera_can_hold_player(cand.cx, cand.cy):
            continue
        sc = score_camera(
            frame, map_pixels, ignore_mask, cand.cx, cand.cy, FULL_FRAME_FIT_MAX_ERRORS
        )
        if _score_better(sc, best):
            best = sc
            best_x = cand.cx
            best_y = cand.cy

    if not _accept_camera_score(best, FULL_FRAME_FIT_MAX_ERRORS):
        return False
    _accept_lock(state, best_x, best_y, best, CameraLock.FRAME_MAP_LOCK, tick)
    return True


# --- tier 3: spiral fallback ---------------------------------------------


def _locate_by_spiral(
    state: LocalizerState,
    frame: np.ndarray,
    map_pixels: np.ndarray,
    ignore_mask: np.ndarray,
    tick: int,
) -> bool:
    """Last-resort spiral scan. Kept sequential (one ``score_camera``
    per probe) to preserve the upstream first-zero-error-wins
    short-circuit ordering. Worst case ~5800 calls at 48 px radius,
    but usually terminates within a few rings."""
    seed_x = state.camera_x if state.game_started else button_camera_x()
    seed_y = state.camera_y if state.game_started else button_camera_y()
    lo_x, hi_x = min_camera_x(), max_camera_x()
    lo_y, hi_y = min_camera_y(), max_camera_y()
    seed_x = max(lo_x, min(hi_x, seed_x))
    seed_y = max(lo_y, min(hi_y, seed_y))
    max_radius = min(
        SPIRAL_MAX_RADIUS,
        max(
            max(abs(seed_x - lo_x), abs(seed_x - hi_x)),
            max(abs(seed_y - lo_y), abs(seed_y - hi_y)),
        ),
    )

    best = _NO_SCORE
    best_x = seed_x
    best_y = seed_y

    def try_camera(x: int, y: int) -> bool:
        nonlocal best, best_x, best_y
        if not (lo_x <= x <= hi_x and lo_y <= y <= hi_y):
            return False
        if not camera_can_hold_player(x, y):
            return False
        sc = score_camera(
            frame, map_pixels, ignore_mask, x, y, FULL_FRAME_FIT_MAX_ERRORS
        )
        if _score_better(sc, best):
            best = sc
            best_x = x
            best_y = y
            if sc.errors == 0 and sc.compared >= FRAME_FIT_MIN_COMPARED:
                return True
        return False

    if not try_camera(seed_x, seed_y):
        done = False
        for radius in range(1, max_radius + 1):
            if done:
                break
            # Top + bottom rows of the ring.
            for dx in range(-radius, radius + 1):
                if try_camera(seed_x + dx, seed_y - radius):
                    done = True
                    break
                if done:
                    break
                if try_camera(seed_x + dx, seed_y + radius):
                    done = True
                    break
            if done:
                break
            # Left + right columns (excluding corners).
            for dy in range(-radius + 1, radius):
                if try_camera(seed_x - radius, seed_y + dy):
                    done = True
                    break
                if done:
                    break
                if try_camera(seed_x + radius, seed_y + dy):
                    done = True
                    break

    if not _accept_camera_score(best, FULL_FRAME_FIT_MAX_ERRORS):
        state.camera_lock = CameraLock.NO_LOCK
        state.camera_score = best.score
        state.localized = False
        return False
    _accept_lock(state, best_x, best_y, best, CameraLock.FRAME_MAP_LOCK, tick)
    return True


# --- public entry points -------------------------------------------------


def update_location(
    prev_state: LocalizerState | None,
    frame: np.ndarray,
    ignore_mask: np.ndarray,
    *,
    tick: int = 0,
    map_pixels: np.ndarray | None = None,
) -> LocalizerState:
    """Localize the camera against ``frame`` and return a fresh state.

    Callers are responsible for having gated out interstitial frames
    before calling — running a localize pass on a black voting screen
    wastes time and produces garbage. The S5+ perception orchestrator
    will enforce this via :func:`interstitial.detect_interstitial`.

    Callers are also responsible for populating ``ignore_mask`` — use
    :func:`ignore.build_phase_1_0_ignore_mask` for the phase-1.0 mask;
    extended actor-aware masks are composed at the callsite.

    ``prev_state=None`` is treated as a fresh first frame. The returned
    state is a new dataclass — the caller's ``prev_state`` is not
    mutated.
    """
    if map_pixels is None:
        map_pixels = load_map_pixels()

    state = LocalizerState() if prev_state is None else replace(prev_state)
    state.last_camera_x = state.camera_x
    state.last_camera_y = state.camera_y

    if state.localized:
        if _locate_near_frame(state, frame, map_pixels, ignore_mask, tick):
            return state

    if _locate_by_patches(state, frame, map_pixels, ignore_mask, tick):
        return state

    if _locate_by_spiral(state, frame, map_pixels, ignore_mask, tick):
        return state

    # All tiers failed; leave the camera fields at their previous values
    # (already copied by `replace`), mark unlocalized.
    state.localized = False
    return state


def reseed_camera_at_home(prev_state: LocalizerState) -> LocalizerState:
    """Reset the camera to home (or the button) with no active lock.
    Called after interstitials when the belief layer wants the next
    localization pass to start from a known-good seed. Returns a fresh
    state."""
    state = replace(prev_state)
    if state.home_set:
        state.camera_x = camera_x_for_world(state.home_x)
        state.camera_y = camera_y_for_world(state.home_y)
    else:
        state.camera_x = button_camera_x()
        state.camera_y = button_camera_y()
    state.last_camera_x = state.camera_x
    state.last_camera_y = state.camera_y
    state.camera_lock = CameraLock.NO_LOCK
    state.camera_score = 0
    state.localized = False
    return state
