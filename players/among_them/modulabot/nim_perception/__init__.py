"""Python ctypes shim for the modulabot Nim perception library.

Phase 0 responsibilities:

- Expose :data:`HAVE_NATIVE` so callers can fall back gracefully.
- Expose :data:`ABI_VERSION` (matches the Nim ``ModulabotPerceptionAbiVersion``
  constant; mismatch → library is rejected).
- Try to load the library at module import. Success sets
  ``HAVE_NATIVE = True`` and the raw ``_lib`` ctypes handle.
  Failure sets ``HAVE_NATIVE = False`` and stores the reason in
  :data:`LOAD_ERROR` for diagnostics. Nothing else in the module is
  allowed to touch the Nim library unless ``HAVE_NATIVE`` is True.

Phase 1 wrappers live at the bottom of this module (see
``match_actor_sprite_all`` / ``actor_color_index_all``). Each one takes
the same numpy arguments as the Python kernel it replaces and returns
the same shape, so call sites can do a flat ``if HAVE_NATIVE`` switch.

The loader is tolerant of two failure modes:

1. The library hasn't been built (first run on a fresh checkout).
   We call :func:`build.ensure_library` to build it on demand.
2. The library was built against a different FFI surface (ABI
   mismatch). We compare :func:`_lib.mb_abi_version` against
   :data:`ABI_VERSION`; mismatch → reject.

Both failure modes degrade to pure-Python. No exception propagates
out of import.
"""

from __future__ import annotations

import ctypes
import os
from pathlib import Path

import numpy as np

from . import build as _build

#: Bump whenever the ctypes surface changes. Keep in sync with
#: :data:`modulabot.nim_perception.build.ABI_VERSION` and
#: :data:`lib.nim::ModulabotPerceptionAbiVersion`.
ABI_VERSION = _build.ABI_VERSION

#: Pure-Python fallback flag. When False, every call site in
#: :mod:`modulabot.sprite_match` / :mod:`modulabot.localize` /
#: :mod:`modulabot.ascii` / etc. must take the numpy path.
HAVE_NATIVE: bool = False

#: Human-readable reason the library failed to load, or None. Useful
#: for logging / debug overlays; never consulted in the hot path.
LOAD_ERROR: str | None = None

#: Raw ctypes handle to the loaded library. None unless
#: ``HAVE_NATIVE``. Module-internal; callers should use the wrapper
#: functions added in later phases, not this handle directly.
_lib: ctypes.CDLL | None = None


# ---------------------------------------------------------------------------
# ctypes aliases
# ---------------------------------------------------------------------------
#
# Using ``ctypes.POINTER(ctypes.c_uint8)`` is fine for declaration, but
# passing a NumPy array as the argument requires
# ``arr.ctypes.data_as(ctypes.POINTER(c_uint8))`` every call. Aliasing
# here once shaves some startup cost and keeps call sites readable.

_u8p = ctypes.POINTER(ctypes.c_uint8)
_i8p = ctypes.POINTER(ctypes.c_int8)


