"""Capture raw gameplay frames for offline testing and debug overlay.

Starts a local server + filler bots, connects a passive observer that
sends noops, and records every received frame to a ``.npy`` file.

Usage::

    PYTHONPATH=among_them python among_them/scripts/capture.py \\
        --duration 10 --output frames.npy

    # Custom lobby size + explicit binaries
    PYTHONPATH=among_them python among_them/scripts/capture.py \\
        --duration 30 --num-players 6 \\
        --server-binary ~/bitworld/out/among_them \\
        --filler-binary ~/bitworld/out/nottoodumb \\
        --output /tmp/capture.npy

The output is a ``(N, 128, 128) uint8`` array.  Load with
``np.load("frames.npy")``.
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

import numpy as np

from _lib import (
    add_server_args,
    capture_loop,
    derive_max_ticks,
    find_filler_binary,
    find_server_binary,
    setup_pythonpath,
    spawn_fillers,
    start_server,
    terminate_processes,
)

setup_pythonpath()

from mettagrid.runner.bitworld_runner import (  # noqa: E402
    BitWorldRuntime,
    _connect_websocket,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("capture")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Capture raw gameplay frames to a .npy file."
    )
    add_server_args(parser)
    parser.add_argument(
        "--duration", type=float, default=10.0, help="Seconds to capture."
    )
    parser.add_argument(
        "--seed", type=int, default=42, help="Server RNG seed."
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("frames.npy"),
        help="Output .npy path.",
    )
    args = parser.parse_args()

    server_bin = find_server_binary(args.server_binary)
    filler_bin = find_filler_binary(args.filler_binary)

    max_ticks = derive_max_ticks(args)
    server, config = start_server(
        server_bin,
        num_players=args.num_players,
        max_ticks=max_ticks,
        seed=args.seed,
        imposter_count=args.imposter_count,
    )

    filler_procs = []
    ws = None
    try:
        # Connect the passive observer.
        ws = _connect_websocket(
            config, "/player", "cap", player_name="cap"
        )

        # Fill the lobby with bots.
        filler_procs = spawn_fillers(
            filler_bin, config.host, config.port, args.num_players - 1
        )

        # Capture frames.
        deadline = time.monotonic() + args.duration
        frames = capture_loop(ws, deadline)

        if not frames:
            log.error(
                "No frames captured — server probably never started the match."
            )
            return 1

        arr = np.stack(frames, axis=0).astype(np.uint8)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        np.save(args.output, arr)
        log.info(
            "Wrote %d frames to %s (%.1f MB)",
            arr.shape[0],
            args.output,
            arr.nbytes / 1e6,
        )
        return 0

    finally:
        if ws is not None:
            try:
                ws.close()
            except Exception:
                pass
        terminate_processes(filler_procs, label="filler")
        terminate_processes([server], label="server")


if __name__ == "__main__":
    sys.exit(main())
