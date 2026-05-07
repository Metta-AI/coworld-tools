#!/usr/bin/env python3
"""Capture frames from a live Persephone's Escape game.

Connects to the game server via WebSocket, records all received frames,
and produces:
  - {output}.npy: all frames as (N, 128, 128) uint8 array
  - {output}.jsonl: per-frame metadata (tick, detected view, etc.)

The client optionally accepts a policy expression to drive actions.
Without a policy, it sends noops (passive observer).

Examples:
    # Passive capture against a running server (must be running already)
    python scripts/capture.py --duration 30 --output /tmp/capture

    # With a simple scripted policy (press B at tick 200)
    python scripts/capture.py --duration 30 --output /tmp/capture \\
        --policy "0x40 if tick == 200 else 0x00"

    # Auto-launch server with seed and filler bots
    python scripts/capture.py --duration 30 --output /tmp/capture \\
        --launch-server --seed 42 --fillers 4

    # Force all bots into the same room (helps trigger chatroom views)
    python scripts/capture.py --duration 30 --output /tmp/capture \\
        --launch-server --seed 42 --fillers 4 \\
        --server-config '{"autoGrantWhisperEntry": true}'
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import struct
import subprocess
import sys
import time
from pathlib import Path
from typing import Callable

import numpy as np
import websocket

# Ensure the perception module is importable regardless of how the script
# is invoked (from repo root or scripts/).
_SCRIPT_DIR = Path(__file__).resolve().parent
_PERSEPHONE_ROOT = _SCRIPT_DIR.parent
if str(_PERSEPHONE_ROOT) not in sys.path:
    sys.path.insert(0, str(_PERSEPHONE_ROOT))

from perception import parse_frame  # noqa: E402
from perception._unpack import unpack_frame  # noqa: E402

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_PROTOCOL_BYTES = 8192
_DEFAULT_HOST = "localhost"
_DEFAULT_PORT = 2500
_DEFAULT_DURATION = 30.0
_DEFAULT_NAME = "capture_bot"

_BITWORLD_DIR = Path.home() / "coding" / "bitworld" / "persephones_escape"

# ---------------------------------------------------------------------------
# Policy helpers
# ---------------------------------------------------------------------------


PolicyFn = Callable[[np.ndarray, int], int]


def make_noop_policy() -> PolicyFn:
    """Policy that always sends noop (mask=0)."""
    def policy(frame: np.ndarray, tick: int) -> int:
        return 0
    return policy


def make_expr_policy(expr: str) -> PolicyFn:
    """Build a policy from a Python expression.

    The expression can reference ``tick`` (int) and ``frame`` (128x128 array).
    It must evaluate to an int (button mask).

    Example: "0x40 if tick == 200 else 0x00"
    """
    # Compile once for performance
    code = compile(expr, "<policy-expr>", "eval")

    def policy(frame: np.ndarray, tick: int) -> int:
        result = eval(code, {"__builtins__": {}}, {"tick": tick, "frame": frame})
        return int(result)

    return policy


# ---------------------------------------------------------------------------
# Server/filler management
# ---------------------------------------------------------------------------


def launch_server(
    *,
    port: int,
    seed: int,
    config_json: str | None = None,
    quiet: bool = True,
    server_dir: Path = _BITWORLD_DIR,
) -> subprocess.Popen:
    """Launch the Persephone server as a subprocess.

    Returns the Popen handle. Caller is responsible for cleanup.
    """
    cmd = [
        sys.executable,
        str(_PERSEPHONE_ROOT / "scripts" / "launch_server.py"),
        f"--port={port}",
        f"--seed={seed}",
    ]
    if quiet:
        cmd.append("--quiet")
    if config_json:
        cmd.append(f"--config-json={config_json}")
    if server_dir != _BITWORLD_DIR:
        cmd.append(f"--server-dir={server_dir}")

    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    return proc


def wait_for_server(host: str, port: int, timeout: float = 15.0) -> bool:
    """Block until the server accepts WebSocket connections or timeout."""
    deadline = time.time() + timeout
    url = f"ws://{host}:{port}/player?name=__probe__"
    while time.time() < deadline:
        try:
            ws = websocket.WebSocket()
            ws.settimeout(1.0)
            ws.connect(url)
            ws.close()
            return True
        except (ConnectionRefusedError, OSError, websocket.WebSocketException):
            time.sleep(0.3)
    return False


def launch_fillers(
    count: int,
    host: str,
    port: int,
    server_dir: Path = _BITWORLD_DIR,
) -> list[subprocess.Popen]:
    """Launch TypeScript smart filler bots.

    Uses the upstream winner_bot.ts (which takes actions: walks, chats,
    exchanges) rather than a passive bot.
    """
    procs = []
    bot_script = server_dir / "bots" / "winner_bot.ts"
    if not bot_script.is_file():
        # Fall back to smart_bots if winner_bot doesn't exist
        bot_script = server_dir / "bots" / "smart_bots.ts"
    if not bot_script.is_file():
        print(
            f"Warning: no filler bot script found at {server_dir}/bots/. "
            "Skipping fillers.",
            file=sys.stderr,
        )
        return procs

    base_url = f"ws://{host}:{port}/player"
    for i in range(count):
        name = f"filler_{i}"
        cmd = ["npx", "tsx", str(bot_script), "--url", base_url, "--name", name]
        proc = subprocess.Popen(
            cmd,
            cwd=str(server_dir),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        procs.append(proc)
        # Stagger connections slightly to avoid overwhelming the server
        time.sleep(0.1)

    return procs


# ---------------------------------------------------------------------------
# Core capture loop
# ---------------------------------------------------------------------------


def capture_loop(
    ws: websocket.WebSocket,
    policy: PolicyFn,
    duration: float,
    jsonl_path: Path,
    stop_flag: Callable[[], bool] | None = None,
) -> list[np.ndarray]:
    """Run the capture loop, returning collected frames.

    Writes per-frame metadata to *jsonl_path* as each frame arrives.
    If *stop_flag* is provided, it is checked each iteration; returning
    True causes the loop to exit cleanly.
    """
    frames: list[np.ndarray] = []
    start_time = time.time()
    tick = 0

    with open(jsonl_path, "w") as meta_f:
        while True:
            # Check shutdown flag (set by signal handler)
            if stop_flag and stop_flag():
                break

            # Check duration
            elapsed = time.time() - start_time
            if duration > 0 and elapsed >= duration:
                break

            # Receive frame (socket timeout lets us re-check stop conditions)
            try:
                data = ws.recv()
            except websocket.WebSocketTimeoutException:
                continue
            except (
                websocket.WebSocketConnectionClosedException,
                ConnectionError,
            ):
                print("Server closed connection.", file=sys.stderr)
                break

            if not isinstance(data, bytes) or len(data) != _PROTOCOL_BYTES:
                # Skip non-frame messages (e.g. text messages)
                continue

            # Unpack frame
            frame = unpack_frame(data)
            frames.append(frame)

            # Run perception for metadata
            try:
                perc = parse_frame(frame)
                view_name = perc.view.value
            except Exception:
                view_name = "error"

            # Write metadata line
            meta_line = json.dumps(
                {"tick": tick, "view": view_name, "wall_s": round(elapsed, 3)},
                separators=(",", ":"),
            )
            meta_f.write(meta_line + "\n")

            # Compute and send action
            try:
                mask = policy(frame, tick)
            except Exception:
                mask = 0

            # Send button packet: [0x00, mask]
            ws.send(struct.pack("BB", 0x00, mask & 0xFF), opcode=0x2)

            tick += 1

            # Progress indicator every 5 seconds
            if tick % 120 == 0:  # ~5s at 24fps
                print(
                    f"  tick {tick:>5d} | {elapsed:.1f}s | view={view_name}",
                    file=sys.stderr,
                )

    return frames


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Capture frames from a live Persephone's Escape game.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    # Connection
    p.add_argument(
        "--host", default=_DEFAULT_HOST,
        help=f"Server hostname (default: {_DEFAULT_HOST})",
    )
    p.add_argument(
        "--port", type=int, default=_DEFAULT_PORT,
        help=f"Server port (default: {_DEFAULT_PORT})",
    )
    p.add_argument(
        "--name", default=_DEFAULT_NAME,
        help=f"Player name for the capture client (default: {_DEFAULT_NAME})",
    )

    # Session
    p.add_argument(
        "--duration", type=float, default=_DEFAULT_DURATION,
        help=f"Capture duration in seconds; 0 = until server closes (default: {_DEFAULT_DURATION})",
    )
    p.add_argument(
        "--output", "-o", default="capture",
        help="Output path prefix (produces {output}.npy and {output}.jsonl)",
    )

    # Policy
    p.add_argument(
        "--policy", default=None, metavar="EXPR",
        help=(
            "Python expression for button mask. "
            "Available vars: tick (int), frame (128x128 uint8 array). "
            "Example: '0x40 if tick == 200 else 0x00'"
        ),
    )

    # Server management
    p.add_argument(
        "--launch-server", action="store_true",
        help="Auto-launch the game server before connecting",
    )
    p.add_argument(
        "--seed", type=int, default=42,
        help="Server RNG seed (default: 42)",
    )
    p.add_argument(
        "--fillers", type=int, default=0, metavar="N",
        help="Number of TypeScript filler bots to launch (default: 0)",
    )
    p.add_argument(
        "--server-config", default=None, metavar="JSON",
        help="Inline JSON config for the server (deep-merged with defaults)",
    )
    p.add_argument(
        "--server-dir", default=None, metavar="DIR",
        help=f"Override path to persephones_escape (default: {_BITWORLD_DIR})",
    )

    return p


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    # Resolve output paths
    output_base = Path(args.output)
    output_base.parent.mkdir(parents=True, exist_ok=True)
    npy_path = output_base.with_suffix(".npy")
    jsonl_path = output_base.with_suffix(".jsonl")

    # Build policy
    if args.policy:
        policy = make_expr_policy(args.policy)
    else:
        policy = make_noop_policy()

    # Resolve server directory
    server_dir = Path(args.server_dir) if args.server_dir else _BITWORLD_DIR

    # Managed subprocesses
    server_proc: subprocess.Popen | None = None
    filler_procs: list[subprocess.Popen] = []

    def cleanup() -> None:
        """Terminate all managed subprocesses."""
        for p in filler_procs:
            if p.poll() is None:
                p.terminate()
        if server_proc and server_proc.poll() is None:
            server_proc.terminate()
            try:
                server_proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                server_proc.kill()

    # Handle signals for clean shutdown
    shutdown_requested = False

    def handle_signal(signum: int, _frame: object) -> None:
        nonlocal shutdown_requested
        shutdown_requested = True

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    try:
        # Launch server if requested
        if args.launch_server:
            print(f"Launching server (seed={args.seed}, port={args.port})...")
            server_proc = launch_server(
                port=args.port,
                seed=args.seed,
                config_json=args.server_config,
                server_dir=server_dir,
            )

            # Wait for server to be ready
            print("Waiting for server to accept connections...")
            if not wait_for_server(args.host, args.port):
                print("Error: server did not start within timeout.", file=sys.stderr)
                return 1
            print("Server ready.")

            # Launch fillers
            if args.fillers > 0:
                print(f"Launching {args.fillers} filler bot(s)...")
                filler_procs = launch_fillers(
                    args.fillers, args.host, args.port, server_dir,
                )
                # Give fillers time to connect and populate lobby
                time.sleep(1.0)
                print(f"Fillers connected.")

        # Connect to server
        url = f"ws://{args.host}:{args.port}/player?name={args.name}"
        print(f"Connecting to {url}")

        ws = websocket.WebSocket()
        ws.settimeout(2.0)
        try:
            ws.connect(url)
        except (ConnectionRefusedError, OSError, websocket.WebSocketException) as exc:
            print(f"Error: cannot connect to server: {exc}", file=sys.stderr)
            return 1

        print(f"Connected. Capturing for {args.duration}s -> {output_base}.*")
        print()

        # Run capture loop
        frames = capture_loop(
            ws, policy, args.duration, jsonl_path,
            stop_flag=lambda: shutdown_requested,
        )

        ws.close()

    except KeyboardInterrupt:
        pass

    finally:
        cleanup()

    # Save frames
    if frames:
        frame_array = np.stack(frames)
        np.save(npy_path, frame_array)
        print()
        print(f"Captured {len(frames)} frames ({frame_array.shape})")
        print(f"  Frames: {npy_path}")
        print(f"  Metadata: {jsonl_path}")
    else:
        print("\nNo frames captured.", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
