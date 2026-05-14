"""Extract a handful of representative frames from modulabot's fixture
set and dump each as a raw 16384-byte unpacked uint8 file. Committed
.bin files let guided_bot's Nim tests exercise real perception without
needing a numpy / .npy reader on the Nim side.

Format (each .bin):
    128 * 128 = 16384 bytes, row-major, each byte in [0, 15] (palette
    index — already unpacked from the 4-bit packed wire format).

Run from the repo root:

    PYTHONPATH=among_them .venv/bin/python \\
        among_them/guided_bot/test/fixtures/extract_fixtures.py

The input file comes from the modulabot Python port's perception
snapshot suite and is a one-time capture from a real game; it's
outside this agent's concern and we take a dependency on it by path.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[4]
SRC = REPO_ROOT / "among_them" / "modulabot" / "tests" / "fixtures_frames.npy"
DST = Path(__file__).resolve().parent


# Semantic name -> source-array index. Keep this list short; bigger is
# not better. Each fixture has a test-side justification.
SELECTIONS: dict[str, int] = {
    # Fully-black interstitial (voting screen at capture start).
    "interstitial_0.bin": 0,
    "interstitial_5.bin": 5,
    "interstitial_100.bin": 100,
    # First gameplay frame — the transition away from interstitial.
    "gameplay_131.bin": 131,
    # Mid-gameplay frames; used for sanity checks on ignore-mask and,
    # once phase 1.2 lands, for localization parity.
    "gameplay_150.bin": 150,
    "gameplay_200.bin": 200,
    # Last frame in the capture.
    "gameplay_274.bin": 274,
}


def main() -> None:
    arr = np.load(SRC)
    if arr.dtype != np.uint8:
        raise RuntimeError(f"Unexpected dtype: {arr.dtype}")
    if arr.shape[1:] != (128, 128):
        raise RuntimeError(f"Unexpected frame shape: {arr.shape[1:]}")

    DST.mkdir(parents=True, exist_ok=True)
    for name, idx in SELECTIONS.items():
        frame = arr[idx]
        out = DST / name
        out.write_bytes(frame.tobytes(order="C"))
        black_frac = float((frame == 0).sum()) / frame.size
        print(f"{name}: src_idx={idx} black_frac={black_frac:.3f} -> {out}")


if __name__ == "__main__":
    main()
