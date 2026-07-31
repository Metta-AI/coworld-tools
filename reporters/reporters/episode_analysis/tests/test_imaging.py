"""Tests for the dependency-free PNG/drawing primitives."""

from __future__ import annotations

import struct
import zlib

import numpy as np

from episode_analysis.imaging import (
    draw_disc,
    draw_line,
    draw_ring,
    png_bytes,
    upscale,
    write_png,
)


def _png_size(data: bytes) -> tuple[int, int]:
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    w, h = struct.unpack(">II", data[16:24])
    return w, h


def _decode_rgb(data: bytes, w: int, h: int) -> np.ndarray:
    # Single IDAT, filter 0 per row (how the encoder writes it).
    idat_start = data.index(b"IDAT") + 4
    idat_len = struct.unpack(">I", data[data.index(b"IDAT") - 4 : data.index(b"IDAT")])[0]
    raw = zlib.decompress(data[idat_start : idat_start + idat_len])
    rows = np.frombuffer(raw, np.uint8).reshape(h, 1 + w * 3)
    assert (rows[:, 0] == 0).all()
    return rows[:, 1:].reshape(h, w, 3)


def test_png_round_trip():
    img = np.zeros((5, 7, 3), np.uint8)
    img[2, 3] = (10, 200, 30)
    data = png_bytes(img)
    assert _png_size(data) == (7, 5)
    decoded = _decode_rgb(data, 7, 5)
    assert (decoded == img).all()


def test_write_png_matches_bytes(tmp_path):
    img = np.random.default_rng(0).integers(0, 255, (4, 6, 3), dtype=np.uint8)
    p = tmp_path / "out" / "img.png"
    write_png(img, p)  # creates parent dirs
    assert p.read_bytes() == png_bytes(img)


def test_draw_line_endpoints_and_clipping():
    img = np.zeros((10, 10, 3), np.uint8)
    draw_line(img, 1, 1, 8, 8, (255, 0, 0))
    assert (img[1, 1] == (255, 0, 0)).all() and (img[8, 8] == (255, 0, 0)).all()
    draw_line(img, -5, -5, 20, 5, (0, 255, 0))  # clipped, no raise


def test_draw_disc_and_ring():
    img = np.zeros((21, 21, 3), np.uint8)
    draw_disc(img, 10, 10, 3, (0, 0, 255))
    assert (img[10, 10] == (0, 0, 255)).all()
    assert (img[10, 14] == 0).all()  # outside radius
    draw_ring(img, 10, 10, 8, (255, 255, 0), width=1)
    assert (img[10, 10 + 8] == (255, 255, 0)).all()
    assert (img[10, 10 + 2] == (0, 0, 255)).all()  # disc interior untouched by ring
    assert (img[10, 10 + 5] == 0).all()  # gap between disc edge and ring inner


def test_upscale():
    img = np.arange(12, dtype=np.uint8).reshape(2, 2, 3)
    up = upscale(img, 3)
    assert up.shape == (6, 6, 3)
    assert (up[0:3, 0:3] == img[0, 0]).all()
    assert upscale(img, 1) is img
