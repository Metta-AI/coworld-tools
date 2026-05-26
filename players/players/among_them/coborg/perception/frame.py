"""Frame-level primitives: 4-bpp unpacking and palette-indexed frame helpers.

Port of ``users/james/personal_cogs/among_them/guided_bot/perception/frame.nim``
(Phase 1.0 in the upstream port plan). Pure numpy, no baked-asset dependency.

Public surface mirrors the Nim names 1:1 so the parity rig can compare outputs
symbol-by-symbol against the upstream oracle.
"""

from __future__ import annotations

from typing import Union

import numpy as np

SCREEN_WIDTH = 128
SCREEN_HEIGHT = 128

# Unpacked frame size: one palette-index byte per pixel.
FRAME_LEN = SCREEN_WIDTH * SCREEN_HEIGHT  # 16384

# Wire format size: 4-bit-packed, two pixels per byte.
PACKED_FRAME_LEN = FRAME_LEN // 2  # 8192

# Type alias for "anything that np.frombuffer can read as bytes". Avoids
# narrowing the inbound BitWorld bridge surface (which delivers `bytes`)
# while still tolerating numpy arrays, bytearrays, and memoryviews from tests.
PackedSource = Union[bytes, bytearray, memoryview, np.ndarray]


def unpack4bpp(packed: PackedSource) -> np.ndarray:
    """Expand a 4-bit-packed wire-format frame into one palette-index byte per pixel.

    Two pixels per source byte: low nybble at pixel ``2i``, high nybble at
    pixel ``2i + 1``, row-major. Returns a ``(SCREEN_HEIGHT, SCREEN_WIDTH)``
    ``uint8`` array.

    Mirrors ``unpack4bpp`` in ``guided_bot/perception/frame.nim``. The Nim
    side fails loudly on length mismatch; we do too.
    """
    if isinstance(packed, np.ndarray):
        arr = packed.astype(np.uint8, copy=False).reshape(-1)
    else:
        arr = np.frombuffer(packed, dtype=np.uint8)
    if arr.size != PACKED_FRAME_LEN:
        raise ValueError(
            f"unpack4bpp: expected {PACKED_FRAME_LEN} packed bytes, got {arr.size}"
        )
    out = np.empty(FRAME_LEN, dtype=np.uint8)
    out[0::2] = arr & 0x0F
    out[1::2] = arr >> 4
    return out.reshape((SCREEN_HEIGHT, SCREEN_WIDTH))


def pack4bpp(unpacked: np.ndarray) -> bytes:
    """Inverse of :func:`unpack4bpp`. Test helper only.

    Production traffic is one-way (BitWorld -> us), so the bridge only ever
    unpacks. This pack proc exists so unit tests can round-trip an unpacked
    fixture through the wire format and assert byte equality.

    Pixel values must be in ``[0, 15]``; the proc masks each value to 4 bits.
    """
    flat = np.asarray(unpacked, dtype=np.uint8).reshape(-1)
    if flat.size != FRAME_LEN:
        raise ValueError(f"pack4bpp: expected {FRAME_LEN} pixels, got {flat.size}")
    lo = flat[0::2] & 0x0F
    hi = (flat[1::2] & 0x0F) << 4
    return (lo | hi).tobytes()


def black_pixel_count(frame: np.ndarray) -> int:
    """Count pixels with palette index 0 (PICO-8 black).

    Foundational input to the interstitial-screen detector (ported in S4).
    Kept here because it's a per-pixel primitive with no notion of what
    "interstitial" means - that classification is one level up.
    """
    return int(np.count_nonzero(np.asarray(frame) == 0))


def pixel_at(frame: np.ndarray, x: int, y: int) -> int:
    """Safe indexed pixel access. Returns 0 for out-of-bounds reads.

    Mirrors ``pixelAt`` in the Nim port. The 0-return matches the Nim
    proc's behaviour and conveniently coincides with the ``MapVoidColor``
    sentinel used elsewhere; downstream code can treat OOB as "void".
    """
    if x < 0 or x >= SCREEN_WIDTH or y < 0 or y >= SCREEN_HEIGHT:
        return 0
    return int(frame[y, x])


# Sentinel palette value for out-of-screen pixels in patches built by
# :func:`oob_filled_patch`. 255 is safe to use as an in-band sentinel
# because real frames are 4-bpp (palette indices 0..15) so 255 never
# appears in a legitimate frame pixel. ``PLAYER_BODY_LUT[255]`` and
# ``PALETTE_TO_PLAYER_SLOT[255]`` are both "not a player color", and
# strict matches against any palette 0..15 sprite pixel will count
# OOB as a miss because 255 != that pixel.
OOB_SENTINEL: np.uint8 = np.uint8(255)


def oob_filled_patch(
    frame: np.ndarray, x: int, y: int, shape: tuple[int, int]
) -> np.ndarray:
    """Return a ``shape``-sized uint8 patch of ``frame`` anchored at
    ``(x, y)``, with out-of-screen pixels filled with :data:`OOB_SENTINEL`.

    Lets numpy-vectorised match helpers skip the per-pixel OOB branch by
    making the OOB rule fall out of the same boolean-mask arithmetic the
    in-bounds rule already uses. Shared between
    :mod:`perception.actors` (HUD / crewmate scalar probes) and
    :mod:`perception.tasks` (task-icon strict matches).
    """
    sh, sw = shape
    patch = np.full((sh, sw), OOB_SENTINEL, dtype=np.uint8)
    fy0, fx0 = max(0, y), max(0, x)
    fy1 = min(SCREEN_HEIGHT, y + sh)
    fx1 = min(SCREEN_WIDTH, x + sw)
    if fy0 < fy1 and fx0 < fx1:
        py0, px0 = fy0 - y, fx0 - x
        py1, px1 = fy1 - y, fx1 - x
        patch[py0:py1, px0:px1] = frame[fy0:fy1, fx0:fx1]
    return patch


def new_ignore_mask() -> np.ndarray:
    """Allocate a fresh ``(SCREEN_HEIGHT, SCREEN_WIDTH)`` bool ignore mask.

    Mirrors ``initIgnoreMask`` in ``guided_bot/perception/frame.nim``. The
    Nim version wraps a flat ``seq[uint8]`` inside an ``IgnoreMask`` object
    because Nim lacks natural multi-dimensional arrays; in numpy a bare
    ``bool`` ndarray is idiomatic and the rest of the perception layer
    consumes it directly.

    Stamping helpers (player-centre zone, radar pixels, sprite rects,
    nameplate rects, the whole-frame phase-1.0 mask) live in
    ``perception/ignore.py`` per the upstream module split; see S4.
    """
    return np.zeros((SCREEN_HEIGHT, SCREEN_WIDTH), dtype=bool)
