#!/usr/bin/env python3
"""Run a manual live smoke test for the Orpheus test agent.

Examples:
    python scripts/orpheus_live_test.py --duration 30 --launch-server --seed 42 --fillers 9
    python scripts/orpheus_live_test.py --duration 30 --host localhost --port 2500

The script optionally launches a local Persephone server, starts
``agents/orpheus_test/policy.py``, optionally adds upstream winner_bot.ts
fillers, lets the run proceed for the requested duration, then inspects the
agent JSONL logs. It is intentionally not a pytest test because it depends on
a local bitworld checkout and Node/tsx runtime.
"""

from __future__ import annotations

import argparse
import json
import signal
import subprocess
import sys
import time
from pathlib import Path

import websocket

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_BITWORLD_DIR = Path.home() / "coding" / "bitworld" / "persephones_escape"


def main() -> int:
    args = _parse_args()
    procs: list[subprocess.Popen] = []
    server_proc: subprocess.Popen | None = None

    try:
        if args.launch_server:
            server_proc = _launch_server(args)
            procs.append(server_proc)

        if not _wait_for_server(args.host, args.port, timeout=args.server_timeout):
            print(
                f"Error: server did not accept connections on "
                f"{args.host}:{args.port}",
                file=sys.stderr,
            )
            return 1

        filler_procs = _launch_fillers(
            args.fillers,
            args.host,
            args.port,
            args.server_dir,
        )
        procs.extend(filler_procs)

        agent_proc = _launch_agent(args)
        time.sleep(args.duration)
        _terminate(agent_proc)
        try:
            output, _ = agent_proc.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            agent_proc.kill()
            output, _ = agent_proc.communicate(timeout=5)

        return _verify_agent_output(output, agent_proc.returncode)
    finally:
        for proc in reversed(procs):
            _terminate(proc)
        for proc in reversed(procs):
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Live smoke test for agents/orpheus_test.",
    )
    parser.add_argument("--host", default="localhost", help="Server host")
    parser.add_argument("--port", type=int, default=2500, help="Server port")
    parser.add_argument(
        "--duration",
        type=float,
        default=30.0,
        help="Seconds to run the agent before shutdown",
    )
    parser.add_argument(
        "--launch-server",
        action="store_true",
        help="Launch scripts/launch_server.py before connecting",
    )
    parser.add_argument("--seed", type=int, default=42, help="Server RNG seed")
    parser.add_argument(
        "--fillers",
        type=int,
        default=0,
        help="Number of upstream winner_bot.ts filler bots to launch",
    )
    parser.add_argument(
        "--server-timeout",
        type=float,
        default=15.0,
        help="Seconds to wait for server startup",
    )
    parser.add_argument(
        "--server-dir",
        type=Path,
        default=_BITWORLD_DIR,
        help="Path to bitworld/persephones_escape",
    )
    parser.add_argument(
        "--log-level",
        default="events",
        choices=("off", "events", "decisions", "verbose"),
        help="Log level passed to the Orpheus test agent",
    )
    return parser.parse_args()


def _launch_server(args: argparse.Namespace) -> subprocess.Popen:
    cmd = [
        sys.executable,
        str(_PROJECT_ROOT / "scripts" / "launch_server.py"),
        f"--port={args.port}",
        f"--seed={args.seed}",
        "--quiet",
        f"--server-dir={args.server_dir}",
    ]
    return subprocess.Popen(
        cmd,
        cwd=str(_PROJECT_ROOT),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )


def _wait_for_server(host: str, port: int, timeout: float) -> bool:
    deadline = time.time() + timeout
    url = f"ws://{host}:{port}/player?name=__orpheus_probe__"
    while time.time() < deadline:
        try:
            ws = websocket.create_connection(url, timeout=1.0)
            ws.close()
            return True
        except (OSError, websocket.WebSocketException):
            time.sleep(0.3)
    return False


def _launch_fillers(
    count: int,
    host: str,
    port: int,
    server_dir: Path = _BITWORLD_DIR,
) -> list[subprocess.Popen]:
    if count <= 0:
        return []

    bot_script = server_dir / "bots" / "winner_bot.ts"
    if not bot_script.is_file():
        print(
            f"Warning: filler bot script not found at {bot_script}; "
            "running without fillers.",
            file=sys.stderr,
        )
        return []

    procs: list[subprocess.Popen] = []
    base_url = f"ws://{host}:{port}/player"
    for i in range(count):
        proc = subprocess.Popen(
            [
                "npx",
                "tsx",
                str(bot_script),
                "--url",
                base_url,
                "--name",
                f"orpheus_filler_{i}",
            ],
            cwd=str(server_dir),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        procs.append(proc)
        time.sleep(0.1)
    return procs


def _launch_agent(args: argparse.Namespace) -> subprocess.Popen:
    url = f"ws://{args.host}:{args.port}/player"
    return subprocess.Popen(
        [
            sys.executable,
            str(_PROJECT_ROOT / "agents" / "orpheus_test" / "policy.py"),
            "--url",
            url,
            "--name",
            "orpheus_test_live",
            "--log-level",
            args.log_level,
        ],
        cwd=str(_PROJECT_ROOT),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )


def _terminate(proc: subprocess.Popen) -> None:
    if proc.poll() is not None:
        return
    try:
        proc.send_signal(signal.SIGINT)
    except OSError:
        return


def _verify_agent_output(output: str, returncode: int | None) -> int:
    print(output, end="")
    if returncode not in (0, None):
        print(f"Error: agent exited with code {returncode}", file=sys.stderr)
        return 1
    if "Traceback" in output:
        print("Error: agent output contains a traceback", file=sys.stderr)
        return 1

    entries = []
    for line in output.splitlines():
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            continue

    if not entries:
        print("Error: agent emitted no JSONL log entries", file=sys.stderr)
        return 1

    failure_types = {
        "hook_failure",
        "meta_decide_failed",
        "meta_decide_bad_return",
        "outer_loop_restart",
    }
    failures = [entry for entry in entries if entry.get("type") in failure_types]
    if failures:
        print(f"Error: agent logged failures: {failures}", file=sys.stderr)
        return 1

    if not any(entry.get("type") == "view_transition" for entry in entries):
        print(
            "Error: agent logs did not contain a view_transition entry",
            file=sys.stderr,
        )
        return 1

    print("Orpheus live smoke test passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
