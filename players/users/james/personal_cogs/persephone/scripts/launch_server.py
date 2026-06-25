#!/usr/bin/env python3
"""Launch a Persephone's Escape game server.

Wraps the upstream TypeScript server with ergonomic defaults, inline JSON
config support (with deep-merge), log routing, and signal forwarding.

Examples:
    # Default: port 2500, random seed, default config
    python scripts/launch_server.py

    # Named preset, fixed seed
    python scripts/launch_server.py --config simple --seed 42

    # Inline config tweak (deep-merged with defaults)
    python scripts/launch_server.py --config-json '{"obstacleCount": 0}'

    # Full custom config file, public binding, logs to a directory
    python scripts/launch_server.py --config-file my_config.json --public --log-dir ./run_logs

    # Quiet mode (suppress periodic heartbeat lines)
    python scripts/launch_server.py --quiet
"""

from __future__ import annotations

import argparse
import json
import os
import random
import signal
import subprocess
import sys
import tempfile
from pathlib import Path

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Path to the upstream Persephone server directory in the bitworld repo.
_BITWORLD_PERSEPHONE_DIR = Path.home() / "coding" / "bitworld" / "persephones_escape"

_SERVER_ENTRY = "server.ts"

_DEFAULT_PORT = 2500

# Mirror of DEFAULT_GAME_CONFIG from game/constants.ts.  Used for
# deep-merging partial --config-json input so that callers can override
# individual fields without specifying the entire config.
_DEFAULT_GAME_CONFIG: dict = {
    "roles": [
        {"role": "Hades", "team": "TeamA", "count": 1},
        {"role": "Persephone", "team": "TeamB", "count": 1},
        {"role": "Cerberus", "team": "TeamA", "count": 1},
        {"role": "Demeter", "team": "TeamB", "count": 1},
        {"role": "Shades", "team": "TeamA", "count": 3},
        {"role": "Nymphs", "team": "TeamB", "count": 3},
    ],
    "rounds": [
        {"durationSecs": 15, "hostages": 1},
        {"durationSecs": 15, "hostages": 1},
        {"durationSecs": 15, "hostages": 1},
    ],
}


# ---------------------------------------------------------------------------
# Config helpers
# ---------------------------------------------------------------------------


def deep_merge(base: dict, overrides: dict) -> dict:
    """Merge *overrides* into a copy of *base*.

    Top-level keys in *overrides* replace the corresponding key in *base*
    wholesale (no recursive dict merge).  This matches the GameConfig
    semantics: if you override ``roles``, you replace the entire array;
    if you override ``obstacleCount``, only that scalar changes.
    """
    merged = dict(base)
    merged.update(overrides)
    return merged


def write_temp_config(config: dict) -> str:
    """Write *config* to a temporary JSON file and return its path.

    The file is created with delete=False so it persists until the process
    exits.  We clean it up in the finally block of main().
    """
    fd, path = tempfile.mkstemp(suffix=".json", prefix="persephone_cfg_")
    with os.fdopen(fd, "w") as f:
        json.dump(config, f, indent=2)
    return path


def validate_json_string(raw: str, label: str) -> dict:
    """Parse a JSON string and return the resulting dict, or exit with an error."""
    try:
        obj = json.loads(raw)
    except json.JSONDecodeError as exc:
        print(f"Error: invalid JSON in {label}: {exc}", file=sys.stderr)
        sys.exit(1)
    if not isinstance(obj, dict):
        print(f"Error: {label} must be a JSON object, got {type(obj).__name__}", file=sys.stderr)
        sys.exit(1)
    return obj


# ---------------------------------------------------------------------------
# Output filtering
# ---------------------------------------------------------------------------