def _bind(lib: ctypes.CDLL) -> None:
    """Declare ``restype`` / ``argtypes`` for every FFI entry point.

    Called once after the library loads and after ABI check passes.
    Must be kept in sync with ``src/sprite_match.nim`` (and any
    future kernel modules). Bump :data:`ABI_VERSION` whenever a
    signature changes.
    """
    lib.mb_abi_version.restype = ctypes.c_int
    lib.mb_abi_version.argtypes = []

    # mb_match_actor_sprite_all(frame, sprite, sh, sw, flip_h,
    #                           max_misses, min_stable, min_tint, out_mask)
    lib.mb_match_actor_sprite_all.restype = None
    lib.mb_match_actor_sprite_all.argtypes = [
        _u8p, _u8p,
        ctypes.c_int, ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int, ctypes.c_int, ctypes.c_int,
        _u8p,
    ]

    # mb_actor_color_index_all(frame, sprite, sh, sw, flip_h, out_indices)
    lib.mb_actor_color_index_all.restype = None
    lib.mb_actor_color_index_all.argtypes = [
        _u8p, _u8p,
        ctypes.c_int, ctypes.c_int,
        ctypes.c_int,
        _i8p,
    ]

    # Phase 2: mb_score_camera(frame, map, map_w, map_h, ignore, cx, cy,
    #                          max_errors, out_score_flag,
    #                          out_errors, out_compared, out_score)
    lib.mb_score_camera.restype = None
    lib.mb_score_camera.argtypes = [
        _u8p, _u8p,
        ctypes.c_int, ctypes.c_int,
        _u8p,
        ctypes.c_int, ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.POINTER(ctypes.c_int),
        ctypes.POINTER(ctypes.c_int),
        ctypes.POINTER(ctypes.c_int),
    ]

    # Phase 2: mb_hash_frame_patches(frame, ignore_mask, out_hashes, out_valid)
    lib.mb_hash_frame_patches.restype = None
    lib.mb_hash_frame_patches.argtypes = [
        _u8p, _u8p,
        ctypes.POINTER(ctypes.c_uint64),
        _u8p,
    ]

    # Phase 2.5: mb_vote_camera_candidates(
    #     frame_hashes, frame_valid,
    #     index_hashes, index_cam_xs, index_cam_ys, index_len,
    #     min_cx, max_cx, min_cy, max_cy,
    #     vote_buf, vote_buf_len,
    #     top_k, min_votes, max_matches_per_patch,
    #     out_cxs, out_cys, out_votes, out_count)
    lib.mb_vote_camera_candidates.restype = None
    lib.mb_vote_camera_candidates.argtypes = [
        ctypes.POINTER(ctypes.c_uint64),  # frame_hashes
        _u8p,                              # frame_valid
        ctypes.POINTER(ctypes.c_uint64),  # index_hashes
        ctypes.POINTER(ctypes.c_int32),   # index_cam_xs
        ctypes.POINTER(ctypes.c_int32),   # index_cam_ys
        ctypes.c_int,                      # index_len
        ctypes.c_int, ctypes.c_int,        # min_cx, max_cx
        ctypes.c_int, ctypes.c_int,        # min_cy, max_cy
        ctypes.POINTER(ctypes.c_uint16),  # vote_buf
        ctypes.c_int,                      # vote_buf_len
        ctypes.c_int, ctypes.c_int, ctypes.c_int,  # top_k, min_votes, max_matches
        ctypes.POINTER(ctypes.c_int32),   # out_cxs
        ctypes.POINTER(ctypes.c_int32),   # out_cys
        ctypes.POINTER(ctypes.c_int32),   # out_votes
        ctypes.POINTER(ctypes.c_int),     # out_count
    ]

    # Phase 3: mb_scan_task_icons(frame, sprite, sh, sw, task_coords,
    #     num_tasks, cam_x, cam_y, search_radius, max_matches,
    #     out_xs, out_ys, out_count)
    lib.mb_scan_task_icons.restype = None
    lib.mb_scan_task_icons.argtypes = [
        _u8p, _u8p,
        ctypes.c_int, ctypes.c_int,
        ctypes.POINTER(ctypes.c_int32),
        ctypes.c_int,
        ctypes.c_int, ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.POINTER(ctypes.c_int32),
        ctypes.POINTER(ctypes.c_int32),
        ctypes.POINTER(ctypes.c_int),
    ]

    # Phase 4: mb_best_glyph(frame, font_pixels, widths, opaque, prefs,
    #     num_glyphs, font_h, font_max_w, font_spacing,
    #     x, y, max_errors, background,
    #     out_glyph_idx, out_errors, out_advance)
    lib.mb_best_glyph.restype = None
    lib.mb_best_glyph.argtypes = [
        _u8p,                                # frame
        _u8p,                                # font_pixels
        ctypes.POINTER(ctypes.c_int32),     # widths
        ctypes.POINTER(ctypes.c_int32),     # opaque
        ctypes.POINTER(ctypes.c_int32),     # preferences
        ctypes.c_int,                        # num_glyphs
        ctypes.c_int, ctypes.c_int,          # font_h, font_max_w
        ctypes.c_int,                        # font_spacing
        ctypes.c_int, ctypes.c_int,          # x, y
        ctypes.c_int,                        # max_errors
        ctypes.c_int,                        # background
        ctypes.POINTER(ctypes.c_int),       # out_glyph_idx
        ctypes.POINTER(ctypes.c_int),       # out_errors
        ctypes.POINTER(ctypes.c_int),       # out_advance
    ]

    # Phase 4: mb_text_matches(frame, font_pixels, widths, font_h,
    #     font_max_w, font_spacing, text_indices, text_len,
    #     x, y, max_errors, background,
    #     out_matched, out_errors, out_opaque)
    lib.mb_text_matches.restype = None
    lib.mb_text_matches.argtypes = [
        _u8p,                                # frame
        _u8p,                                # font_pixels
        ctypes.POINTER(ctypes.c_int32),     # widths
        ctypes.c_int,                        # font_h
        ctypes.c_int,                        # font_max_w
        ctypes.c_int,                        # font_spacing
        ctypes.POINTER(ctypes.c_int32),     # text_indices
        ctypes.c_int,                        # text_len
        ctypes.c_int, ctypes.c_int,          # x, y
        ctypes.c_int,                        # max_errors
        ctypes.c_int,                        # background
        ctypes.POINTER(ctypes.c_int),       # out_matched
        ctypes.POINTER(ctypes.c_int),       # out_errors
        ctypes.POINTER(ctypes.c_int),       # out_opaque
    ]


