#!/usr/bin/env python3
"""Universal agent runner for Persephone's Escape.

Launches any combination of registered agents against a game server.
An agent is registered by having a ``policy.py`` file under
``agents/<id>/``.

Usage:
    python run_agents.py baseline
    python run_agents.py baseline:3
    python run_agents.py baseline:3 my_agent:2
    python run_agents.py --port 9090 baseline:6
    python run_agents.py --list

See DESIGN_run_agents.md for the full design rationale.
"""

from __future__ import annotations

import argparse
import importlib
import importlib.util
import os
import signal
import subprocess
import sys
import threading
from pathlib import Path

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_PROJECT_ROOT = Path(__file__).resolve().parent
_AGENTS_DIR = _PROJECT_ROOT / "agents"

_DEFAULT_HOST = "localhost"
_DEFAULT_PORT = 2500
_LOG_LEVEL_AGENTS = frozenset({"eurydice", "orpheus_test"})
_FRAME_RECORDING_AGENTS = frozenset({"eurydice"})


# ---------------------------------------------------------------------------
# Agent discovery
# ---------------------------------------------------------------------------


def discover_agents() -> dict[str, Path]:
    """Scan agents/ for directories containing policy.py.

    Returns a mapping of agent_id -> path to policy.py.
    """
    agents: dict[str, Path] = {}
    if not _AGENTS_DIR.is_dir():
        return agents
    for entry in sorted(_AGENTS_DIR.iterdir()):
        if not entry.is_dir():
            continue
        policy = entry / "policy.py"
        if policy.is_file():
            agents[entry.name] = policy
    return agents


def load_agent_metadata(agent_id: str, policy_path: Path) -> dict[str, str]:
    """Import a policy module and read optional metadata constants.

    Returns a dict with 'id' and 'description' keys.  Falls back to
    the directory name and a placeholder if the module can't be imported
    or doesn't define the constants.
    """
    meta: dict[str, str] = {"id": agent_id, "description": "(no description)"}
    try:
        spec = importlib.util.spec_from_file_location(
            f"agents.{agent_id}.policy", policy_path,
        )
        if spec and spec.loader:
            mod = importlib.util.module_from_spec(spec)
            # Don't execute __main__ blocks -- just load module-level constants.
            spec.loader.exec_module(mod)
            if hasattr(mod, "AGENT_ID"):
                meta["id"] = mod.AGENT_ID
            if hasattr(mod, "DESCRIPTION"):
                meta["description"] = mod.DESCRIPTION
    except Exception:
        # Import failed (missing deps, syntax error, etc).  Use defaults.
        pass
    return meta


# ---------------------------------------------------------------------------
# Agent spec parsing
# ---------------------------------------------------------------------------


def parse_agent_specs(
    specs: list[str], available: dict[str, Path],
) -> list[tuple[str, Path]]:
    """Parse CLI agent specs into a flat list of (agent_id, policy_path).

    Each spec is either ``name`` (one instance) or ``name:N`` (N instances).
    Validates that each agent_id exists in *available*.
    """
    result: list[tuple[str, Path]] = []
    for spec in specs:
        if ":" in spec:
            parts = spec.split(":", 1)
            agent_id = parts[0]
            try:
                count = int(parts[1])
            except ValueError:
                print(f"Error: invalid count in spec '{spec}'", file=sys.stderr)
                sys.exit(1)
            if count < 1:
                print(f"Error: count must be >= 1 in spec '{spec}'", file=sys.stderr)
                sys.exit(1)
        else:
            agent_id = spec
            count = 1

        if agent_id not in available:
            avail_str = ", ".join(sorted(available)) or "(none)"
            print(
                f"Error: unknown agent '{agent_id}'. "
                f"Available agents: {avail_str}",
                file=sys.stderr,
            )
            sys.exit(1)

        for _ in range(count):
            result.append((agent_id, available[agent_id]))

    return result


# ---------------------------------------------------------------------------
# Process management
# ---------------------------------------------------------------------------


def prefix_stream(
    stream, prefix: str, log_file=None,
) -> None:
    """Read lines from *stream*, print with prefix, optionally write to log."""
    try:
        for line in stream:
            text = line if isinstance(line, str) else line.decode("utf-8", errors="replace")
            formatted = f"[{prefix}] {text}"
            sys.stdout.write(formatted)
            sys.stdout.flush()
            if log_file:
                log_file.write(formatted)
                log_file.flush()
    except (ValueError, OSError):
        # Stream closed.
        pass


