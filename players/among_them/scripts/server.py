"""Start a Nim Among Them server and block until killed.

Prints the ``host:port`` to stdout so callers (human or script) can
connect.  All server-config knobs are exposed as CLI flags with sane
defaults.

Usage::

    # Auto-pick a free port, 8 players, default config
    PYTHONPATH=among_them python among_them/scripts/server.py

    # Explicit port + custom lobby
    PYTHONPATH=among_them python among_them/scripts/server.py \\
        --port 3000 --num-players 6 --imposter-count 1 --duration 120

The process exits when the server terminates (match ends, tick cap
reached, or Ctrl-C).
"""

from __future__ import annotations

import argparse
import logging
import signal
import sys

from _lib import (
    add_server_args,
    derive_max_ticks,
    find_server_binary,
    setup_pythonpath,
    start_server,
)

setup_pythonpath()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("server")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Start an Among Them Nim server and block until killed."
    )
    add_server_args(parser)
    # Server needs --duration and --seed but not --frame-stack.
    parser.add_argument(
        "--duration", type=float, default=0,
        help="Match duration in seconds (0 = use --max-ticks only).",
    )
    parser.add_argument(
        "--seed", type=int, default=42, help="Server RNG seed.",
    )
    # server.py uses --port for the bind port (0 = auto).
    parser.add_argument(
        "--port", type=int, default=0, help="Port to bind (0 = auto-pick)."
    )
    args = parser.parse_args()

    binary = find_server_binary(args.server_binary)
    log.info("Using binary: %s", binary)

    max_ticks = derive_max_ticks(args)
    server, config = start_server(
        binary,
        port=args.port,
        num_players=args.num_players,
        max_ticks=max_ticks,
        seed=args.seed,
        imposter_count=args.imposter_count,
        force_role=args.force_role,
    )

    # Print the resolved address so pipe consumers can parse it.
    print(f"{config.host}:{config.port}", flush=True)

    # Block until the server exits or we get a signal.
    def _handle_signal(signum, _frame):
        log.info("Received signal %s, terminating server...", signum)
        server.terminate()

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    rc = server.wait()
    log.info("Server exited with code %d", rc)
    return rc


if __name__ == "__main__":
    sys.exit(main())
