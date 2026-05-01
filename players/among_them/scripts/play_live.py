"""Live-test modulabot against an already-running Among Them server.

Unlike :mod:`scripts.play_local`, this does **not** start its own
server or spawn filler bots — it connects to a server the caller
has running elsewhere (e.g. ``~/coding/bitworld/out/among_them
--address:127.0.0.1 --port:2000``).

Usage::

    cd /Users/jamesboggs/coding/personal_cogs
    source .venv/bin/activate
    PYTHONPATH=among_them python among_them/scripts/play_live.py

Defaults to ``127.0.0.1:2000`` with 60 seconds of play. Any
argument can be overridden::

    python among_them/scripts/play_live.py \\
        --host 127.0.0.1 --port 2000 --name modulabot \\
        --duration 120 --trace-dir /tmp/modulabot_runs

Trace output is opt-in via ``--trace-dir`` (sets
``MODULABOT_TRACE_DIR`` for the session). The tournament worker
will have this off by default; enabling it locally captures the
full session manifest + decisions stream for offline analysis.
"""

from __future__ import annotations

import argparse
import logging
import os
import signal
import sys
import time
from collections import Counter
from pathlib import Path

import numpy as np
import websocket

# Ensure the modulabot package is importable when this script runs
# from the repo root.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mettagrid.bitworld import (  # noqa: E402
    BITWORLD_ACTION_NAMES,
    BITWORLD_DEFAULT_FRAME_STACK,
    PACKED_FRAME_BYTES,
    encode_buttons,
    pack_input_packet,
)
from mettagrid.runner.bitworld_runner import (  # noqa: E402
    BitWorldConfig,
    PlayerConnection,
    _build_bitworld_env_interface,
    _connect_websocket,
    _stack_observation,
)

from modulabot.policy import AmongThemPolicy  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("play_live")


