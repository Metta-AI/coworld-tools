"""Live integration test for guided_bot.

Runs full local games against the Nim server with filler bots, then
checks trace output for correctness. Designed to be run occasionally
(not on every change) to verify end-to-end behavior.

Usage::

    PYTHONPATH=among_them .venv/bin/python \
        among_them/guided_bot/test/live_test.py

    # Imposter-only (faster, single scenario)
    PYTHONPATH=among_them .venv/bin/python \
        among_them/guided_bot/test/live_test.py --scenario imposter

    # Keep trace output for inspection
    PYTHONPATH=among_them .venv/bin/python \
        among_them/guided_bot/test/live_test.py --keep-traces

    # Custom output directory
    PYTHONPATH=among_them .venv/bin/python \
        among_them/guided_bot/test/live_test.py --output-dir /tmp/gb_live

Prerequisites:
    - Server binary at ~/coding/bitworld/out/among_them (or
      AMONG_THEM_BINARY env var)
    - Filler binary at ~/coding/bitworld/out/nottoodumb (or
      NOTTOODUMB_BINARY env var)
    - libguidedbot.dylib built (run build_guided_bot.py first)

Configuration:
    - Kill cooldown is set LOW (48 ticks = 2 seconds) so kills
      actually happen during imposter games.
    - Games run to completion (no --duration cap) so game_over
      events appear in the trace.
    - Max ticks is capped at 2400 (~100 seconds at 24Hz) to prevent
      infinite games.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

# Ensure the scripts directory is importable.
_scripts_dir = Path(__file__).resolve().parent.parent.parent / "scripts"
sys.path.insert(0, str(_scripts_dir))

from _lib import (  # noqa: E402
    AgentResult,
    add_policy_args,
    agent_loop,
    build_env_info,
    derive_player_name,
    find_filler_binary,
    find_server_binary,
    install_stop_handler,
    report_results,
    resolve_policy,
    setup_pythonpath,
    spawn_fillers,
    start_server,
    terminate_processes,
)

setup_pythonpath()
from mettagrid.runner.bitworld_runner import _connect_websocket  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("live_test")

# ---------------------------------------------------------------------------
# Scenario definitions
# ---------------------------------------------------------------------------

# Kill cooldown low enough that kills happen in a ~60s match.
# Default server cooldown is 1200 ticks (~50s); we use 48 (~2s).
KILL_COOLDOWN_TICKS = 48

# Max match length. At 24Hz this is 100 seconds — long enough for
# a full game but prevents runaway matches.
MAX_TICKS = 2400

# Wall-clock deadline per scenario. Prevents infinite games when the
# server doesn't hit max_ticks (voting/interstitial time doesn't
# count toward the tick limit).
WALL_CLOCK_LIMIT_SECONDS = 90

SCENARIOS = {
    "imposter": {
        "seed": 100,
        "force_role": "imposter",
        "description": "Imposter role — should hunt and attempt kills",
        "assertions": [
            ("role_detected", "imposter"),
            ("mode_entered", "hunting"),
            ("manifest_closed", True),
        ],
    },
    "crewmate": {
        "seed": 7,
        "force_role": "imposter",  # seed 7 ignores the flag (race)
        "description": "Crewmate role — should complete tasks",
        "assertions": [
            ("role_detected", "crewmate"),
            ("mode_entered", "task_completing"),
            ("manifest_closed", True),
        ],
    },
}

# ---------------------------------------------------------------------------
# Game runner
# ---------------------------------------------------------------------------

POLICY_CLASS = "guided_bot.cogames.amongthem_policy.AmongThemPolicy"


def run_game(
    scenario_name: str,
    scenario: dict,
    trace_dir: Path,
) -> dict:
    """Run one full game. Returns trace data as a dict for assertions."""
    log.info(
        "--- Scenario: %s (seed=%d) ---",
        scenario_name,
        scenario["seed"],
    )
    log.info("  %s", scenario["description"])

    trace_dir.mkdir(parents=True, exist_ok=True)

    # Set trace env vars for the guided_bot library.
    os.environ["GUIDED_BOT_TRACE_DIR"] = str(trace_dir)
    os.environ["GUIDED_BOT_TRACE_LEVEL"] = "decisions"

    server_bin = find_server_binary(None)
    server, config = start_server(
        server_bin,
        num_players=8,
        max_ticks=MAX_TICKS,
        seed=scenario["seed"],
        imposter_count=2,
        imposter_cooldown_ticks=KILL_COOLDOWN_TICKS,
        force_role=scenario["force_role"],
    )

    filler_procs = []
    try:
        # Connect our policy agent first (slot 0).
        ws = _connect_websocket(config, "/player", "gb", player_name="gb")

        # Spawn fillers.
        try:
            filler_bin = find_filler_binary(None)
            filler_procs = spawn_fillers(filler_bin, config.host, config.port, 7)
        except FileNotFoundError:
            log.error("Filler binary not found — cannot run live test.")
            raise

        # Build policy.
        env_info = build_env_info(frame_stack=4, num_agents=1)
        policy = resolve_policy(POLICY_CLASS, env_info, policy_kwargs={"seed": "0"})

        # Run until game ends, max ticks, or wall-clock deadline.
        stop_event = threading.Event()
        install_stop_handler(stop_event)

        deadline = time.monotonic() + WALL_CLOCK_LIMIT_SECONDS
        result = AgentResult()
        agent_loop(
            agent_id=0,
            player_name="gb",
            ws=ws,
            policy=policy,
            frame_stack=4,
            deadline=deadline,
            stop_event=stop_event,
            capture_frames=False,
            collect_metrics=False,
            result=result,
        )

        report_results([result], 1)

        if hasattr(policy, "close"):
            policy.close(reason="session_end")

    finally:
        terminate_processes(filler_procs, label="filler")
        terminate_processes([server], label="server")

    # Clean up env vars.
    os.environ.pop("GUIDED_BOT_TRACE_DIR", None)
    os.environ.pop("GUIDED_BOT_TRACE_LEVEL", None)

    # Read trace output.
    return read_traces(trace_dir)


# ---------------------------------------------------------------------------
# Trace reader
# ---------------------------------------------------------------------------


def read_traces(trace_dir: Path) -> dict:
    """Read and parse trace files into a structured dict."""
    result = {
        "manifest": {},
        "events": [],
        "modes": [],
        "decisions_count": 0,
    }

    manifest_path = trace_dir / "manifest.json"
    if manifest_path.exists():
        result["manifest"] = json.loads(manifest_path.read_text())

    events_path = trace_dir / "events.jsonl"
    if events_path.exists():
        for line in events_path.read_text().strip().splitlines():
            if line:
                result["events"].append(json.loads(line))

    modes_path = trace_dir / "modes.jsonl"
    if modes_path.exists():
        for line in modes_path.read_text().strip().splitlines():
            if line:
                result["modes"].append(json.loads(line))

    decisions_path = trace_dir / "decisions.jsonl"
    if decisions_path.exists():
        result["decisions_count"] = sum(
            1 for line in decisions_path.read_text().strip().splitlines() if line
        )

    return result


# ---------------------------------------------------------------------------
# Assertions
# ---------------------------------------------------------------------------


def check_assertions(
    scenario_name: str,
    scenario: dict,
    traces: dict,
) -> list[str]:
    """Run assertions on trace output. Returns list of failure messages."""
    failures = []

    for assertion_type, expected in scenario["assertions"]:
        if assertion_type == "role_detected":
            role_events = [
                e for e in traces["events"] if e.get("kind") == "role_revealed"
            ]
            if not role_events:
                failures.append(f"  FAIL: No role_revealed event found")
            elif role_events[0].get("role") != expected:
                failures.append(
                    f"  FAIL: role_revealed={role_events[0].get('role')}, "
                    f"expected={expected}"
                )

        elif assertion_type == "mode_entered":
            entered_modes = [
                m.get("mode")
                for m in traces["modes"]
                if m.get("kind") == "mode_entered"
            ]
            if expected not in entered_modes:
                failures.append(
                    f"  FAIL: mode '{expected}' never entered. "
                    f"Modes seen: {entered_modes}"
                )

        elif assertion_type == "manifest_closed":
            if traces["manifest"].get("closed") != expected:
                failures.append(
                    f"  FAIL: manifest closed={traces['manifest'].get('closed')}, "
                    f"expected={expected}"
                )

    # Additional soft checks (reported but not failures).
    manifest = traces["manifest"]
    end_tick = manifest.get("end_tick", 0)
    role = manifest.get("role", "?")
    events = traces["events"]
    modes = traces["modes"]

    log.info("  Results for %s:", scenario_name)
    log.info("    Role: %s | End tick: %d | Decisions: %d",
             role, end_tick, traces["decisions_count"])
    log.info("    Events: %s",
             [f"{e['kind']}@t{e['t']}" for e in events[:10]])
    log.info("    Mode transitions: %s",
             [f"{m['mode']}@t{m['t']}" for m in modes if m.get("kind") == "mode_entered"])

    # Check for kill events (imposter scenario, informational).
    kill_events = [e for e in events if "kill" in e.get("kind", "")]
    if kill_events:
        log.info("    Kill events: %s",
                 [f"{e['kind']}@t{e['t']}" for e in kill_events])

    # Check for task events (crewmate scenario, informational).
    task_events = [e for e in events if "task" in e.get("kind", "")]
    if task_events:
        log.info("    Task events: %s",
                 [f"{e['kind']}@t{e['t']}" for e in task_events[:10]])

    # Check for game_over (informational).
    game_over = [e for e in events if e.get("kind") == "game_over"]
    if game_over:
        log.info("    Game ended at tick %d", game_over[0]["t"])
    else:
        log.info("    Game did not reach game_over (hit max_ticks=%d)", MAX_TICKS)

    return failures


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Live integration test for guided_bot.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--scenario",
        choices=list(SCENARIOS.keys()),
        default=None,
        help="Run only this scenario (default: all).",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Directory for trace output (default: temp dir).",
    )
    parser.add_argument(
        "--keep-traces",
        action="store_true",
        help="Keep trace output after test (always kept if --output-dir is set).",
    )
    args = parser.parse_args()

    # Determine output directory.
    if args.output_dir:
        output_dir = args.output_dir
        output_dir.mkdir(parents=True, exist_ok=True)
        keep = True
    elif args.keep_traces:
        output_dir = Path(tempfile.mkdtemp(prefix="gb_live_"))
        keep = True
    else:
        output_dir = Path(tempfile.mkdtemp(prefix="gb_live_"))
        keep = False

    log.info("Trace output: %s", output_dir)

    # Select scenarios.
    if args.scenario:
        scenarios_to_run = {args.scenario: SCENARIOS[args.scenario]}
    else:
        scenarios_to_run = SCENARIOS

    # Run scenarios.
    all_failures = []
    for name, scenario in scenarios_to_run.items():
        trace_dir = output_dir / name
        try:
            traces = run_game(name, scenario, trace_dir)
            failures = check_assertions(name, scenario, traces)
            all_failures.extend(failures)
            for f in failures:
                log.error(f)
        except Exception as e:
            log.error("  FAIL: Scenario %s crashed: %s", name, e)
            all_failures.append(f"  FAIL: {name} crashed: {e}")

    # Summary.
    print()
    if all_failures:
        print(f"FAILED: {len(all_failures)} assertion(s)")
        for f in all_failures:
            print(f)
        rc = 1
    else:
        total = sum(len(s["assertions"]) for s in scenarios_to_run.values())
        print(f"OK: all {total} assertions passed across {len(scenarios_to_run)} scenario(s)")
        rc = 0

    if keep:
        print(f"Traces saved to: {output_dir}")
    else:
        shutil.rmtree(output_dir, ignore_errors=True)

    return rc


if __name__ == "__main__":
    sys.exit(main())
