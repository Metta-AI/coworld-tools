"""Tiny dependency-free image primitives: draw onto and PNG-encode numpy arrays.

stdlib ``struct``/``zlib`` + numpy only -- no Pillow, no matplotlib. Lets a
reporter or diagnoser emit raster artifacts (debug overlays, minimaps) without
paying for a plotting stack. Images are ``(H, W, 3)`` uint8 RGB; colors are
``(r, g, b)`` tuples.

Origin: extracted near-verbatim from Ron Dahlgren's (swgy) crewrift tooling
(``swgy_tools.imaging``); ``png_bytes`` added because reporters write into
zips rather than to paths.
"""

from __future__ import annotations

import struct
import zlib
from pathlib import Path

import numpy as np


def draw_line(img: np.ndarray, x0: int, y0: int, x1: int, y1: int, rgb) -> None:
    """Bresenham line from ``(x0, y0)`` to ``(x1, y1)`` in place, clipped."""
    h, w = img.shape[:2]
    x0, y0, x1, y1 = int(x0), int(y0), int(x1), int(y1)
    dx, dy = abs(x1 - x0), -abs(y1 - y0)
    sx, sy = (1 if x0 < x1 else -1), (1 if y0 < y1 else -1)
    err = dx + dy
    while True:
        if 0 <= x0 < w and 0 <= y0 < h:
            img[y0, x0] = rgb
        if x0 == x1 and y0 == y1:
            break
        e2 = 2 * err
        if e2 >= dy:
            err += dy
            x0 += sx
        if e2 <= dx:
            err += dx
            y0 += sy


def draw_disc(img: np.ndarray, cx: int, cy: int, r: int, rgb) -> None:
    """Filled disc of radius ``r`` px centered at ``(cx, cy)``, clipped."""
    h, w = img.shape[:2]
    x0, x1 = max(0, cx - r), min(w, cx + r + 1)
    y0, y1 = max(0, cy - r), min(h, cy + r + 1)
    if x1 <= x0 or y1 <= y0:
        return
    ys, xs = np.ogrid[y0:y1, x0:x1]
    sel = (xs - cx) ** 2 + (ys - cy) ** 2 <= r * r
    img[y0:y1, x0:x1][sel] = rgb


def draw_ring(img: np.ndarray, cx: int, cy: int, r: int, rgb, width: int = 1) -> None:
    """Hollow ring (outer radius ``r``, given ``width``) at ``(cx, cy)``, clipped."""
    h, w = img.shape[:2]
    inner = max(0, r - width)
    x0, x1 = max(0, cx - r), min(w, cx + r + 1)
    y0, y1 = max(0, cy - r), min(h, cy + r + 1)
    if x1 <= x0 or y1 <= y0:
        return
    ys, xs = np.ogrid[y0:y1, x0:x1]
    d2 = (xs - cx) ** 2 + (ys - cy) ** 2
    sel = (d2 <= r * r) & (d2 >= inner * inner)
    img[y0:y1, x0:x1][sel] = rgb


def upscale(img: np.ndarray, factor: int) -> np.ndarray:
    """Nearest-neighbor integer upscale by ``factor`` (no-op if <= 1)."""
    if factor <= 1:
        return img
    return np.repeat(np.repeat(img, factor, axis=0), factor, axis=1)


def _png_chunk(tag: bytes, data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data))


def write_png(img: np.ndarray, path: str | Path) -> None:
    """Write an ``(H, W, 3)`` (or 4) uint8 array as an RGB PNG (zlib stdlib only)."""
    h, w = img.shape[:2]
    rgb = np.ascontiguousarray(img[:, :, :3], dtype=np.uint8)
    raw = np.hstack(
        [np.zeros((h, 1), np.uint8), rgb.reshape(h, w * 3)]
    ).tobytes()  # filter byte 0/row
    ihdr = struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)  # 8-bit truecolor RGB
    data = (
        b"\x89PNG\r\n\x1a\n"
        + _png_chunk(b"IHDR", ihdr)
        + _png_chunk(b"IDAT", zlib.compress(raw, 9))
        + _png_chunk(b"IEND", b"")
    )
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def png_bytes(img: np.ndarray) -> bytes:
    """PNG-encode an ``(H, W, 3)`` (or 4) uint8 array to bytes (no file I/O)."""
    h, w = img.shape[:2]
    rgb = np.ascontiguousarray(img[:, :, :3], dtype=np.uint8)
    raw = np.hstack(
        [np.zeros((h, 1), np.uint8), rgb.reshape(h, w * 3)]
    ).tobytes()  # filter byte 0/row
    ihdr = struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)  # 8-bit truecolor RGB
    return (
        b"\x89PNG\r\n\x1a\n"
        + _png_chunk(b"IHDR", ihdr)
        + _png_chunk(b"IDAT", zlib.compress(raw, 9))
        + _png_chunk(b"IEND", b"")
    )
