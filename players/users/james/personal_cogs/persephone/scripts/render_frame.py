#!/usr/bin/env python3
"""Render .npy frames to PNG using the PICO-8 palette.

Usage:
    python scripts/render_frame.py path/to/frame.npy -o output.png
    python scripts/render_frame.py path/to/capture.npy --tick 200 -o frame200.png
    python scripts/render_frame.py path/to/frame.npy --scale 4 -o big.png
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np

try:
    from PIL import Image
except ImportError:
    print("Error: Pillow is required. Install with: pip install Pillow", file=sys.stderr)
    sys.exit(1)

# PICO-8 palette (16 colors) as RGB tuples
PICO8_PALETTE = [
    (0x00, 0x00, 0x00),  # 0  black
    (0x1D, 0x2B, 0x53),  # 1  dark blue
    (0x7E, 0x25, 0x53),  # 2  dark magenta
    (0x00, 0x87, 0x51),  # 3  dark green
    (0xAB, 0x52, 0x36),  # 4  brown
    (0x5F, 0x57, 0x4F),  # 5  dark gray
    (0xC2, 0xC3, 0xC7),  # 6  light gray
    (0xFF, 0xF1, 0xE8),  # 7  white
    (0xFF, 0x00, 0x4D),  # 8  red
    (0xFF, 0xA3, 0x00),  # 9  orange
    (0xFF, 0xEC, 0x27),  # 10 yellow
    (0x00, 0xE4, 0x36),  # 11 green
    (0x29, 0xAD, 0xFF),  # 12 blue
    (0x83, 0x76, 0x9C),  # 13 lavender
    (0xFF, 0x77, 0xA8),  # 14 pink
    (0xFF, 0xCC, 0xAA),  # 15 peach
]


def render_frame(frame: np.ndarray, scale: int = 1) -> Image.Image:
    """Convert a (128, 128) uint8 palette-index array to an RGB PIL Image."""
    assert frame.shape == (128, 128), f"Expected (128, 128), got {frame.shape}"
    assert frame.dtype == np.uint8

    # Build RGB image
    rgb = np.zeros((128, 128, 3), dtype=np.uint8)
    for idx, (r, g, b) in enumerate(PICO8_PALETTE):
        mask = frame == idx
        rgb[mask] = [r, g, b]

    img = Image.fromarray(rgb, mode="RGB")

    if scale > 1:
        img = img.resize((128 * scale, 128 * scale), Image.NEAREST)

    return img


def main() -> int:
    parser = argparse.ArgumentParser(description="Render .npy frames to PNG.")
    parser.add_argument("input", type=Path, help="Path to .npy file")
    parser.add_argument("-o", "--output", type=Path, default=None, help="Output PNG path")
    parser.add_argument("--tick", type=int, default=None, help="Frame index for multi-frame .npy")
    parser.add_argument("--scale", type=int, default=4, help="Pixel scaling factor (default: 4)")

    args = parser.parse_args()

    if not args.input.is_file():
        print(f"Error: {args.input} not found", file=sys.stderr)
        return 1

    data = np.load(args.input)

    # Single frame or multi-frame
    if data.ndim == 2:
        frame = data
    elif data.ndim == 3:
        if args.tick is None:
            args.tick = 0
        if args.tick >= len(data):
            print(f"Error: tick {args.tick} out of range (0-{len(data)-1})", file=sys.stderr)
            return 1
        frame = data[args.tick]
    else:
        print(f"Error: unexpected array shape {data.shape}", file=sys.stderr)
        return 1

    img = render_frame(frame, scale=args.scale)

    output = args.output or args.input.with_suffix(".png")
    img.save(output)
    print(f"Rendered {frame.shape} frame -> {output} (scale={args.scale}x)")

    return 0


if __name__ == "__main__":
    sys.exit(main())
