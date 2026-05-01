"""Play one local episode of Among Them.

Composes ``server.py`` + filler bots + ``connect.py`` into a single
command for quick local testing.  Starts the Nim server, fills the
lobby with nottoodumb bots, connects one policy agent, and prints
session stats on exit.

Usage::

    # Quick 20-second run with modulabot
    PYTHONPATH=among_them python among_them/scripts/play_local.py \\
        --duration 20

    # Different policy, longer run, with metrics
    PYTHONPATH=among_them python among_them/scripts/play_local.py \\
        -p modulabot.policy.AmongThemPolicy --duration 60 \\
        --metrics-out /tmp/metrics.jsonl

    # With trace + frame capture
    PYTHONPATH=among_them python among_them/scripts/play_local.py \\
        --duration 30 --trace-dir /tmp/trace \\
        --capture-frames /tmp/frames.npy

This is the ground-truth check: whatever ``cogames run/ship/tournament``
would hand the policy, this script reproduces locally.
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
    derive_max_ticks,
    derive_player_name,
    find_filler_binary,
    find_server_binary,
    install_stop_handler,
    parse_policy_kwargs,
    report_results,
    resolve_policy,
    setup_pythonpath,
    setup_trace_env,
    spawn_fillers,
    start_server,
    terminate_processes,
    write_captured_frames,
    write_metrics,
)

setup_pythonpath()

from mettagrid.runner.bitworld_runner import _connect_websocket  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("play_local")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Play one local Among Them episode (server + fillers + 1 agent)."
    )
    add_server_args(parser)
    add_policy_args(parser)
    add_session_args(parser)
    add_output_args(parser)
    args = parser.parse_args()

    setup_trace_env(args.trace_dir, args.trace_level)

    # --- Start server ----------------------------------------------------

    server_bin = find_server_binary(args.server_binary)
    log.info("Using server binary: %s", server_bin)

    max_ticks = derive_max_ticks(args)
    server, config = start_server(
        server_bin,
        num_players=args.num_players,
        max_ticks=max_ticks,
        seed=args.seed,
        imposter_count=args.imposter_count,
    )

    filler_procs = []
    try:
        # --- Connect our policy agent ------------------------------------

        player_name = derive_player_name(args)
        ws = _connect_websocket(
            config, "/player", player_name, player_name=player_name
        )

        # --- Spawn fillers -----------------------------------------------

        try:
            filler_bin = find_filler_binary(args.filler_binary)
            filler_procs = spawn_fillers(
                filler_bin,
                config.host,
                config.port,
                args.num_players - 1,
            )
        except FileNotFoundError:
            log.warning(
                "Filler bot binary not found — playing solo "
                "(server may not start the match)."
            )

        # --- Build policy ------------------------------------------------

        env_info = build_env_info(frame_stack=args.frame_stack, num_agents=1)
        log.info(
            "Env: shape=%s dtype=%s action_count=%d",
            env_info.observation_shape,
            env_info.observation_dtype,
            len(env_info.action_names),
        )

        policy_kwargs = parse_policy_kwargs(args.policy_kwarg)
        if "seed" not in policy_kwargs:
            policy_kwargs["seed"] = str(args.seed)
        policy = resolve_policy(args.policy, env_info, policy_kwargs=policy_kwargs)

        # --- Run the agent loop ------------------------------------------

        stop_event = threading.Event()
        install_stop_handler(stop_event)

        deadline = (
            None if args.duration <= 0 else time.monotonic() + args.duration
        )
        result = AgentResult()
        agent_loop(
            agent_id=0,
            player_name=player_name,
            ws=ws,
            policy=policy,
            frame_stack=args.frame_stack,
            deadline=deadline,
            stop_event=stop_event,
            capture_frames=bool(args.capture_frames),
            collect_metrics=bool(args.metrics_out),
            result=result,
        )

        # --- Report ------------------------------------------------------

        report_results([result], 1)
        if args.metrics_out:
            write_metrics(args.metrics_out, [result])
        if args.capture_frames:
            write_captured_frames(args.capture_frames, [result], 1)

        if hasattr(policy, "close"):
            policy.close(reason="session_end")

    finally:
        log.info("Shutting down...")
        terminate_processes(filler_procs, label="filler")
        terminate_processes([server], label="server")

    return 0


if __name__ == "__main__":
    sys.exit(main())
