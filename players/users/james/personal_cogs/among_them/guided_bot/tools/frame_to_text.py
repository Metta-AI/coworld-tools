#!/usr/bin/env python3
"""Convert frames.bin frames to text grids for LLM-readable inspection.

Each pixel becomes a character A-P representing palette indices 0-15:

    A = 0 (black)        I = 8  (yellow)
    B = 1 (light grey)   J = 9  (dark purple)
    C = 2 (white)        K = 10 (dark green)
    D = 3 (red)          L = 11 (green)
    E = 4 (pink)         M = 12 (dark navy)
    F = 5 (dark grey)    N = 13 (indigo)
    G = 6 (brown)        O = 14 (blue)
    H = 7 (orange)       P = 15 (peach)

Usage:
    # Dump frame 150 from bot_0's trace to stdout:
    PYTHONPATH=among_them .venv/bin/python \\
        among_them/guided_bot/tools/frame_to_text.py \\
        among_them/guided_bot/traces/bot_0 --frame 150

    # Dump frames 100-105 to a file:
    PYTHONPATH=among_them .venv/bin/python \\
        among_them/guided_bot/tools/frame_to_text.py \\
        among_them/guided_bot/traces/bot_0 --frame 100 --count 6 \\
        --output /tmp/frames_100_105.txt

    # Dump with a legend header:
    PYTHONPATH=among_them .venv/bin/python \\
        among_them/guided_bot/tools/frame_to_text.py \\
        among_them/guided_bot/traces/bot_0 --frame 150 --legend
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np

FRAME_W = 128
FRAME_H = 128
FRAME_BYTES = FRAME_W * FRAME_H

# Character mapping: palette index 0-15 → 'A'-'P'.
INDEX_TO_CHAR = "ABCDEFGHIJKLMNOP"

LEGEND = """\
Palette legend:
  A = 0  black         I = 8  yellow
  B = 1  light grey    J = 9  dark purple
  C = 2  white         K = 10 dark green
  D = 3  red           L = 11 green
  E = 4  pink          M = 12 dark navy
  F = 5  dark grey     N = 13 indigo
  G = 6  brown         O = 14 blue
  H = 7  orange        P = 15 peach
"""


def load_frames(path: Path) -> np.ndarray:
    """Load frames.bin → (N, 128, 128) uint8."""
    data = np.fromfile(path, dtype=np.uint8)
    if data.size == 0:
        print(f"Error: {path} is empty.", file=sys.stderr)
        sys.exit(1)
    n = data.size // FRAME_BYTES
    if n == 0:
        print(f"Error: {path} too small for even one frame.", file=sys.stderr)
        sys.exit(1)
    return data[: n * FRAME_BYTES].reshape(n, FRAME_H, FRAME_W)


def frame_to_text(frame: np.ndarray) -> str:
    """Convert a single 128x128 frame to a 128-line string of A-P chars."""
    # Vectorized: build a lookup table and index into it.
    lut = np.array(list(INDEX_TO_CHAR), dtype="U1")
    # Clamp to valid range just in case.
    clamped = np.clip(frame, 0, 15)
    char_grid = lut[clamped]
    lines = ["".join(row) for row in char_grid]
    return "\n".join(lines)


def resolve_frames_bin(target: Path) -> Path:
    """Resolve a target path to its frames.bin file."""
    if target.is_file():
        return target
    if target.is_dir():
        direct = target / "frames.bin"
        if direct.exists():
            return direct
        # Maybe a bot_N directory — pick latest session.
        sessions = sorted([s for s in target.iterdir() if s.is_dir()])
        if sessions:
            candidate = sessions[-1] / "frames.bin"
            if candidate.exists():
                return candidate
    print(f"Error: cannot find frames.bin in {target}", file=sys.stderr)
    sys.exit(1)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Convert guided_bot trace frames to A-P text grids.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "target",
        help="Trace session directory, bot_N directory, or frames.bin path.",
    )
    parser.add_argument(
        "--frame", "-f",
        type=int,
        default=0,
        help="Frame index to start from (default: 0).",
    )
    parser.add_argument(
        "--count", "-n",
        type=int,
        default=1,
        help="Number of consecutive frames to dump (default: 1).",
    )
    parser.add_argument(
        "--output", "-o",
        type=str,
        default=None,
        help="Output file (default: stdout).",
    )
    parser.add_argument(
        "--legend",
        action="store_true",
        help="Print palette legend before frame data.",
    )
    args = parser.parse_args()

    frames_path = resolve_frames_bin(Path(args.target))
    frames = load_frames(frames_path)
    n_frames = len(frames)

    start = args.frame
    count = args.count
    if start < 0 or start >= n_frames:
        print(
            f"Error: frame {start} out of range [0, {n_frames - 1}].",
            file=sys.stderr,
        )
        sys.exit(1)
    end = min(start + count, n_frames)

    # Build output.
    out_lines: list[str] = []
    if args.legend:
        out_lines.append(LEGEND)

    for i in range(start, end):
        if count > 1:
            out_lines.append(f"--- frame {i} ---")
        out_lines.append(frame_to_text(frames[i]))
        if i < end - 1:
            out_lines.append("")  # Blank line between frames.

    output = "\n".join(out_lines) + "\n"

    if args.output:
        Path(args.output).write_text(output)
        print(f"Wrote {end - start} frame(s) to {args.output}", file=sys.stderr)
    else:
        sys.stdout.write(output)


if __name__ == "__main__":
    main()
