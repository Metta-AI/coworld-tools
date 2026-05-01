"""Capture a short stream of real gameplay frames for offline testing.

Runs the same local-episode harness as ``play_local.py``, but instead of
stepping a policy it just records the unpacked 128×128 frames to a .npy
file. Use the resulting file for perception snapshot tests and for the
visual debug overlay:

.. code-block:: bash

    cd /Users/jamesboggs/coding/personal_cogs/among_them
    PYTHONPATH=. python scripts/capture_frames.py --duration 10 --output frames.npy

The output is a (N, 128, 128) uint8 array. Load with::

    frames = np.load("frames.npy")
"""

from __future__ import annotations

import argparse
import logging
import os
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
from mettagrid.bitworld import PACKED_FRAME_BYTES
from mettagrid.runner.bitworld_runner import (
    BitWorldConfig,
    _connect_websocket,
    _start_server_on_free_port,
    _unpack_frame,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
log = logging.getLogger("capture")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--duration", type=float, default=10.0)
    parser.add_argument("--num-players", type=int, default=5)
    parser.add_argument("--output", type=Path, default=Path("frames.npy"))
    parser.add_argument(
        "--binary",
        type=Path,
        default=Path.home() / "coding" / "bitworld" / "out" / "among_them",
    )
    parser.add_argument(
        "--filler-bot",
        type=Path,
        default=Path.home() / "coding" / "bitworld" / "out" / "nottoodumb",
    )
    args = parser.parse_args()

    if not args.binary.exists():
        raise SystemExit(f"server binary not found: {args.binary}")

    config = BitWorldConfig(
        binary_path=str(args.binary), host="127.0.0.1", port=0,
        num_players=args.num_players, max_ticks=60 * 24,
    )
    server = _start_server_on_free_port(args.binary, config)
    log.info("Server on port %d", config.port)

    bot_procs = []
    try:
        ws = _connect_websocket(config, "/player", "capturer", player_name="capturer")

        if args.filler_bot.exists():
            for i in range(args.num_players - 1):
                p = subprocess.Popen(
                    [str(args.filler_bot), f"--address:{config.host}", f"--port:{config.port}", f"--name:bot{i+1}"],
                    cwd=str(args.filler_bot.parent),
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                )
                bot_procs.append(p)
                time.sleep(0.1)

        frames: list[np.ndarray] = []
        deadline = time.monotonic() + args.duration
        while time.monotonic() < deadline:
            try:
                payload = ws.recv()
            except Exception as e:
                log.info("ws closed: %s", e)
                break
            if isinstance(payload, (bytes, bytearray)) and len(payload) == PACKED_FRAME_BYTES:
                frames.append(_unpack_frame(payload))
                # Send back a noop to keep the match running.
                from mettagrid.bitworld import pack_input_packet
                import websocket
                ws.send(pack_input_packet(0), opcode=websocket.ABNF.OPCODE_BINARY)

        if not frames:
            raise SystemExit("no frames captured — server probably never started the match")

        arr = np.stack(frames, axis=0).astype(np.uint8)
        np.save(args.output, arr)
        log.info("wrote %d frames to %s (%.1f MB)", arr.shape[0], args.output, arr.nbytes / 1e6)

    finally:
        try:
            ws.close()
        except Exception:
            pass
        for p in bot_procs:
            try: p.terminate()
            except Exception: pass
        try: server.terminate()
        except Exception: pass


if __name__ == "__main__":
    main()
