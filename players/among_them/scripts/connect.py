"""Connect N agents running a given policy to an existing Among Them server.

This is the primary client-side script.  It does **not** start a server
— point it at one that's already running (from ``server.py``, the shell
harnesses, or a remote tournament host).

Usage::

    # Current guided_bot policy, 60 seconds
    PYTHONPATH=among_them python among_them/scripts/connect.py \\
        -p guided_bot.cogames.amongthem_policy.AmongThemPolicy \\
        --host 127.0.0.1 --port 2000

    # 4 agents, custom policy, 120 seconds
    PYTHONPATH=among_them python among_them/scripts/connect.py \\
        --host 127.0.0.1 --port 2000 \\
        --num-agents 4 --duration 120 \\
        -p guided_bot.cogames.amongthem_policy.AmongThemPolicy \\
        --policy-kwarg seed=42

    # With trace + metrics + frame capture
    PYTHONPATH=among_them python among_them/scripts/connect.py \\
        -p guided_bot.cogames.amongthem_policy.AmongThemPolicy \\
        --host 127.0.0.1 --port 2000 \\
        --trace-dir /tmp/trace --metrics-out /tmp/metrics.jsonl \\
        --capture-frames /tmp/frames.npy

When ``--num-agents`` > 1, each agent connects on its own WebSocket
with a unique player name (``<name>-0``, ``<name>-1``, ...) and runs
its recv/step/send loop in a dedicated thread with its own policy
instance.
"""

from __future__ import annotations

import argparse
import logging
import sys
import threading
import time

from _lib import (
    AgentResult,
    add_client_args,
    add_output_args,
    add_policy_args,
    add_session_args,
    agent_loop,
    build_env_info,
    connect_agents,
    derive_player_name,
    install_stop_handler,
    parse_policy_kwargs,
    report_results,
    resolve_policy,
    setup_pythonpath,
    setup_trace_env,
    write_captured_frames,
    write_metrics,
)

setup_pythonpath()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("connect")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Connect agent(s) to a running Among Them server."
    )
    add_client_args(parser)
    add_policy_args(parser)
    add_session_args(parser)
    add_output_args(parser)
    args = parser.parse_args()

    n = args.num_agents
    if n < 1:
        log.error("--num-agents must be >= 1")
        return 1

    setup_trace_env(args.trace_dir, args.trace_level)

    # --- Build env info + policies ---------------------------------------

    env_info = build_env_info(frame_stack=args.frame_stack, num_agents=1)
    log.info(
        "Env: shape=%s dtype=%s kind=%s action_count=%d",
        env_info.observation_shape,
        env_info.observation_dtype,
        env_info.observation_kind,
        len(env_info.action_names),
    )

    policy_kwargs = parse_policy_kwargs(args.policy_kwarg)
    # Seed is both a top-level flag and a policy kwarg; inject it unless
    # the user explicitly passed --policy-kwarg seed=... .
    if "seed" not in policy_kwargs:
        policy_kwargs["seed"] = str(args.seed)

    policies = []
    for i in range(n):
        kw = dict(policy_kwargs)
        kw["seed"] = str(args.seed + i)
        policies.append(resolve_policy(args.policy, env_info, policy_kwargs=kw))

    # --- Connect WebSockets ----------------------------------------------

    player_name = derive_player_name(args)
    connections = connect_agents(
        args.host,
        args.port,
        player_name,
        n,
        connect_timeout=args.connect_timeout,
    )

    # --- Signal handling -------------------------------------------------

    stop_event = threading.Event()
    install_stop_handler(stop_event)

    # --- Launch agent threads --------------------------------------------

    deadline = None if args.duration <= 0 else time.monotonic() + args.duration
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

    # Wait for all threads (with periodic wake so signals are delivered).
    for t in threads:
        while t.is_alive():
            t.join(timeout=0.5)

    # --- Reporting -------------------------------------------------------

    report_results(results, n)
    if args.metrics_out:
        write_metrics(args.metrics_out, results)
    if args.capture_frames:
        write_captured_frames(args.capture_frames, results, n)

    # --- Cleanup ---------------------------------------------------------

    for p in policies:
        if hasattr(p, "close"):
            p.close(reason="session_end")

    return 0


if __name__ == "__main__":
    sys.exit(main())