def _button_mask_for_action(action: int) -> int:
    """Translate a 27-wide action index into the BitWorld button mask.

    Mirrors the helper in :mod:`scripts.play_local` so both scripts
    emit identical wire-level input packets.
    """
    name = BITWORLD_ACTION_NAMES[action]
    if name == "noop":
        return 0
    return encode_buttons(name.split("+"))


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run modulabot against an already-running Among Them server."
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=2000)
    parser.add_argument(
        "--name",
        default="modulabot",
        help="Player name sent in the WebSocket join URL.",
    )
    parser.add_argument(
        "--duration",
        type=float,
        default=60.0,
        help="Seconds of wall-clock play before disconnecting.",
    )
    parser.add_argument(
        "--frame-stack",
        type=int,
        default=BITWORLD_DEFAULT_FRAME_STACK,
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="RNG seed for the policy (affects fake-task rolls etc.).",
    )
    parser.add_argument(
        "--trace-dir",
        default=None,
        help="Enable trace writer into this directory (sets MODULABOT_TRACE_DIR).",
    )
    parser.add_argument(
        "--trace-level",
        default="decisions",
        choices=("off", "events", "decisions"),
        help="Trace verbosity (ignored unless --trace-dir is set).",
    )
    parser.add_argument(
        "--metrics-out",
        default=None,
        help=(
            "Dump a per-tick JSONL with (tick, phase, role, camera, "
            "velocity, stuck_ticks, action, branch_id) for offline "
            "motion / oscillation analysis. Complements the trace "
            "writer, which only emits on branch transitions."
        ),
    )
    parser.add_argument(
        "--capture-frames",
        default=None,
        help=(
            "Path to save raw 128x128 observation frames to an .npy file. "
            "One row per tick; scrub with `scripts/debug_overlay.py --watch`. "
            "Only the most recent frame of each observation stack is kept "
            "to avoid 4x bloat."
        ),
    )
    args = parser.parse_args()

    if args.trace_dir:
        os.environ["MODULABOT_TRACE_DIR"] = args.trace_dir
        os.environ["MODULABOT_TRACE_LEVEL"] = args.trace_level
        log.info("Trace enabled: %s (level=%s)", args.trace_dir, args.trace_level)

    # Minimal BitWorldConfig — we only need host + port + connect_timeout_s
    # for :func:`_connect_websocket`. All other fields are ignored because
    # we're not starting a server.
    config = BitWorldConfig(host=args.host, port=args.port, connect_timeout_s=5.0)
    log.info("Connecting to ws://%s:%d as %s…", args.host, args.port, args.name)

    try:
        ws = _connect_websocket(config, "/player", args.name, player_name=args.name)
    except ConnectionError as e:
        log.error(
            "Failed to connect: %s. Is a server running on %s:%d?",
            e,
            args.host,
            args.port,
        )
        return 1

    # Build the PolicyEnvInterface and the policy.
    env_info = _build_bitworld_env_interface(
        frame_stack=args.frame_stack, num_agents=1
    )
    log.info(
        "Env: shape=%s dtype=%s kind=%s action_count=%d",
        env_info.observation_shape,
        env_info.observation_dtype,
        env_info.observation_kind,
        len(env_info.action_names),
    )

    policy = AmongThemPolicy(env_info, seed=args.seed)
    log.info("Instantiated %s (seed=%d)", policy.__class__.__name__, args.seed)

    conn = PlayerConnection(ws=ws, player_index=0, address=args.name)

    # Clean-shutdown flag so Ctrl-C closes the socket gracefully
    # instead of ripping it out mid-recv.
    stop = False

    def _handle_sigint(signum, frame):  # pragma: no cover - signal handler
        nonlocal stop
        log.info("Received signal %s, shutting down…", signum)
        stop = True

    signal.signal(signal.SIGINT, _handle_sigint)
    signal.signal(signal.SIGTERM, _handle_sigint)

    deadline = time.monotonic() + args.duration
    frame_count = 0
    action_counts: Counter[int] = Counter()
    branch_counts: Counter[str] = Counter()
    phase_counts: Counter[str] = Counter()
    first_shape_logged = False
    start_time = time.monotonic()

    # Per-tick metrics buffer; flushed to --metrics-out on exit. Cheap
    # in-memory list; 5 minutes at 24 Hz is ~7200 rows, well under
    # anything that would strain RAM.
    metrics: list[dict] = []
    # Raw-frames buffer; flushed to --capture-frames on exit. Only the
    # most recent frame of each stack is kept (the stack's 4x history
    # is redundant once laid out in tick order). 10 minutes of 128x128
    # uint8 frames is ~220 MB — comfortably in RAM.
    captured_frames: list[np.ndarray] = [] if args.capture_frames else []

    try:
        while not stop and time.monotonic() < deadline:
            try:
                payload = ws.recv()
            except websocket.WebSocketTimeoutException:
                continue
            except Exception as exc:  # noqa: BLE001 — log & exit gracefully
                log.info("WebSocket closed: %s", exc)
                break

            if not isinstance(payload, (bytes, bytearray)):
                # Chat / event / reward packet — ignore for now.
                continue
            if len(payload) != PACKED_FRAME_BYTES:
                # Any binary packet that isn't a frame (e.g. handshake,
                # chat echo). Skip silently.
                continue

            obs = _stack_observation(conn, payload, args.frame_stack)
            if not first_shape_logged:
                log.info(
                    "First obs: shape=%s dtype=%s min=%d max=%d unique=%s",
                    obs.shape,
                    obs.dtype,
                    int(obs.min()),
                    int(obs.max()),
                    sorted(np.unique(obs).tolist()),
                )
                first_shape_logged = True

            if args.capture_frames:
                # Only the most recent frame of the stack — history
                # the stack carries is redundant once we lay the
                # per-tick frames out in time order.
                captured_frames.append(obs[-1].copy())

            batch_obs = obs[np.newaxis]
            actions_out = np.zeros(1, dtype=np.int32)
            policy.step_batch(batch_obs, actions_out)

            action_index = int(actions_out[0])
            action_counts[action_index] += 1
            bot = policy._cores[0].bot
            branch_counts[bot.diag.branch_id or "(empty)"] += 1
            phase_counts[bot.percep.phase.name] += 1

            if args.metrics_out:
                m = bot.motion
                metrics.append(
                    {
                        "tick": bot.tick,
                        "phase": bot.percep.phase.name,
                        "role": bot.role.name,
                        "localized": bool(bot.percep.localized),
                        "camera_x": bot.percep.camera_x,
                        "camera_y": bot.percep.camera_y,
                        "velocity_x": m.velocity_x,
                        "velocity_y": m.velocity_y,
                        "stuck_ticks": m.stuck_ticks,
                        "jiggle_ticks": m.jiggle_ticks,
                        "goal_has": bool(bot.goal.has),
                        "action": action_index,
                        "action_name": BITWORLD_ACTION_NAMES[action_index],
                        "branch_id": bot.diag.branch_id,
                    }
                )

            mask = _button_mask_for_action(action_index)
            try:
                ws.send(pack_input_packet(mask), opcode=websocket.ABNF.OPCODE_BINARY)
            except Exception as exc:  # noqa: BLE001
                log.info("Send failed: %s", exc)
                break

            # Flush any queued chat the policy produced this frame.
            # cogames surfaces chat via Action(talk=...); for the raw
            # WebSocket path we'd need a separate chat opcode — leave a
            # warning so we notice if chat ever gets queued.
            chat_text = policy.last_chat(0)
            if chat_text:
                log.info("chat queued (not sent via raw WS): %r", chat_text)

            frame_count += 1
    finally:
        elapsed = time.monotonic() - start_time
        log.info("Session ended after %.1fs, %d frames processed.", elapsed, frame_count)
        if frame_count:
            fps = frame_count / elapsed if elapsed > 0 else 0
            log.info(
                "Action mix (top 6 of %d):", len(action_counts)
            )
            for idx, cnt in action_counts.most_common(6):
                log.info(
                    "  %-14s %5d  (%5.1f%%)",
                    BITWORLD_ACTION_NAMES[idx],
                    cnt,
                    100.0 * cnt / frame_count,
                )
            log.info("Top branch IDs fired (top 6):")
            for branch, cnt in branch_counts.most_common(6):
                log.info("  %-32s %5d", branch, cnt)
            log.info("Phase distribution:")
            for phase, cnt in phase_counts.most_common():
                log.info("  %-14s %5d", phase, cnt)
            log.info("Avg throughput: %.1f frames/s", fps)

        if args.metrics_out and metrics:
            import json as _json
            from pathlib import Path as _Path

            out = _Path(args.metrics_out)
            out.parent.mkdir(parents=True, exist_ok=True)
            with out.open("w") as f:
                for row in metrics:
                    f.write(_json.dumps(row) + "\n")
            log.info("Wrote %d metric rows to %s", len(metrics), out)

        if args.capture_frames and captured_frames:
            from pathlib import Path as _Path

            out = _Path(args.capture_frames)
            out.parent.mkdir(parents=True, exist_ok=True)
            arr = np.stack(captured_frames, axis=0).astype(np.uint8)
            np.save(out, arr)
            log.info(
                "Wrote %d frames to %s (%.1f MB, %dx%d)",
                arr.shape[0],
                out,
                arr.nbytes / 1e6,
                arr.shape[2],
                arr.shape[1],
            )

        try:
            ws.close()
        except Exception:
            pass
        policy.close(reason="session_end")

    return 0


if __name__ == "__main__":
    sys.exit(main())
