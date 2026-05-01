"""Camera localization: patch-hash global search + local refit + spiral fallback.

Port of ``localize.nim``. Once a frame has been deemed non-interstitial
by :func:`~modulabot.frame.looks_like_interstitial`, the localizer's
job is to find the map offset ``(camera_x, camera_y)`` such that the
frame's pixels best match a 128×128 window of the static map raster
(ignoring dynamic pixels like the player, other crewmates, bodies,
ghosts, task icons, and the radar dot ring).

Once localized, :mod:`~modulabot.geometry` converts the camera offset
into a world position for task targeting and A-star navigation, and
:func:`~modulabot.actors.scan_task_icons` becomes non-trivial.

Strategy (matches the Nim entry point ``updateLocation``):

1. **Local refit** — `scoreCamera` over a small window around the
   previous camera. Cheap, usually finds a zero-error fit in 1 step
   on a stationary bot.
2. **Patch-hash global search** — hash 8×8 frame patches, look each
   up in a pre-built map-patch index, vote for camera offsets, score
   the top candidates with the full 128×128 fit. Invoked only when
   the local refit fails.
3. **Spiral fallback** — last resort when the patch table returns no
   plausible candidate. Spirals outward from the best seed camera
   (previous lock, or the button if we've never locked).

The expensive per-pixel map-fit scoring is vectorised — we compute
the whole (128, 128) match mask in one numpy pass and count errors /
compared in one more. Patch-hash build + lookup use numpy uint64
arithmetic so the hash overflow semantics match the Nim version.

State model (see :class:`~modulabot.state.Perception`):

- ``camera_x`` / ``camera_y`` / ``camera_score`` / ``camera_lock``
  /``localized`` — the current lock.
- ``last_camera_x`` / ``last_camera_y`` — previous frame's camera, so
  the local refit starts from the right seed.
- ``home_x`` / ``home_y`` / ``home_set`` — remembered button-area
  camera for post-interstitial reseeds.
- ``game_started`` — false during the very first frames of a round;
  forces the global search to start from the button rather than
  trusting stale state.

Design notes that differ from Nim:

- The patch index is built lazily and cached at module level, keyed
  on ``id(game_map)``. One map per process, so this is effectively
  permanent.
- We do not emit perf micros (:attr:`bot.perf`); the Python port
  doesn't carry a ``PerfCounters`` sub-record yet. Add one on
  ``Bot.diag`` if telemetry becomes a priority.
- The ``mapTiles`` (remembered-visible-map) memoization in the Nim
  debug viewer is not ported — our visual debug path in
  :mod:`scripts.debug_overlay` doesn't need it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import numpy as np

from . import nim_perception as _nim_perception
from .data import (
    MAP_HEIGHT,
    MAP_VOID_COLOR,
    MAP_WIDTH,
    SCREEN_HEIGHT,
    SCREEN_WIDTH,
    SHADOW_MAP,
    GameMap,
    Sprites,
)
from .frame import compute_ignore_mask
from .geometry import (
    button_camera_x,
    button_camera_y,
    camera_can_hold_player,
    camera_x_for_world,
    camera_y_for_world,
    max_camera_x,
    max_camera_y,
    min_camera_x,
    min_camera_y,
)
from .state import Bot, CameraLock

# ---------------------------------------------------------------------------
# Constants (verbatim from localize.nim)
# ---------------------------------------------------------------------------

#: Max per-frame mismatches the global search will accept on a lock.
FULL_FRAME_FIT_MAX_ERRORS = 420
#: Max per-frame mismatches the cheap local refit will accept.
LOCAL_FRAME_FIT_MAX_ERRORS = 320
#: Minimum pixels compared (i.e. opaque, non-ignored) for a score to
#: be trusted — guards against "all 16k pixels were ignored" degenerate
#: cases.
FRAME_FIT_MIN_COMPARED = 12000
#: Local refit search half-extent in pixels (square window of 17×17).
LOCAL_FRAME_SEARCH_RADIUS = 8
#: Size of one patch, in pixels. 8 means a 16×16 grid of patches per
#: 128×128 frame. Do not change — the hash table entry layout is
#: tied to this.
PATCH_SIZE = 8
PATCH_GRID_W = SCREEN_WIDTH // PATCH_SIZE
PATCH_GRID_H = SCREEN_HEIGHT // PATCH_SIZE

PATCH_HASH_BASE = np.uint64(16777619)
PATCH_HASH_SEED = np.uint64(14695981039346656037)

#: Skip frame patches whose hash matches more than this many map
#: entries — those patches are too ambiguous to contribute useful
#: votes. Corresponds to large featureless regions like floors.
PATCH_MAX_MATCHES = 4096
#: Keep this many top-voted camera candidates for full-frame scoring.
PATCH_TOP_CANDIDATES = 16
#: Minimum patch votes for a camera offset to be considered a
#: candidate.
PATCH_MIN_VOTES = 3


# ---------------------------------------------------------------------------
# Camera scoring (full 128×128 map fit, vectorised)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CameraScore:
    """Result of scoring one camera offset against the current frame.

    ``score`` is Nim's ``compared - errors * ScreenWidth`` — a single
    scalar used to order candidates. ``errors`` and ``compared`` are
    the underlying counts. Higher ``score`` is better; lower
    ``errors`` is better for acceptance.
    """

    score: int
    errors: int
    compared: int


_NO_SCORE = CameraScore(score=-(1 << 30), errors=(1 << 30), compared=0)


def _map_slice_for_camera(
    map_pixels: np.ndarray, cx: int, cy: int
) -> np.ndarray:
    """Return a ``(SCREEN_HEIGHT, SCREEN_WIDTH)`` uint8 view of the map
    under camera ``(cx, cy)``, filling off-map pixels with
    :data:`~modulabot.data.MAP_VOID_COLOR`.

    The frame's ``(sx, sy)`` is aligned with map ``(cx + sx, cy + sy)``.
    """
    out = np.full((SCREEN_HEIGHT, SCREEN_WIDTH), MAP_VOID_COLOR, dtype=np.uint8)
    mx0, my0 = cx, cy
    mx1, my1 = cx + SCREEN_WIDTH, cy + SCREEN_HEIGHT

    # Visible intersection with the map rectangle.
    src_x0 = max(mx0, 0)
    src_y0 = max(my0, 0)
    src_x1 = min(mx1, MAP_WIDTH)
    src_y1 = min(my1, MAP_HEIGHT)
    if src_x1 <= src_x0 or src_y1 <= src_y0:
        return out

    dst_x0 = src_x0 - mx0
    dst_y0 = src_y0 - my0
    dst_x1 = dst_x0 + (src_x1 - src_x0)
    dst_y1 = dst_y0 + (src_y1 - src_y0)
    out[dst_y0:dst_y1, dst_x0:dst_x1] = map_pixels[src_y0:src_y1, src_x0:src_x1]
    return out


def score_camera(
    frame: np.ndarray,
    map_pixels: np.ndarray,
    ignore_mask: np.ndarray,
    cx: int,
    cy: int,
    max_errors: int = FULL_FRAME_FIT_MAX_ERRORS,
) -> CameraScore:
    """Score one camera offset. Dispatch: Nim FFI or numpy fallback.

    Both paths produce byte-identical :class:`CameraScore` results;
    pinned by ``tests/test_nim_perception.py``. Callers should use
    this dispatcher, not the underscored ``_score_camera_numpy``,
    unless they explicitly want to force the fallback for testing.
    """
    if _nim_perception.HAVE_NATIVE:
        score, errors, compared = _nim_perception.score_camera(
            frame, map_pixels, ignore_mask, cx, cy, max_errors,
        )
        return CameraScore(score=score, errors=errors, compared=compared)
    return _score_camera_numpy(
        frame, map_pixels, ignore_mask, cx, cy, max_errors,
    )


def _score_camera_numpy(
    frame: np.ndarray,
    map_pixels: np.ndarray,
    ignore_mask: np.ndarray,
    cx: int,
    cy: int,
    max_errors: int = FULL_FRAME_FIT_MAX_ERRORS,
) -> CameraScore:
    """Pure-Python numpy fallback for :func:`score_camera`.

    Kept so ``MODULABOT_DISABLE_NATIVE=1`` still produces correct (if
    slower) results. Also serves as the parity oracle in
    ``tests/test_nim_perception.py``.

    For every non-ignored frame pixel, compare against the
    corresponding map pixel — a match *either* against the exact
    colour or against the shadow-map variant counts toward
    ``compared``; a non-match increments ``errors``. Final score is
    ``compared - errors * ScreenWidth`` (same formula the Nim uses so
    candidate ordering is identical).

    The ``max_errors`` budget is only consulted at the end; unlike the
    scalar Nim implementation we don't early-exit per pixel, because a
    single numpy compare over (128, 128) is cheaper than the
    per-iteration branch overhead a half-completed Python loop would
    pay.
    """
    map_slice = _map_slice_for_camera(map_pixels, cx, cy)

    # Exact-match or shadowed-match — either one counts as "compared".
    direct = frame == map_slice
    # Nim checks `ShadowMap[mapColor and 0x0f] == frameColor`.
    shadow_lut = SHADOW_MAP[map_slice & 0x0F]
    shadowed = frame == shadow_lut

    not_ignored = ~ignore_mask
    compared_mask = not_ignored  # every non-ignored pixel contributes
    error_mask = not_ignored & ~direct & ~shadowed

    compared = int(np.count_nonzero(compared_mask))
    errors = int(np.count_nonzero(error_mask))

    if errors > max_errors:
        return CameraScore(score=-errors, errors=errors, compared=compared)
    return CameraScore(
        score=compared - errors * SCREEN_WIDTH,
        errors=errors,
        compared=compared,
    )


def _accept_camera_score(score: CameraScore, max_errors: int) -> bool:
    return score.errors <= max_errors and score.compared >= FRAME_FIT_MIN_COMPARED


# ---------------------------------------------------------------------------
# Patch-hash index (built once per map)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PatchIndex:
    """Global 8×8 patch-hash index over the static map raster.

    ``hashes`` is sorted ascending so we can binary-search for matches;
    ``cam_xs`` / ``cam_ys`` are the co-sorted camera offsets (upper-left
    of the 8×8 patch, not the player-centred camera). Lookup is a
    ``searchsorted`` pair for a given query hash.

    Built once per :class:`~modulabot.data.GameMap` and cached at
    module level — constructing it costs ~0.5 s and allocates ~12 MB.
    """

    hashes: np.ndarray  # (N,) uint64, sorted
    cam_xs: np.ndarray  # (N,) int32
    cam_ys: np.ndarray  # (N,) int32
    width: int  # derived from camera range
    height: int


_PATCH_INDEX_CACHE: dict[int, PatchIndex] = {}


def _map_pixel_safe(map_pixels: np.ndarray, x: int, y: int) -> int:
    """Off-map read returns :data:`MAP_VOID_COLOR` to match Nim
    ``patchMapColor``."""
    if 0 <= x < MAP_WIDTH and 0 <= y < MAP_HEIGHT:
        return int(map_pixels[y, x])
    return MAP_VOID_COLOR


def _build_patch_index(game_map: GameMap) -> PatchIndex:
    """Compute patch hashes for every valid camera anchor in the map.

    Vectorised: we iterate the 64 pixels of the 8×8 patch window and,
    at each pixel offset, fold every map location into the hash
    accumulator in a single numpy op. Cost is 64 multiply-adds over a
    ~600×1100 array — a few hundred milliseconds at worst.

    The anchor range covers ``[minCameraX, maxCameraX + ScreenWidth - PatchSize]``
    in X (same Y), matching ``buildPatchEntries`` in ``localize.nim``.
    Anchors outside the map rectangle are still indexed; their hashes
    fold in :data:`MAP_VOID_COLOR` for the off-map pixels, so
    frame-patches near the screen edge can still match during global
    search.
    """
    min_x = min_camera_x()
    max_x = max_camera_x() + SCREEN_WIDTH - PATCH_SIZE
    min_y = min_camera_y()
    max_y = max_camera_y() + SCREEN_HEIGHT - PATCH_SIZE

    width = max_x - min_x + 1
    height = max_y - min_y + 1

    # Pad the map so we can index the full patch window at any anchor
    # without bounds checks. Pad amount is max(-min_x, 0) on the left,
    # max(max_x + PATCH_SIZE - MAP_WIDTH, 0) on the right, similarly Y.
    pad_left = max(-min_x, 0)
    pad_top = max(-min_y, 0)
    pad_right = max(max_x + PATCH_SIZE - MAP_WIDTH, 0)
    pad_bottom = max(max_y + PATCH_SIZE - MAP_HEIGHT, 0)

    padded = np.full(
        (
            game_map.map_pixels.shape[0] + pad_top + pad_bottom,
            game_map.map_pixels.shape[1] + pad_left + pad_right,
        ),
        MAP_VOID_COLOR,
        dtype=np.uint8,
    )
    padded[
        pad_top : pad_top + game_map.map_pixels.shape[0],
        pad_left : pad_left + game_map.map_pixels.shape[1],
    ] = game_map.map_pixels

    # Anchor (min_y, min_x) lives at padded (min_y + pad_top, min_x + pad_left).
    anchor_y0 = min_y + pad_top
    anchor_x0 = min_x + pad_left

    hashes = np.full((height, width), PATCH_HASH_SEED, dtype=np.uint64)
    for py in range(PATCH_SIZE):
        for px in range(PATCH_SIZE):
            block = padded[
                anchor_y0 + py : anchor_y0 + py + height,
                anchor_x0 + px : anchor_x0 + px + width,
            ].astype(np.uint64) & np.uint64(0x0F)
            # hash = hash * PATCH_HASH_BASE + color + 1  (Nim patchHashAdd)
            hashes = hashes * PATCH_HASH_BASE + block + np.uint64(1)

    # Camera offsets for each anchor (flat index → (cx, cy)).
    ys = np.arange(min_y, max_y + 1, dtype=np.int32)
    xs = np.arange(min_x, max_x + 1, dtype=np.int32)
    cam_xs_grid, cam_ys_grid = np.meshgrid(xs, ys)

    flat_hashes = hashes.reshape(-1)
    flat_xs = cam_xs_grid.reshape(-1)
    flat_ys = cam_ys_grid.reshape(-1)

    order = np.argsort(flat_hashes, kind="stable")
    return PatchIndex(
        hashes=flat_hashes[order],
        cam_xs=flat_xs[order],
        cam_ys=flat_ys[order],
        width=width,
        height=height,
    )


def get_patch_index(game_map: GameMap) -> PatchIndex:
    """Return the (possibly cached) patch index for ``game_map``.

    First call per :class:`~modulabot.data.GameMap` builds the index;
    later calls return the cached instance. Keyed on ``id(game_map)``
    because :class:`GameMap` contains numpy arrays and isn't hashable.
    """
    key = id(game_map)
    idx = _PATCH_INDEX_CACHE.get(key)
    if idx is None:
        idx = _build_patch_index(game_map)
        _PATCH_INDEX_CACHE[key] = idx
    return idx


# ---------------------------------------------------------------------------
# Frame-patch hashing
# ---------------------------------------------------------------------------


def _hash_frame_patches(
    frame: np.ndarray, ignore_mask: np.ndarray
) -> tuple[np.ndarray, np.ndarray]:
    """Compute hashes for the 16×16 grid of frame 8×8 patches.

    Dispatch: Nim FFI or numpy fallback. Both paths return
    byte-identical ``(hashes, valid)`` tuples; pinned by
    ``tests/test_nim_perception.py``.

    Returns ``(hashes, valid)``:

    - ``hashes`` — ``(PATCH_GRID_H, PATCH_GRID_W) uint64``.
    - ``valid`` — ``(PATCH_GRID_H, PATCH_GRID_W) bool``. ``True`` iff
      the patch has no dynamic-pixel inside it (matches
      ``framePatchHash`` returning false on ignore hits).

    A patch containing even one ignored pixel is invalid — its hash
    would depend on transient content we can't trust.
    """
    if _nim_perception.HAVE_NATIVE:
        return _nim_perception.hash_frame_patches(frame, ignore_mask)
    return _hash_frame_patches_numpy(frame, ignore_mask)


def _hash_frame_patches_numpy(
    frame: np.ndarray, ignore_mask: np.ndarray
) -> tuple[np.ndarray, np.ndarray]:
    """Pure-Python numpy fallback for :func:`_hash_frame_patches`.

    Kept so ``MODULABOT_DISABLE_NATIVE=1`` still produces correct (if
    slower) results. Also serves as the parity oracle in
    ``tests/test_nim_perception.py``.
    """
    # Build per-patch hashes by iterating 8×8 within patch (not by anchor).
    hashes = np.full((PATCH_GRID_H, PATCH_GRID_W), PATCH_HASH_SEED, dtype=np.uint64)
    # "any-ignored" accumulator: True if any pixel in this patch is ignored.
    any_ignored = np.zeros((PATCH_GRID_H, PATCH_GRID_W), dtype=bool)

    for py in range(PATCH_SIZE):
        for px in range(PATCH_SIZE):
            pixels = frame[py::PATCH_SIZE, px::PATCH_SIZE][:PATCH_GRID_H, :PATCH_GRID_W]
            ignore_here = ignore_mask[py::PATCH_SIZE, px::PATCH_SIZE][
                :PATCH_GRID_H, :PATCH_GRID_W
            ]
            any_ignored |= ignore_here
            block = pixels.astype(np.uint64) & np.uint64(0x0F)
            hashes = hashes * PATCH_HASH_BASE + block + np.uint64(1)
    return hashes, ~any_ignored


# ---------------------------------------------------------------------------
# Localizer
# ---------------------------------------------------------------------------


class Localizer:
    """Stateful front-end to the localization primitives above.

    One localizer per :class:`~modulabot.state.Bot`. Keeps a reference
    to the map patch index (shared across all agents) and exposes
    :meth:`update_location` as the per-frame entry point.

    Internal scratch arrays (patch-vote accumulator, touched list) are
    allocated lazily on first use so an always-state-obs agent pays no
    memory cost for the pixel path.
    """

    def __init__(self, game_map: GameMap) -> None:
        self._game_map = game_map
        self._patch_index = get_patch_index(game_map)
        # Camera-index → vote count. Size = (maxCameraY - minCameraY + 1) *
        # (maxCameraX - minCameraX + 1). Allocated on first patch search.
        self._votes: Optional[np.ndarray] = None
        self._touched: list[int] = []
        self._camera_width: int = max_camera_x() - min_camera_x() + 1

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def update_location(
        self,
        bot: Bot,
        sprites: Sprites,
        frame: np.ndarray,
    ) -> None:
        """Localize the camera against ``frame``; update ``bot.percep``.

        Caller is responsible for having gated out interstitials via
        :func:`~modulabot.frame.looks_like_interstitial` — we don't
        re-check here. Caller is also responsible for having run the
        actor scanners ahead of us so the ignore mask knows about
        dynamic pixels (crewmates, bodies, ghosts, task icons).

        Strategy mirrors the Nim ``updateLocation``:

        1. Stash the previous camera in ``last_camera_*``.
        2. Try the cheap local refit.
        3. Fall back to the full patch + spiral global search if the
           refit doesn't clear its miss budget.

        On success, sets ``bot.percep.localized = True`` and populates
        ``camera_x`` / ``camera_y`` / ``camera_score`` / ``camera_lock``.
        On failure, leaves ``localized = False`` and the camera fields
        at their previous values — callers should treat them as stale.
        """
        percep = bot.percep
        percep.last_camera_x = percep.camera_x
        percep.last_camera_y = percep.camera_y

        ignore_mask = compute_ignore_mask(bot, sprites, frame)
        map_pixels = self._game_map.map_pixels

        if percep.localized and self._locate_near_frame(
            bot, frame, map_pixels, ignore_mask
        ):
            return
        self._locate_by_frame(bot, frame, map_pixels, ignore_mask)

    def reseed_camera_at_home(self, bot: Bot) -> None:
        """Reset the camera to home (or the button) with no active lock.

        Called after interstitials when we want the next localisation
        pass to start from a known-good seed instead of stale state.
        Mirrors ``reseedCameraAtHome`` in ``localize.nim``.
        """
        percep = bot.percep
        if percep.home_set:
            percep.camera_x = camera_x_for_world(percep.home_x)
            percep.camera_y = camera_y_for_world(percep.home_y)
        else:
            percep.camera_x = button_camera_x(self._game_map)
            percep.camera_y = button_camera_y(self._game_map)
        percep.last_camera_x = percep.camera_x
        percep.last_camera_y = percep.camera_y
        percep.camera_lock = CameraLock.NO_LOCK
        percep.camera_score = 0
        percep.localized = False

    # ------------------------------------------------------------------
    # Locator strategies
    # ------------------------------------------------------------------

    def _locate_near_frame(
        self,
        bot: Bot,
        frame: np.ndarray,
        map_pixels: np.ndarray,
        ignore_mask: np.ndarray,
    ) -> bool:
        """Cheap local refit within ``LOCAL_FRAME_SEARCH_RADIUS`` of the
        previous lock. Returns True on success (lock updated).

        Python-specific tiered approach:

        1. Score the previous-camera position. If it clears the miss
           budget (``LOCAL_FRAME_FIT_MAX_ERRORS`` / ``FRAME_FIT_MIN_COMPARED``),
           commit immediately.
        2. Otherwise scan the full 17×17 neighbourhood and pick the
           best.

        Nim's scalar ``scoreCamera`` early-exits internally when miss
        count exceeds the budget, so its full-window sweep is cheap —
        bad cameras reject after a few pixels. Our vectorised Python
        score has no cheap early-exit, so the full-window sweep always
        pays the full cost per candidate. Accepting the seed when it's
        already good enough is a safe equivalent: a stationary bot's
        seed *is* the argmin; a moving bot's seed is still within
        ``LOCAL_FRAME_SEARCH_RADIUS`` of the truth, and next frame's
        seed (derived from this acceptance) will again be within
        the window. Drift is bounded by the per-frame refit miss
        budget.
        """
        percep = bot.percep
        seed_x, seed_y = percep.camera_x, percep.camera_y
        seed_score = score_camera(
            frame, map_pixels, ignore_mask, seed_x, seed_y,
            max_errors=LOCAL_FRAME_FIT_MAX_ERRORS,
        )
        if _accept_camera_score(seed_score, LOCAL_FRAME_FIT_MAX_ERRORS):
            self._accept_lock(
                bot, seed_x, seed_y, seed_score,
                CameraLock.LOCAL_FRAME_MAP_LOCK,
            )
            return True

        # Seed didn't clear the budget — run the full neighbourhood sweep.
        best = seed_score
        best_x, best_y = seed_x, seed_y
        lo_x = max(min_camera_x(), seed_x - LOCAL_FRAME_SEARCH_RADIUS)
        hi_x = min(max_camera_x(), seed_x + LOCAL_FRAME_SEARCH_RADIUS)
        lo_y = max(min_camera_y(), seed_y - LOCAL_FRAME_SEARCH_RADIUS)
        hi_y = min(max_camera_y(), seed_y + LOCAL_FRAME_SEARCH_RADIUS)

        for y in range(lo_y, hi_y + 1):
            for x in range(lo_x, hi_x + 1):
                if x == seed_x and y == seed_y:
                    continue
                score = score_camera(
                    frame, map_pixels, ignore_mask, x, y,
                    max_errors=LOCAL_FRAME_FIT_MAX_ERRORS,
                )
                if _score_better(score, best):
                    best = score
                    best_x, best_y = x, y
                    if score.errors == 0 and score.compared >= FRAME_FIT_MIN_COMPARED:
                        self._accept_lock(
                            bot, best_x, best_y, best,
                            CameraLock.LOCAL_FRAME_MAP_LOCK,
                        )
                        return True

        if not _accept_camera_score(best, LOCAL_FRAME_FIT_MAX_ERRORS):
            return False
        self._accept_lock(
            bot, best_x, best_y, best, CameraLock.LOCAL_FRAME_MAP_LOCK
        )
        return True

    def _locate_by_frame(
        self,
        bot: Bot,
        frame: np.ndarray,
        map_pixels: np.ndarray,
        ignore_mask: np.ndarray,
    ) -> bool:
        """Global search: patches first, spiral fallback."""
        if self._locate_by_patches(bot, frame, map_pixels, ignore_mask):
            return True
        return self._locate_by_spiral(bot, frame, map_pixels, ignore_mask)

    def _locate_by_patches(
        self,
        bot: Bot,
        frame: np.ndarray,
        map_pixels: np.ndarray,
        ignore_mask: np.ndarray,
    ) -> bool:
        """Patch-hash vote + full-frame rescore of the top candidates.

        Steps:

        1. Hash each of the 256 frame patches (skipping ones that
           contain ignored pixels).
        2. Vote for camera offsets that match each patch's hash in
           the map-patch index — Nim bulk kernel
           ``mb_vote_camera_candidates`` when ``HAVE_NATIVE``, Python
           fallback otherwise.
        3. Score each of the ``PATCH_TOP_CANDIDATES`` vote-getters
           with :func:`score_camera`, accept the best if it clears
           ``FULL_FRAME_FIT_MAX_ERRORS``.

        The Nim path replaces the 256-patch Python loop (~2 ms of
        interpreter overhead on a typical cold frame) with one FFI
        call that folds searchsorted + vote-accumulate + top-K
        collection into native code.
        """
        frame_hashes, valid = _hash_frame_patches(frame, ignore_mask)

        candidates: list[tuple[int, int, int]]
        if _nim_perception.HAVE_NATIVE:
            candidates = self._collect_candidates_native(frame_hashes, valid)
        else:
            candidates = self._collect_candidates_numpy(frame_hashes, valid)
        if not candidates:
            return False

        best_score = _NO_SCORE
        best_x, best_y = bot.percep.camera_x, bot.percep.camera_y
        for cx, cy, _votes in candidates:
            if not camera_can_hold_player(cx, cy):
                continue
            score = score_camera(
                frame, map_pixels, ignore_mask, cx, cy,
                max_errors=FULL_FRAME_FIT_MAX_ERRORS,
            )
            if _score_better(score, best_score):
                best_score = score
                best_x, best_y = cx, cy

        if not _accept_camera_score(best_score, FULL_FRAME_FIT_MAX_ERRORS):
            return False
        self._accept_lock(bot, best_x, best_y, best_score, CameraLock.FRAME_MAP_LOCK)
        return True

    def _collect_candidates_native(
        self,
        frame_hashes: np.ndarray,
        valid: np.ndarray,
    ) -> list[tuple[int, int, int]]:
        """Nim path: one FFI call covers the whole vote loop.

        Shares the persistent ``_votes`` scratch buffer with the
        numpy path — Nim zeroes only the slots it touches on exit so
        reusing the buffer is safe.
        """
        self._ensure_votes()
        assert self._votes is not None
        return _nim_perception.vote_camera_candidates(
            frame_hashes,
            valid,
            self._patch_index.hashes,
            self._patch_index.cam_xs,
            self._patch_index.cam_ys,
            min_cx=min_camera_x(),
            max_cx=max_camera_x(),
            min_cy=min_camera_y(),
            max_cy=max_camera_y(),
            vote_buf=self._votes,
            top_k=PATCH_TOP_CANDIDATES,
            min_votes=PATCH_MIN_VOTES,
            max_matches_per_patch=PATCH_MAX_MATCHES,
        )

    def _collect_candidates_numpy(
        self,
        frame_hashes: np.ndarray,
        valid: np.ndarray,
    ) -> list[tuple[int, int, int]]:
        """Pure-Python fallback: the original per-patch loop.

        Kept identical to the pre-Nim implementation so
        ``MODULABOT_DISABLE_NATIVE=1`` still produces the same camera
        locks (just ~2 ms slower on cold frames).
        """
        self._clear_votes()
        pidx = self._patch_index
        min_x, max_x = min_camera_x(), max_camera_x()
        min_y, max_y = min_camera_y(), max_camera_y()

        for py in range(PATCH_GRID_H):
            for px in range(PATCH_GRID_W):
                if not valid[py, px]:
                    continue
                h = frame_hashes[py, px]
                first = int(np.searchsorted(pidx.hashes, h, side="left"))
                last = int(np.searchsorted(pidx.hashes, h, side="right"))
                if last - first > PATCH_MAX_MATCHES:
                    continue
                if last == first:
                    continue
                dx = px * PATCH_SIZE
                dy = py * PATCH_SIZE
                cam_xs = pidx.cam_xs[first:last] - dx
                cam_ys = pidx.cam_ys[first:last] - dy
                mask = (
                    (cam_xs >= min_x)
                    & (cam_xs <= max_x)
                    & (cam_ys >= min_y)
                    & (cam_ys <= max_y)
                )
                if not mask.any():
                    continue
                cam_xs = cam_xs[mask]
                cam_ys = cam_ys[mask]
                indices = (cam_ys - min_y) * self._camera_width + (cam_xs - min_x)
                self._add_votes(indices)

        candidates = self._collect_candidates()
        self._clear_votes()
        return candidates

    def _locate_by_spiral(
        self,
        bot: Bot,
        frame: np.ndarray,
        map_pixels: np.ndarray,
        ignore_mask: np.ndarray,
    ) -> bool:
        """Last-resort spiral scan around the best available seed.

        Seeded at the previous camera if we've localized this round,
        otherwise at the button. Small spiral radius grows outward
        until we hit a perfect fit or exhaust the map. Only invoked
        when both local refit and patch-hash search fail — in
        practice rare, but saves us from total loss during heavy
        dynamic-pixel occlusion.
        """
        percep = bot.percep
        seed_x = percep.camera_x if percep.game_started else button_camera_x(self._game_map)
        seed_y = percep.camera_y if percep.game_started else button_camera_y(self._game_map)
        lo_x, hi_x = min_camera_x(), max_camera_x()
        lo_y, hi_y = min_camera_y(), max_camera_y()
        seed_x = max(lo_x, min(hi_x, seed_x))
        seed_y = max(lo_y, min(hi_y, seed_y))
        max_radius = max(
            max(abs(seed_x - lo_x), abs(seed_x - hi_x)),
            max(abs(seed_y - lo_y), abs(seed_y - hi_y)),
        )

        best_score = _NO_SCORE
        best_x, best_y = seed_x, seed_y

        def try_camera(x: int, y: int) -> bool:
            nonlocal best_score, best_x, best_y
            if x < lo_x or x > hi_x or y < lo_y or y > hi_y:
                return False
            if not camera_can_hold_player(x, y):
                return False
            score = score_camera(
                frame, map_pixels, ignore_mask, x, y,
                max_errors=FULL_FRAME_FIT_MAX_ERRORS,
            )
            if _score_better(score, best_score):
                best_score = score
                best_x, best_y = x, y
                return score.errors == 0 and score.compared >= FRAME_FIT_MIN_COMPARED
            return False

        if try_camera(seed_x, seed_y):
            pass  # will still accept below
        else:
            done = False
            for radius in range(1, max_radius + 1):
                if done:
                    break
                # Top + bottom rows of the ring.
                for dx in range(-radius, radius + 1):
                    if try_camera(seed_x + dx, seed_y - radius):
                        done = True
                        break
                    if try_camera(seed_x + dx, seed_y + radius):
                        done = True
                        break
                if done:
                    break
                # Left + right columns (excluding corners already visited).
                for dy in range(-radius + 1, radius):
                    if try_camera(seed_x - radius, seed_y + dy):
                        done = True
                        break
                    if try_camera(seed_x + radius, seed_y + dy):
                        done = True
                        break

        if not _accept_camera_score(best_score, FULL_FRAME_FIT_MAX_ERRORS):
            percep.camera_lock = CameraLock.NO_LOCK
            percep.camera_score = best_score.score
            percep.localized = False
            return False
        self._accept_lock(bot, best_x, best_y, best_score, CameraLock.FRAME_MAP_LOCK)
        return True

    # ------------------------------------------------------------------
    # Vote accumulator helpers
    # ------------------------------------------------------------------

    def _ensure_votes(self) -> None:
        if self._votes is None:
            size = (max_camera_y() - min_camera_y() + 1) * self._camera_width
            self._votes = np.zeros(size, dtype=np.uint16)

    def _add_votes(self, indices: np.ndarray) -> None:
        """Increment the per-camera vote counter at the given flat indices.

        Tracks which indices were touched so :meth:`_clear_votes` can
        zero them out again without sweeping the whole array.
        """
        self._ensure_votes()
        assert self._votes is not None  # for type-checker
        was_zero = self._votes[indices] == 0
        newly_touched = indices[was_zero]
        if newly_touched.size:
            self._touched.extend(int(i) for i in newly_touched.tolist())
        self._votes[indices] += 1

    def _clear_votes(self) -> None:
        if self._votes is None or not self._touched:
            self._touched = []
            return
        self._votes[self._touched] = 0
        self._touched = []

    def _collect_candidates(self) -> list[tuple[int, int, int]]:
        """Return the top ``PATCH_TOP_CANDIDATES`` ``(cx, cy, votes)``."""
        if self._votes is None or not self._touched:
            return []
        # Only the touched indices can have nonzero votes.
        indices = np.array(self._touched, dtype=np.int64)
        assert self._votes is not None  # for type-checker
        votes = self._votes[indices]
        keep = votes >= PATCH_MIN_VOTES
        if not keep.any():
            return []
        indices = indices[keep]
        votes = votes[keep]
        # Sort by descending votes, ties broken by ascending (cy, cx) so
        # the top-N is deterministic (matches the Nim comparator).
        cam_width = self._camera_width
        cxs = indices % cam_width + min_camera_x()
        cys = indices // cam_width + min_camera_y()
        # Compose a single sort key.
        order = np.lexsort((cxs, cys, -votes.astype(np.int32)))
        order = order[:PATCH_TOP_CANDIDATES]
        return [
            (int(cxs[i]), int(cys[i]), int(votes[i])) for i in order.tolist()
        ]

    # ------------------------------------------------------------------
    # Lock book-keeping
    # ------------------------------------------------------------------

    def _accept_lock(
        self,
        bot: Bot,
        cx: int,
        cy: int,
        score: CameraScore,
        lock: CameraLock,
    ) -> None:
        percep = bot.percep
        percep.camera_x = cx
        percep.camera_y = cy
        percep.camera_score = score.score
        percep.camera_lock = lock
        percep.localized = True
        percep.game_started = True
        if not percep.home_set:
            from .geometry import player_world_x, player_world_y
            percep.home_x = player_world_x(percep)
            percep.home_y = player_world_y(percep)
            percep.home_set = True


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _score_better(new: CameraScore, best: CameraScore) -> bool:
    """Nim score ordering: fewer errors first, then more compared."""
    if new.errors != best.errors:
        return new.errors < best.errors
    return new.compared > best.compared


__all__ = [
    "FULL_FRAME_FIT_MAX_ERRORS",
    "LOCAL_FRAME_FIT_MAX_ERRORS",
    "FRAME_FIT_MIN_COMPARED",
    "LOCAL_FRAME_SEARCH_RADIUS",
    "PATCH_SIZE",
    "CameraScore",
    "PatchIndex",
    "score_camera",
    "get_patch_index",
    "Localizer",
]
