#!/usr/bin/env python3
"""Baseline agent policy -- wraps the upstream winner_bot.ts.

Connects to a Persephone server and plays using a hardcoded policy:
approach nearest player, open chatroom, offer role exchange, accept all
offers.  No strategy, no deception, no team awareness.

Contract:
    python agents/baseline/policy.py --url URL --name NAME

Can also be launched via the universal runner:
    python run_agents.py baseline
"""

from __future__ import annotations

import argparse
import signal
import subprocess
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Agent metadata (read by run_agents.py --list)
# ---------------------------------------------------------------------------

AGENT_ID = "baseline"
DESCRIPTION = "Upstream winner_bot.ts -- approach, chatroom, role exchange everyone"

# ---------------------------------------------------------------------------
# Implementation
# ---------------------------------------------------------------------------

_BITWORLD_PERSEPHONE_DIR = Path.home() / "coding" / "bitworld" / "persephones_escape"
_BOT_SCRIPT = _BITWORLD_PERSEPHONE_DIR / "bots" / "winner_bot.ts"


def run(*, url: str, name: str) -> int:
    """Connect to the server and play until disconnected or interrupted.

    Launches the upstream winner_bot.ts as a subprocess and waits for it
    to exit.

    Args:
        url: WebSocket URL (e.g., ws://localhost:2500/player).
        name: Player name to use when connecting.

    Returns:
        Child process exit code.
    """
    if not _BOT_SCRIPT.is_file():
        print(
            f"Error: winner_bot.ts not found at {_BOT_SCRIPT}\n"
            f"Is bitworld checked out at {_BITWORLD_PERSEPHONE_DIR.parent}?",
            file=sys.stderr,
        )
        return 1

    proc = subprocess.Popen(
        ["npx", "tsx", str(_BOT_SCRIPT.resolve()), "--name", name, "--url", url],
        cwd=str(_BITWORLD_PERSEPHONE_DIR),
    )

    # Forward signals to the child for graceful shutdown.
    def forward(signum: int, _frame: object) -> None:
        if proc.poll() is None:
            proc.send_signal(signum)

    signal.signal(signal.SIGINT, forward)
    signal.signal(signal.SIGTERM, forward)

    try:
        return proc.wait()
    except KeyboardInterrupt:
        if proc.poll() is None:
            proc.send_signal(signal.SIGINT)
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                proc.kill()
        return 0


def main() -> int:
    p = argparse.ArgumentParser(
        description="Run the baseline agent against a Persephone server.",
    )
    p.add_argument("--url", required=True, help="Server WebSocket URL")
    p.add_argument("--name", required=True, help="Player name")
    args = p.parse_args()
    return run(url=args.url, name=args.name)


if __name__ == "__main__":
    sys.exit(main())