def _try_load() -> None:
    """Populate ``_lib`` / ``HAVE_NATIVE`` / ``LOAD_ERROR``.

    Called once at import. Idempotent on re-entry (no global state
    beyond the three module-level variables).
    """
    global _lib, HAVE_NATIVE, LOAD_ERROR

    try:
        lib_path: Path = _build.ensure_library()
    except _build.NativeBuildDisabled as exc:
        LOAD_ERROR = str(exc)
        return
    except Exception as exc:  # pragma: no cover - unexpected build failure
        LOAD_ERROR = f"unexpected build failure: {exc!r}"
        return

    try:
        lib = ctypes.CDLL(str(lib_path))
    except OSError as exc:
        LOAD_ERROR = f"CDLL load failed: {exc}"
        return

    # ABI check: every future build must expose ``mb_abi_version`` and
    # return the matching version. A mismatch almost always means a
    # stale ``.dylib`` on disk built against an older FFI; the sidecar
    # hash should have caught it, but we belt-and-brace here.
    try:
        lib.mb_abi_version.restype = ctypes.c_int
        lib.mb_abi_version.argtypes = []
        native_version = int(lib.mb_abi_version())
    except (AttributeError, OSError) as exc:
        LOAD_ERROR = f"mb_abi_version missing or uncallable: {exc}"
        return
    if native_version != ABI_VERSION:
        LOAD_ERROR = (
            f"ABI version mismatch: native={native_version} "
            f"python={ABI_VERSION}; rebuild with "
            f"`python -m modulabot.nim_perception.build --force`"
        )
        return

    _bind(lib)
    _lib = lib
    HAVE_NATIVE = True


_try_load()


# ---------------------------------------------------------------------------
# NumPy helpers
# ---------------------------------------------------------------------------


def _as_u8_ptr(arr: np.ndarray) -> ctypes.POINTER:
    """Return a ``ctypes`` ``uint8*`` into a contiguous numpy buffer.

    Callers must guarantee the array is C-contiguous and
    ``dtype=uint8``; we assert those invariants rather than silently
    copying because every copy is a tax we don't want in the hot path.
    """
    assert arr.dtype == np.uint8, f"expected uint8, got {arr.dtype}"
    assert arr.flags["C_CONTIGUOUS"], "array must be C-contiguous"
    return arr.ctypes.data_as(_u8p)


def _as_i8_ptr(arr: np.ndarray) -> ctypes.POINTER:
    assert arr.dtype == np.int8, f"expected int8, got {arr.dtype}"
    assert arr.flags["C_CONTIGUOUS"], "array must be C-contiguous"
    return arr.ctypes.data_as(_i8p)


# ---------------------------------------------------------------------------
# Phase 1 wrappers: sprite matching
# ---------------------------------------------------------------------------