def launch_agents(
    instances: list[tuple[str, Path]],
    url: str,
    log_dir: Path | None,
    quiet: bool,
    log_level: str | None,
    record_frames: Path | None,
) -> int:
    """Launch all agent instances and wait for them to finish.

    Returns 0 on clean exit, 1 if any agent crashed.
    """
    procs: list[subprocess.Popen] = []
    threads: list[threading.Thread] = []
    log_files: list = []
    names: list[str] = []

    # Assign globally unique names.
    for i, (agent_id, _) in enumerate(instances, start=1):
        names.append(f"{agent_id}_{i}")

    def shutdown(signum: int = 0, _frame: object = None) -> None:
        for p in procs:
            if p.poll() is None:
                try:
                    p.send_signal(signal.SIGINT)
                except OSError:
                    pass
        # Give children a moment to exit, then force-kill.
        for p in procs:
            try:
                p.wait(timeout=3)
            except subprocess.TimeoutExpired:
                p.kill()

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    try:
        for i, (agent_id, policy_path) in enumerate(instances):
            name = names[i]
            cmd = [
                sys.executable, str(policy_path),
                "--url", url,
                "--name", name,
            ]
            if log_level is not None and agent_id in _LOG_LEVEL_AGENTS:
                cmd.extend(["--log-level", log_level])
            if record_frames is not None and agent_id in _FRAME_RECORDING_AGENTS:
                cmd.extend(["--record-frames", str(record_frames)])

            use_pipe = not quiet or log_dir

            proc = subprocess.Popen(
                cmd,
                cwd=str(_PROJECT_ROOT),
                stdout=subprocess.PIPE if use_pipe else None,
                stderr=subprocess.STDOUT if use_pipe else None,
                text=True,
                bufsize=1,
            )
            procs.append(proc)

            lf = None
            if log_dir:
                lf = open(log_dir / f"{name}.log", "a")
                log_files.append(lf)

            if use_pipe and proc.stdout:
                if quiet and not log_dir:
                    # Discard output.
                    t = threading.Thread(
                        target=lambda s: [None for _ in s],
                        args=(proc.stdout,),
                        daemon=True,
                    )
                elif quiet and log_dir:
                    # Write to log only, no console.
                    t = threading.Thread(
                        target=_log_only,
                        args=(proc.stdout, lf),
                        daemon=True,
                    )
                else:
                    t = threading.Thread(
                        target=prefix_stream,
                        args=(proc.stdout, name, lf),
                        daemon=True,
                    )
                t.start()
                threads.append(t)

            print(f"Launched {name} (pid {proc.pid})")

        print(f"\n{len(procs)} agent(s) running against {url}\n")

        # Wait for all children.
        any_failed = False
        for i, p in enumerate(procs):
            rc = p.wait()
            if rc != 0:
                any_failed = True
                print(f"[{names[i]}] exited with code {rc}")

        # Let reader threads drain.
        for t in threads:
            t.join(timeout=2)

        return 1 if any_failed else 0

    except KeyboardInterrupt:
        shutdown()
        return 0

    finally:
        for lf in log_files:
            try:
                lf.close()
            except Exception:
                pass
        for p in procs:
            if p.poll() is None:
                p.terminate()


def _log_only(stream, log_file) -> None:
    """Write lines from *stream* to *log_file* only (no console)."""
    try:
        for line in stream:
            if log_file:
                log_file.write(line)
                log_file.flush()
    except (ValueError, OSError):
        pass


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Launch Persephone agents against a game server.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Agent specs:\n"
            "  name      One instance of agent 'name'\n"
            "  name:N    N instances of agent 'name'\n"
            "\n"
            "Examples:\n"
            "  python run_agents.py baseline\n"
            "  python run_agents.py baseline:3 my_agent:2\n"
            "  python run_agents.py --port 9090 baseline:6\n"
            "  python run_agents.py --list\n"
        ),
    )

    p.add_argument(
        "agents", nargs="*", metavar="AGENT_SPEC",
        help="Agent specs: name or name:N (see below)",
    )

    p.add_argument(
        "--host", default=_DEFAULT_HOST,
        help=f"Server hostname (default: {_DEFAULT_HOST})",
    )
    p.add_argument(
        "--port", type=int, default=_DEFAULT_PORT,
        help=f"Server port (default: {_DEFAULT_PORT})",
    )
    p.add_argument(
        "--url", default=None,
        help="Full WebSocket URL (overrides --host/--port)",
    )

    p.add_argument(
        "--log-dir", metavar="DIR",
        help="Write per-agent output to DIR/{name}.log",
    )
    p.add_argument(
        "--log-level",
        choices=("off", "events", "decisions", "verbose"),
        default=None,
        help=(
            "Forward an Orpheus/Eurydice JSONL log level to agents that "
            "support it (eurydice, orpheus_test)."
        ),
    )
    p.add_argument(
        "--record-frames",
        metavar="DIR",
        help="Forward frame recording directory to agents that support it (eurydice).",
    )
    p.add_argument(
        "--quiet", action="store_true",
        help="Suppress agent output on console (still logged if --log-dir)",
    )
    p.add_argument(
        "--list", action="store_true", dest="list_agents",
        help="List registered agents and exit",
    )

    return p


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    available = discover_agents()

    # -- List mode ------------------------------------------------------------
    if args.list_agents:
        if not available:
            print("No agents found in agents/")
            return 0
        print("Registered agents:\n")
        for agent_id, policy_path in sorted(available.items()):
            meta = load_agent_metadata(agent_id, policy_path)
            print(f"  {agent_id:20s} {meta['description']}")
        print()
        return 0

    # -- Run mode -------------------------------------------------------------
    if not args.agents:
        parser.print_help()
        print("\nError: no agent specs provided.", file=sys.stderr)
        return 1

    instances = parse_agent_specs(args.agents, available)
    if not instances:
        print("Error: no agent instances to launch.", file=sys.stderr)
        return 1

    url = args.url or f"ws://{args.host}:{args.port}/player"

    log_dir: Path | None = None
    if args.log_dir:
        log_dir = Path(args.log_dir).resolve()
        log_dir.mkdir(parents=True, exist_ok=True)

    record_frames: Path | None = None
    if args.record_frames:
        record_frames = Path(args.record_frames).resolve()
        record_frames.mkdir(parents=True, exist_ok=True)

    return launch_agents(
        instances,
        url,
        log_dir,
        args.quiet,
        args.log_level,
        record_frames,
    )


if __name__ == "__main__":
    sys.exit(main())