# Heartbeat lines look like: "tick=121 phase=Playing players=10"
def is_heartbeat(line: str) -> bool:
    """Return True if *line* is a periodic server heartbeat."""
    return line.startswith("tick=")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Launch a Persephone's Escape game server.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Config resolution (mutually exclusive -- pick one):\n"
            "  --config NAME       Named preset (default, simple, empty, tiny, short, empty3, medium)\n"
            "  --config-file PATH  Full JSON config file (roles + rounds required)\n"
            "  --config-json JSON  Inline JSON string, deep-merged with defaults\n"
            "\n"
            "If none is given, the server uses its built-in DEFAULT_GAME_CONFIG\n"
            "(10 players, 3 rounds of 15s each)."
        ),
    )

    p.add_argument(
        "--port", type=int, default=_DEFAULT_PORT,
        help=f"Server listen port (default: {_DEFAULT_PORT})",
    )
    p.add_argument(
        "--public", action="store_true",
        help="Bind to 0.0.0.0 (accessible from other machines)",
    )
    p.add_argument(
        "--seed", type=int, default=None,
        help="RNG seed (default: random, printed to stdout for reproducibility)",
    )

    cfg = p.add_mutually_exclusive_group()
    cfg.add_argument(
        "--config", metavar="NAME", dest="config_name",
        help="Named config preset (default, simple, empty, tiny, short, empty3, medium)",
    )
    cfg.add_argument(
        "--config-file", metavar="PATH",
        help="Path to a complete JSON config file",
    )
    cfg.add_argument(
        "--config-json", metavar="JSON",
        help="Inline JSON config string, deep-merged with defaults",
    )

    p.add_argument(
        "--log-dir", metavar="DIR",
        help=(
            "Directory for game logs and server output.  The server writes "
            "game-over logs to logs/ relative to its working directory; this "
            "flag sets that working directory.  Server stdout is also teed "
            "to DIR/server.log."
        ),
    )
    p.add_argument(
        "--replay", metavar="PATH",
        help="Write a binary replay file to PATH",
    )
    p.add_argument(
        "--quiet", action="store_true",
        help="Suppress periodic tick heartbeat lines (show only startup and game events)",
    )
    p.add_argument(
        "--server-dir", metavar="DIR", default=None,
        help=f"Override path to the persephones_escape directory (default: {_BITWORLD_PERSEPHONE_DIR})",
    )

    return p


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    # -- Resolve server directory ---------------------------------------------
    server_dir = Path(args.server_dir) if args.server_dir else _BITWORLD_PERSEPHONE_DIR
    server_entry = server_dir / _SERVER_ENTRY
    if not server_entry.is_file():
        print(
            f"Error: server entry point not found at {server_entry}\n"
            f"Is bitworld checked out at {server_dir.parent.parent}?",
            file=sys.stderr,
        )
        return 1

    # -- Resolve seed ---------------------------------------------------------
    seed = args.seed if args.seed is not None else random.randint(0, 0x7FFFFFFF)

    # -- Resolve config -------------------------------------------------------
    temp_config_path: str | None = None
    config_source = "default"

    if args.config_file:
        config_path = Path(args.config_file).resolve()
        if not config_path.is_file():
            print(f"Error: config file not found: {config_path}", file=sys.stderr)
            return 1
        # Validate it parses as JSON before handing to the server.
        validate_json_string(config_path.read_text(), f"--config-file {config_path}")
        config_source = str(config_path)

    elif args.config_json:
        overrides = validate_json_string(args.config_json, "--config-json")
        merged = deep_merge(_DEFAULT_GAME_CONFIG, overrides)
        temp_config_path = write_temp_config(merged)
        config_source = f"inline JSON (merged, written to {temp_config_path})"

    elif args.config_name:
        config_source = args.config_name

    # -- Resolve log directory ------------------------------------------------
    log_dir: Path | None = None
    log_file = None
    if args.log_dir:
        log_dir = Path(args.log_dir).resolve()
        log_dir.mkdir(parents=True, exist_ok=True)

    # -- Build server command -------------------------------------------------
    host = "0.0.0.0" if args.public else "localhost"

    # Always use the absolute path to server.ts so it resolves correctly
    # regardless of what cwd we set for the subprocess.
    server_entry_abs = str(server_entry.resolve())

    cmd = [
        "npx", "tsx", server_entry_abs,
        f"--address={host}",
        f"--port={args.port}",
        f"--seed={seed}",
    ]

    if args.config_file:
        cmd.append(f"--config-file={Path(args.config_file).resolve()}")
    elif temp_config_path:
        cmd.append(f"--config-file={temp_config_path}")
    elif args.config_name:
        cmd.append(f"--config={args.config_name}")

    if args.replay:
        replay_path = Path(args.replay).resolve()
        cmd.append(f"--replay={replay_path}")

    # -- Print startup summary ------------------------------------------------
    print(f"Launching Persephone's Escape server")
    print(f"  Port:   {args.port}")
    print(f"  Host:   {host}")
    print(f"  Seed:   {seed}")
    print(f"  Config: {config_source}")
    if log_dir:
        print(f"  Logs:   {log_dir}")
    if args.replay:
        print(f"  Replay: {Path(args.replay).resolve()}")
    print()

    # -- Launch server subprocess ---------------------------------------------
    # The server must run from its own directory so that npx can find
    # node_modules and relative TypeScript imports resolve correctly.
    # Game-over logs are written to logs/ relative to cwd (i.e.,
    # {server_dir}/logs/{timestamp}/).
    #
    # If --log-dir was given, we tee server stdout to {log_dir}/server.log
    # and create a symlink from {server_dir}/logs to the log dir so that
    # game-over logs land where the user expects.  The symlink is removed
    # on exit to avoid polluting the upstream repo.
    cwd = str(server_dir)
    logs_symlink: Path | None = None

    if log_dir:
        game_logs_target = server_dir / "logs"
        # If logs/ already exists as a real directory, don't overwrite it.
        # If it's already a symlink (from a prior run), remove and recreate.
        if game_logs_target.is_symlink():
            game_logs_target.unlink()
        if not game_logs_target.exists():
            game_logs_target.symlink_to(log_dir)
            logs_symlink = game_logs_target

    proc: subprocess.Popen | None = None
    try:
        proc = subprocess.Popen(
            cmd,
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,  # Line-buffered
        )

        # Forward SIGINT/SIGTERM to the child for graceful shutdown.
        def forward_signal(signum: int, _frame: object) -> None:
            if proc and proc.poll() is None:
                proc.send_signal(signum)

        signal.signal(signal.SIGINT, forward_signal)
        signal.signal(signal.SIGTERM, forward_signal)

        # Open log file if needed.
        if log_dir:
            log_file = open(log_dir / "server.log", "a")

        # Stream server output, filtering heartbeat lines in quiet mode.
        assert proc.stdout is not None
        for line in proc.stdout:
            line_stripped = line.rstrip("\n")

            if args.quiet and is_heartbeat(line_stripped):
                # Still write to log file, just don't print to console.
                if log_file:
                    log_file.write(line)
                    log_file.flush()
                continue

            print(line_stripped)
            sys.stdout.flush()

            if log_file:
                log_file.write(line)
                log_file.flush()

        proc.wait()
        return proc.returncode or 0

    except KeyboardInterrupt:
        # Signal already forwarded; just wait for the child.
        if proc and proc.poll() is None:
            proc.wait(timeout=5)
        return 0

    finally:
        if log_file:
            log_file.close()

        # Clean up logs/ symlink if we created one.
        if logs_symlink and logs_symlink.is_symlink():
            try:
                logs_symlink.unlink()
            except OSError:
                pass

        # Clean up temp config file.
        if temp_config_path:
            try:
                os.unlink(temp_config_path)
            except OSError:
                pass

        # Ensure child is dead.
        if proc and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                proc.kill()


if __name__ == "__main__":
    sys.exit(main())