def match_actor_sprite_all(
    frame: np.ndarray,
    sprite_pixels: np.ndarray,
    flip_h: bool,
    *,
    max_misses: int,
    min_stable_pixels: int,
    min_tint_pixels: int,
) -> np.ndarray:
    """Call the Nim all-anchors sprite matcher, returning a bool array.

    Shape: ``(128 - sh + 1, 128 - sw + 1)``, dtype bool. Matches the
    vectorised Python
    :func:`modulabot.sprite_match.match_actor_sprite_all_anchors`
    byte-for-byte.

    Callers (``modulabot.sprite_match``) are expected to check
    ``HAVE_NATIVE`` before invoking this wrapper. Calling when
    ``HAVE_NATIVE=False`` raises :class:`RuntimeError`.
    """
    if not HAVE_NATIVE:
        raise RuntimeError(
            "mb_match_actor_sprite_all unavailable: "
            + (LOAD_ERROR or "library not loaded")
        )
    assert frame.shape == (128, 128), frame.shape
    sh, sw = sprite_pixels.shape
    max_y = 128 - sh + 1
    max_x = 128 - sw + 1
    if max_y <= 0 or max_x <= 0:
        return np.zeros((max(0, max_y), max(0, max_x)), dtype=bool)

    # Ensure contiguous uint8 without forcing a copy when already so.
    frame_c = np.ascontiguousarray(frame, dtype=np.uint8)
    sprite_c = np.ascontiguousarray(sprite_pixels, dtype=np.uint8)

    # Output buffer as uint8; cast to bool at the boundary.
    out = np.zeros((max_y, max_x), dtype=np.uint8)
    assert _lib is not None  # HAVE_NATIVE guarantees this
    _lib.mb_match_actor_sprite_all(
        _as_u8_ptr(frame_c),
        _as_u8_ptr(sprite_c),
        ctypes.c_int(sh),
        ctypes.c_int(sw),
        ctypes.c_int(1 if flip_h else 0),
        ctypes.c_int(max_misses),
        ctypes.c_int(min_stable_pixels),
        ctypes.c_int(min_tint_pixels),
        _as_u8_ptr(out),
    )
    return out.astype(bool, copy=False)


def actor_color_index_all(
    frame: np.ndarray,
    sprite_pixels: np.ndarray,
    flip_h: bool,
) -> np.ndarray:
    """Call the Nim all-anchors tint-colour classifier.

    Shape: ``(128 - sh + 1, 128 - sw + 1)``, dtype int8. Matches the
    vectorised Python
    :func:`modulabot.sprite_match.actor_color_index_all_anchors`
    element-for-element. ``-1`` at a position means "no lit-tint pixel
    voted for any player colour".
    """
    if not HAVE_NATIVE:
        raise RuntimeError(
            "mb_actor_color_index_all unavailable: "
            + (LOAD_ERROR or "library not loaded")
        )
    assert frame.shape == (128, 128), frame.shape
    sh, sw = sprite_pixels.shape
    max_y = 128 - sh + 1
    max_x = 128 - sw + 1
    if max_y <= 0 or max_x <= 0:
        return np.full((max(0, max_y), max(0, max_x)), -1, dtype=np.int8)

    frame_c = np.ascontiguousarray(frame, dtype=np.uint8)
    sprite_c = np.ascontiguousarray(sprite_pixels, dtype=np.uint8)
    out = np.full((max_y, max_x), -1, dtype=np.int8)
    assert _lib is not None
    _lib.mb_actor_color_index_all(
        _as_u8_ptr(frame_c),
        _as_u8_ptr(sprite_c),
        ctypes.c_int(sh),
        ctypes.c_int(sw),
        ctypes.c_int(1 if flip_h else 0),
        _as_i8_ptr(out),
    )
    return out


# ---------------------------------------------------------------------------
# Phase 2 wrappers: camera scoring + patch hashing
# ---------------------------------------------------------------------------


def score_camera(
    frame: np.ndarray,
    map_pixels: np.ndarray,
    ignore_mask: np.ndarray,
    cx: int,
    cy: int,
    max_errors: int,
) -> tuple[int, int, int]:
    """Call the Nim camera-scorer. Returns ``(score, errors, compared)``.

    Semantics match :func:`modulabot.localize.score_camera` /
    ``_score_camera_numpy``. The Python-side caller wraps this in a
    :class:`modulabot.localize.CameraScore` dataclass.

    Early-exit behaviour: when ``errors > max_errors`` the Nim kernel
    returns ``score=-errors`` and leaves ``compared`` reflecting only
    the pixels scanned so far. The Python caller already ignores
    ``compared`` on over-budget candidates, so this is safe.
    """
    if not HAVE_NATIVE:
        raise RuntimeError(
            "mb_score_camera unavailable: "
            + (LOAD_ERROR or "library not loaded")
        )
    assert _lib is not None
    frame_c = np.ascontiguousarray(frame, dtype=np.uint8)
    map_c = np.ascontiguousarray(map_pixels, dtype=np.uint8)
    # ignore_mask is bool in Python; Nim expects uint8 (0/1).
    ignore_c = np.ascontiguousarray(ignore_mask, dtype=np.uint8)

    out_errors = ctypes.c_int(0)
    out_compared = ctypes.c_int(0)
    out_score = ctypes.c_int(0)
    map_h, map_w = map_c.shape
    _lib.mb_score_camera(
        _as_u8_ptr(frame_c),
        _as_u8_ptr(map_c),
        ctypes.c_int(map_w),
        ctypes.c_int(map_h),
        _as_u8_ptr(ignore_c),
        ctypes.c_int(cx),
        ctypes.c_int(cy),
        ctypes.c_int(max_errors),
        ctypes.c_int(1),  # compute score
        ctypes.byref(out_errors),
        ctypes.byref(out_compared),
        ctypes.byref(out_score),
    )
    return (int(out_score.value), int(out_errors.value), int(out_compared.value))


