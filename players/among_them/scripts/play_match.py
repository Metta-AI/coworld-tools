"""Play a full match of N agents against each other.

Replaces ``play_eight.sh``.  Starts a server, connects N policy agents
(no filler bots — every slot is a Python policy), and runs until the
match ends or the duration cap is reached.

Usage::

    # 8 modulabots, 10 minutes
    PYTHONPATH=among_them python among_them/scripts/play_match.py

    # 6 agents, different policy, shorter match
    PYTHONPATH=among_them python among_them/scripts/play_match.py \\
        --num-agents 6 --duration 120 \\
        -p modulabot.policy.AmongThemPolicy

    # With per-agent trace + metrics
    PYTHONPATH=among_them python among_them/scripts/play_match.py \\
        --trace-dir /tmp/match_trace --metrics-out /tmp/match.jsonl

Each agent gets a unique name (``<name>-0``, ``<name>-1``, ...),
its own policy instance with seed offset, and — when ``--trace-dir``
is set — its own trace subdirectory.
"""

from __future__ import annotations

import argparse
import logging
import sys
import threading
import time

from _lib import (
    AgentResult,
    add_output_args,
    add_policy_args,
    add_server_args,
    add_session_args,
    agent_loop,
    build_env_info,
    connect_agents,
    derive_max_ticks,
    derive_player_name,
    find_server_binary,
    install_stop_handler,
    parse_policy_kwargs,
    report_results,
    resolve_policy,
    setup_pythonpath,
    setup_trace_env,
    start_server,
    terminate_processes,
    write_captured_frames,
    write_metrics,
)

setup_pythonpath()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("play_match")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run an all-Python Among Them match (server + N agents)."
    )
    add_server_args(parser)
    add_policy_args(parser)
    add_session_args(parser)
    add_output_args(parser)
    # Override num-agents default: a full match wants all slots.
    parser.add_argument(
        "--num-agents",
        type=int,
        default=8,
        help="Number of policy agents (fills all server slots).",
    )
    args = parser.parse_args()

    n = args.num_agents

    setup_trace_env(args.trace_dir, args.trace_level)

    # --- Start server (num_players = num_agents, no fillers) -------------

    server_bin = find_server_binary(args.server_binary)
    max_ticks = derive_max_ticks(args)

    server, config = start_server(
        server_bin,
        num_players=n,
        max_ticks=max_ticks,
        seed=args.seed,
        imposter_count=args.imposter_count,
        force_role=args.force_role,
    )

    try:
        # --- Connect all agents ------------------------------------------

        player_name = derive_player_name(args)
        connections = connect_agents(
            config.host,
            config.port,
            player_name,
            n,
            connect_timeout=10.0,
            stagger=0.25,
        )

        # --- Build policies ----------------------------------------------

        env_info = build_env_info(frame_stack=args.frame_stack, num_agents=1)
        log.info(
            "Env: shape=%s action_count=%d",
            env_info.observation_shape,
            len(env_info.action_names),
        )

        policy_kwargs = parse_policy_kwargs(args.policy_kwarg)
        policies = []
        for i in range(n):
            kw = dict(policy_kwargs)
            kw["seed"] = str(args.seed + i)
            policies.append(
                resolve_policy(args.policy, env_info, policy_kwargs=kw)
            )

        # --- Signal handling ---------------------------------------------

        stop_event = threading.Event()
        install_stop_handler(stop_event)

        # --- Launch agent threads ----------------------------------------

        deadline = (
            None if args.duration <= 0 else time.monotonic() + args.duration
        )
        results: list[AgentResult] = [AgentResult() for _ in range(n)]
        threads: list[threading.Thread] = []

        for agent_id, pname, ws in connections:
            t = threading.Thread(
                target=agent_loop,
                args=(
                    agent_id,
                    pname,
                    ws,
                    policies[agent_id],
                    args.frame_stack,
                    deadline,
                    stop_event,
                ),
                kwargs={
                    "capture_frames": bool(args.capture_frames),
                    "collect_metrics": bool(args.metrics_out),
                    "result": results[agent_id],
                },
                name=f"agent-{agent_id}",
                daemon=True,
            )
            threads.append(t)
            t.start()

        # Wait with periodic wake for signal delivery.
        for t in threads:
            while t.is_alive():
                t.join(timeout=0.5)

        # --- Reporting ---------------------------------------------------

        print(f"\n=== VIEWER URL: ws://{config.host}:{config.port}/global ===\n")
        report_results(results, n)
        if args.metrics_out:
            write_metrics(args.metrics_out, results)
        if args.capture_frames:
            write_captured_frames(args.capture_frames, results, n)

        for p in policies:
            if hasattr(p, "close"):
                p.close(reason="session_end")

    finally:
        log.info("Shutting down...")
        terminate_processes([server], label="server")

    return 0


if __name__ == "__main__":
    sys.exit(main())