def hash_frame_patches(
    frame: np.ndarray,
    ignore_mask: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    """Call the Nim frame-patch hasher.

    Returns ``(hashes, valid)`` where ``hashes`` is a
    ``(16, 16) uint64`` array of FNV-style patch hashes and ``valid``
    is a ``(16, 16) bool`` mask (False iff any pixel in the patch
    was ignored). Semantics match the numpy fallback in
    :mod:`modulabot.localize`.
    """
    if not HAVE_NATIVE:
        raise RuntimeError(
            "mb_hash_frame_patches unavailable: "
            + (LOAD_ERROR or "library not loaded")
        )
    assert _lib is not None
    frame_c = np.ascontiguousarray(frame, dtype=np.uint8)
    ignore_c = np.ascontiguousarray(ignore_mask, dtype=np.uint8)

    out_hashes = np.zeros((16, 16), dtype=np.uint64)
    out_valid = np.zeros((16, 16), dtype=np.uint8)
    _lib.mb_hash_frame_patches(
        _as_u8_ptr(frame_c),
        _as_u8_ptr(ignore_c),
        out_hashes.ctypes.data_as(ctypes.POINTER(ctypes.c_uint64)),
        _as_u8_ptr(out_valid),
    )
    return out_hashes, out_valid.astype(bool, copy=False)


def vote_camera_candidates(
    frame_hashes: np.ndarray,
    frame_valid: np.ndarray,
    index_hashes: np.ndarray,
    index_cam_xs: np.ndarray,
    index_cam_ys: np.ndarray,
    *,
    min_cx: int,
    max_cx: int,
    min_cy: int,
    max_cy: int,
    vote_buf: np.ndarray,
    top_k: int,
    min_votes: int,
    max_matches_per_patch: int,
) -> list[tuple[int, int, int]]:
    """Bulk Phase-2.5 kernel: patch vote loop in one Nim call.

    Takes the pre-hashed frame patches and the pre-built map patch
    index; returns a list of ``(cx, cy, votes)`` candidates, ordered
    descending by votes (ties broken by ascending ``(cy, cx)`` to
    match numpy ``np.lexsort``).

    ``vote_buf`` is a caller-owned ``uint16`` scratch array of size
    ``(max_cy - min_cy + 1) * (max_cx - min_cx + 1)``. Nim zeroes
    only the slots it touches, so reusing the same buffer across
    calls is a meaningful win over re-allocating every frame. The
    :class:`modulabot.localize.Localizer` already caches an
    equivalent ``_votes`` buffer; we hand it straight through.
    """
    if not HAVE_NATIVE:
        raise RuntimeError(
            "mb_vote_camera_candidates unavailable: "
            + (LOAD_ERROR or "library not loaded")
        )
    assert _lib is not None
    fh = np.ascontiguousarray(frame_hashes, dtype=np.uint64)
    fv = np.ascontiguousarray(frame_valid, dtype=np.uint8)
    ih = np.ascontiguousarray(index_hashes, dtype=np.uint64)
    ixs = np.ascontiguousarray(index_cam_xs, dtype=np.int32)
    iys = np.ascontiguousarray(index_cam_ys, dtype=np.int32)
    assert vote_buf.dtype == np.uint16 and vote_buf.flags["C_CONTIGUOUS"]

    # Output buffers: top_k slots for each of cx / cy / votes.
    out_cxs = np.zeros(top_k, dtype=np.int32)
    out_cys = np.zeros(top_k, dtype=np.int32)
    out_votes = np.zeros(top_k, dtype=np.int32)
    out_count = ctypes.c_int(0)

    _lib.mb_vote_camera_candidates(
        fh.ctypes.data_as(ctypes.POINTER(ctypes.c_uint64)),
        _as_u8_ptr(fv),
        ih.ctypes.data_as(ctypes.POINTER(ctypes.c_uint64)),
        ixs.ctypes.data_as(ctypes.POINTER(ctypes.c_int32)),
        iys.ctypes.data_as(ctypes.POINTER(ctypes.c_int32)),
        ctypes.c_int(int(ih.size)),
        ctypes.c_int(min_cx), ctypes.c_int(max_cx),
        ctypes.c_int(min_cy), ctypes.c_int(max_cy),
        vote_buf.ctypes.data_as(ctypes.POINTER(ctypes.c_uint16)),
        ctypes.c_int(vote_buf.size),
        ctypes.c_int(top_k),
        ctypes.c_int(min_votes),
        ctypes.c_int(max_matches_per_patch),
        out_cxs.ctypes.data_as(ctypes.POINTER(ctypes.c_int32)),
        out_cys.ctypes.data_as(ctypes.POINTER(ctypes.c_int32)),
        out_votes.ctypes.data_as(ctypes.POINTER(ctypes.c_int32)),
        ctypes.byref(out_count),
    )
    n = out_count.value
    return [
        (int(out_cxs[i]), int(out_cys[i]), int(out_votes[i]))
        for i in range(n)
    ]


# ---------------------------------------------------------------------------
# Phase 3 wrappers: task icon + radar scanners
# ---------------------------------------------------------------------------


def scan_task_icons(
    frame: np.ndarray,
    sprite_pixels: np.ndarray,
    task_coords: np.ndarray,
    cam_x: int,
    cam_y: int,
    search_radius: int,
    max_matches: int = 64,
) -> list[tuple[int, int]]:
    """Bulk Nim kernel for :func:`modulabot.actors.scan_task_icons`.

    ``task_coords`` is an ``(N, 4) int32`` array of ``(x, y, w, h)``
    task rects. Returns ``[(x, y), …]`` deduped icon matches in the
    order Nim found them (raster scan over tasks × bob × dy × dx);
    order matches the pre-FFI Python implementation, so snapshot
    tests keep agreeing.

    ``max_matches`` is an output cap. Real frames produce <5 matches
    in practice (only on-screen tasks hit); the cap exists to keep
    the output buffers tiny and to make runaway pathological frames
    self-limiting.
    """
    if not HAVE_NATIVE:
        raise RuntimeError(
            "mb_scan_task_icons unavailable: "
            + (LOAD_ERROR or "library not loaded")
        )
    assert _lib is not None
    frame_c = np.ascontiguousarray(frame, dtype=np.uint8)
    sprite_c = np.ascontiguousarray(sprite_pixels, dtype=np.uint8)
    tc = np.ascontiguousarray(task_coords, dtype=np.int32)
    assert tc.ndim == 2 and tc.shape[1] == 4, tc.shape

    out_xs = np.zeros(max_matches, dtype=np.int32)
    out_ys = np.zeros(max_matches, dtype=np.int32)
    out_count = ctypes.c_int(0)
    sh, sw = sprite_c.shape

    _lib.mb_scan_task_icons(
        _as_u8_ptr(frame_c),
        _as_u8_ptr(sprite_c),
        ctypes.c_int(sh), ctypes.c_int(sw),
        tc.ctypes.data_as(ctypes.POINTER(ctypes.c_int32)),
        ctypes.c_int(tc.shape[0]),
        ctypes.c_int(cam_x), ctypes.c_int(cam_y),
        ctypes.c_int(search_radius),
        ctypes.c_int(max_matches),
        out_xs.ctypes.data_as(ctypes.POINTER(ctypes.c_int32)),
        out_ys.ctypes.data_as(ctypes.POINTER(ctypes.c_int32)),
        ctypes.byref(out_count),
    )
    n = out_count.value
    return [(int(out_xs[i]), int(out_ys[i])) for i in range(n)]


# ---------------------------------------------------------------------------
# Phase 4: packed-font cache for OCR
# ---------------------------------------------------------------------------
#
# The Nim OCR kernels take the font as flat C arrays rather than the
# PixelFont dataclass. Packing is O(total glyph pixels), ~40 KB for
# tiny5 — cheap, but the Nim kernels need the data as contiguous
# uint8/int32 numpy arrays so we memoise a packed struct keyed on
# ``id(font)``. One font per process → effectively permanent.

_FIRST_PRINTABLE_ASCII = 32


class _PackedFont:
    """Flat numpy buffers for one :class:`~modulabot.data.PixelFont`.

    The Nim OCR kernels read ``pixels`` / ``widths`` / ``opaque`` /
    ``preferences`` directly; the Python side keeps strong refs on
    this object for the duration of every call to guarantee the
    buffers outlive the FFI call. Don't pickle it; rebuild on
    unpickle.
    """

    __slots__ = (
        "pixels",
        "widths",
        "opaque",
        "preferences",
        "num_glyphs",
        "height",
        "max_width",
        "spacing",
        "char_to_index",
    )

    def __init__(
        self,
        pixels: np.ndarray,
        widths: np.ndarray,
        opaque: np.ndarray,
        preferences: np.ndarray,
        num_glyphs: int,
        height: int,
        max_width: int,
        spacing: int,
        char_to_index: dict[str, int],
    ) -> None:
        self.pixels = pixels
        self.widths = widths
        self.opaque = opaque
        self.preferences = preferences
        self.num_glyphs = num_glyphs
        self.height = height
        self.max_width = max_width
        self.spacing = spacing
        self.char_to_index = char_to_index


_PACKED_FONT_CACHE: dict[int, _PackedFont] = {}


def _glyph_preference(ch: str) -> int:
    """Mirror :func:`modulabot.ascii._glyph_preference`. Duplicated
    here so the FFI module doesn't import ascii (circular)."""
    if "a" <= ch <= "z":
        return 4
    if "0" <= ch <= "9":
        return 3
    if "A" <= ch <= "Z":
        return 2
    if ch == " ":
        return 1
    return 0


def _pack_font(font) -> _PackedFont:
    """Pack a :class:`~modulabot.data.PixelFont` into contiguous
    numpy buffers.

    The pixel array has shape ``(num_glyphs, height, max_width)``
    with zero-padding past each glyph's actual width. Values are
    ``uint8`` 0/1 so the Nim side can read them directly without a
    bool → uint8 cast in the hot path.
    """
    key = id(font)
    cached = _PACKED_FONT_CACHE.get(key)
    if cached is not None:
        return cached

    height = int(font.height)
    spacing = int(font.spacing)
    glyphs = font.glyphs
    num_glyphs = len(glyphs)
    max_width = max((int(g.width) for g in glyphs), default=0)
    pixels = np.zeros((num_glyphs, height, max_width), dtype=np.uint8)
    widths = np.zeros(num_glyphs, dtype=np.int32)
    opaque = np.zeros(num_glyphs, dtype=np.int32)
    preferences = np.zeros(num_glyphs, dtype=np.int32)
    char_to_index: dict[str, int] = {}

    for i, g in enumerate(glyphs):
        w = int(g.width)
        widths[i] = w
        if w > 0:
            # PixelGlyph.pixels is bool (h, w). Copy directly into
            # the front of the packed row.
            pixels[i, :height, :w] = g.pixels.astype(np.uint8)
            opaque[i] = int(g.pixels.sum())
        ch = chr(_FIRST_PRINTABLE_ASCII + i)
        preferences[i] = _glyph_preference(ch)
        char_to_index[ch] = i

    # Ensure contiguous for pointer-cast.
    pixels = np.ascontiguousarray(pixels)
    widths = np.ascontiguousarray(widths)
    opaque = np.ascontiguousarray(opaque)
    preferences = np.ascontiguousarray(preferences)

    packed = _PackedFont(
        pixels=pixels,
        widths=widths,
        opaque=opaque,
        preferences=preferences,
        num_glyphs=num_glyphs,
        height=height,
        max_width=max_width,
        spacing=spacing,
        char_to_index=char_to_index,
    )
    _PACKED_FONT_CACHE[key] = packed
    return packed


# ---------------------------------------------------------------------------
# Phase 4 wrappers: OCR
# ---------------------------------------------------------------------------


def best_glyph(
    frame: np.ndarray,
    font,
    x: int,
    y: int,
    max_errors: int = 0,
    background: int = 0,
) -> tuple[str, int, int]:
    """Return ``(char, errors, advance)`` for the best-matching glyph
    at ``(x, y)``.

    Mirrors :func:`modulabot.ascii.best_glyph`'s semantics; the only
    difference is the Python wrapper returns ``advance`` (pen step)
    alongside the character so the caller doesn't have to recompute
    it. ``char`` is ``'?'`` when no glyph clears ``max_errors``.
    """
    if not HAVE_NATIVE:
        raise RuntimeError(
            "mb_best_glyph unavailable: "
            + (LOAD_ERROR or "library not loaded")
        )
    assert _lib is not None
    packed = _pack_font(font)
    frame_c = np.ascontiguousarray(frame, dtype=np.uint8)

    out_idx = ctypes.c_int(0)
    out_errors = ctypes.c_int(0)
    out_advance = ctypes.c_int(0)
    _lib.mb_best_glyph(
        _as_u8_ptr(frame_c),
        _as_u8_ptr(packed.pixels),
        packed.widths.ctypes.data_as(ctypes.POINTER(ctypes.c_int32)),
        packed.opaque.ctypes.data_as(ctypes.POINTER(ctypes.c_int32)),
        packed.preferences.ctypes.data_as(ctypes.POINTER(ctypes.c_int32)),
        ctypes.c_int(packed.num_glyphs),
        ctypes.c_int(packed.height),
        ctypes.c_int(packed.max_width),
        ctypes.c_int(packed.spacing),
        ctypes.c_int(x), ctypes.c_int(y),
        ctypes.c_int(max_errors),
        ctypes.c_int(background),
        ctypes.byref(out_idx),
        ctypes.byref(out_errors),
        ctypes.byref(out_advance),
    )
    idx = out_idx.value
    if idx < 0:
        return ("?", int(out_errors.value), 0)
    ch = chr(_FIRST_PRINTABLE_ASCII + idx)
    return (ch, int(out_errors.value), int(out_advance.value))


def text_matches(
    frame: np.ndarray,
    font,
    text: str,
    x: int,
    y: int,
    max_errors: int = 0,
    background: int = 0,
) -> bool:
    """Mirror :func:`modulabot.ascii.text_matches`.

    Encodes ``text`` as a list of glyph indices (``-1`` for newline)
    and calls the Nim ``mb_text_matches`` kernel. Returns
    ``True`` iff some glyph pixels were expected and the total
    mismatch count is within budget.
    """
    if not HAVE_NATIVE:
        raise RuntimeError(
            "mb_text_matches unavailable: "
            + (LOAD_ERROR or "library not loaded")
        )
    if not text:
        return False
    assert _lib is not None
    packed = _pack_font(font)

    # Encode: -1 for newline, otherwise the glyph index (or the
    # index of '?' for characters the font doesn't cover).
    q_idx = packed.char_to_index.get("?", -2)
    text_indices = np.empty(len(text), dtype=np.int32)
    for i, ch in enumerate(text):
        if ch == "\n":
            text_indices[i] = -1
        else:
            text_indices[i] = packed.char_to_index.get(ch, q_idx)
    text_indices = np.ascontiguousarray(text_indices)
    frame_c = np.ascontiguousarray(frame, dtype=np.uint8)

    out_matched = ctypes.c_int(0)
    out_errors = ctypes.c_int(0)
    out_opaque = ctypes.c_int(0)
    _lib.mb_text_matches(
        _as_u8_ptr(frame_c),
        _as_u8_ptr(packed.pixels),
        packed.widths.ctypes.data_as(ctypes.POINTER(ctypes.c_int32)),
        ctypes.c_int(packed.height),
        ctypes.c_int(packed.max_width),
        ctypes.c_int(packed.spacing),
        text_indices.ctypes.data_as(ctypes.POINTER(ctypes.c_int32)),
        ctypes.c_int(len(text)),
        ctypes.c_int(x), ctypes.c_int(y),
        ctypes.c_int(max_errors),
        ctypes.c_int(background),
        ctypes.byref(out_matched),
        ctypes.byref(out_errors),
        ctypes.byref(out_opaque),
    )
    return out_matched.value == 1


# ---------------------------------------------------------------------------
# Public surface
# ---------------------------------------------------------------------------

__all__ = [
    "ABI_VERSION",
    "HAVE_NATIVE",
    "LOAD_ERROR",
    "match_actor_sprite_all",
    "actor_color_index_all",
    "score_camera",
    "hash_frame_patches",
    "vote_camera_candidates",
    "scan_task_icons",
    "best_glyph",
    "text_matches",
]
