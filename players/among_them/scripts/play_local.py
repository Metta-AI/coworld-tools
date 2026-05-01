"""Play one local episode of BitWorld Among Them.

Runs the real Nim server (pre-built binary at `~/coding/bitworld/out/among_them`),
fills the lobby with a few headless Nim bots, connects our modulabot
``AmongThemPolicy`` as one of the players, and prints:

- The actual observation shape our policy receives.
- Action counts per agent.
- Whether the episode terminated cleanly.

This is the ground-truth check: whatever ``cogames run/ship/tournament`` would
hand modulabot, this script reproduces locally.
"""

from __future__ import annotations

import argparse
import logging
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import numpy as np

from mettagrid.bitworld import (
    BITWORLD_ACTION_COUNT,
    BITWORLD_ACTION_NAMES,
    BITWORLD_DEFAULT_FRAME_STACK,
    SCREEN_HEIGHT,
    SCREEN_WIDTH,
)
from mettagrid.policy.policy_env_interface import PolicyEnvInterface
from mettagrid.runner.bitworld_runner import (
    BitWorldConfig,
    _build_bitworld_env_interface,
    _connect_websocket,
    _pick_free_port,
    _start_server_on_free_port,
    _stack_observation,
    _unpack_frame,
    PlayerConnection,
)
from mettagrid.bitworld import (
    encode_buttons,
    bitworld_action_index,
    pack_input_packet,
    PACKED_FRAME_BYTES,
)

import websocket

# Ensure the modulabot package is importable.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from modulabot.policy import AmongThemPolicy  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("play_local")


def find_binary() -> Path:
    env = os.environ.get("AMONG_THEM_BINARY")
    if env:
        path = Path(env)
        if path.exists():
            return path
    candidates = [
        Path.home() / "coding" / "bitworld" / "out" / "among_them",
        Path.home() / "bitworld" / "out" / "among_them",
        Path("/opt/bitworld/among_them/among_them"),
    ]
    for c in candidates:
        if c.exists():
            return c
    raise FileNotFoundError(
        "Among Them binary not found. Set AMONG_THEM_BINARY or build it at ~/coding/bitworld/out/among_them."
    )


def button_mask_for_action(action: int) -> int:
    """Convert a 27-wide action index into a 7-bit BitWorld button mask."""
    name = BITWORLD_ACTION_NAMES[action]
    if name == "noop":
        return 0
    return encode_buttons(name.split("+"))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--duration", type=float, default=20.0, help="Episode wall-clock seconds.")
    parser.add_argument("--num-players", type=int, default=8)
    parser.add_argument("--frame-stack", type=int, default=BITWORLD_DEFAULT_FRAME_STACK)
    parser.add_argument("--log-frame-shapes", action="store_true", default=True)
    parser.add_argument(
        "--max-ticks",
        type=int,
        default=60 * 24 * 10,  # 10 minutes at 24 Hz
        help="Server tick cap. Defaults to 10 min; override for short runs.",
    )
    parser.add_argument(
        "--trace-dir",
        default=None,
        help="Enable trace writer into this directory (sets MODULABOT_TRACE_DIR).",
    )
    parser.add_argument(
        "--metrics-out",
        default=None,
        help="If set, write a JSONL file with per-tick motion / action metrics.",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Policy RNG seed.",
    )
    args = parser.parse_args()

    if args.trace_dir:
        os.environ["MODULABOT_TRACE_DIR"] = args.trace_dir
        log.info("Trace enabled: %s", args.trace_dir)

    binary = find_binary()
    log.info("Using binary: %s", binary)

    config = BitWorldConfig(
        binary_path=str(binary),
        host="127.0.0.1",
        port=0,
        num_players=args.num_players,
        max_ticks=args.max_ticks,
    )

    server = _start_server_on_free_port(binary, config)
    log.info("Server running on port %d", config.port)

    try:
        # Connect our Python policy as one player.
        ws = _connect_websocket(config, "/player", "modulabot", player_name="modulabot")

        # Fill remaining slots with headless Nim bots (nottoodumb, which ships with bitworld).
        bot_procs = []
        nottoodumb_bin = Path.home() / "coding" / "bitworld" / "out" / "nottoodumb"
        if not nottoodumb_bin.exists():
            log.warning("nottoodumb binary not found at %s — will play solo (server may not start)", nottoodumb_bin)
        else:
            for i in range(args.num_players - 1):
                p = subprocess.Popen(
                    [
                        str(nottoodumb_bin),
                        f"--address:{config.host}",
                        f"--port:{config.port}",
                        f"--name:bot{i+1}",
                    ],
                    cwd=str(nottoodumb_bin.parent),
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                bot_procs.append(p)
                time.sleep(0.1)

        # Build a PolicyEnvInterface the way the real runner does, then the policy.
        env_info = _build_bitworld_env_interface(frame_stack=args.frame_stack, num_agents=1)
        log.info(
            "Observation space: shape=%s dtype=%s kind=%s  action_count=%d",
            env_info.observation_shape,
            env_info.observation_dtype,
            env_info.observation_kind,
            len(env_info.action_names),
        )

        policy = AmongThemPolicy(env_info, seed=args.seed)
        log.info("Instantiated %s (seed=%d)", policy.__class__.__name__, args.seed)

        conn = PlayerConnection(ws=ws, player_index=0, address="modulabot")

        deadline = time.monotonic() + args.duration
        frame_count = 0
        action_counts = {}
        first_shape_logged = False

        # Per-tick metrics buffer; flushed to --metrics-out on exit so we
        # can compare a before/after run without sifting through the
        # trace JSONL. Kept in-memory because even 10 minutes at 24 Hz
        # is only ~14k rows.
        metrics: list[dict] = []
        prev_direction_axis: int | None = None  # -1/+1 sign or None
        direction_flips_10 = 0  # rolling count (cleared at log time)
        recent_actions: list[int] = []

        while time.monotonic() < deadline:
            try:
                payload = ws.recv()
            except Exception as e:
                log.info("websocket closed: %s", e)
                break
            if not isinstance(payload, (bytes, bytearray)):
                continue
            if len(payload) != PACKED_FRAME_BYTES:
                # Non-frame packet (reward, chat). Ignore.
                continue

            obs = _stack_observation(conn, payload, args.frame_stack)
            if not first_shape_logged:
                log.info("First observation: shape=%s dtype=%s min=%d max=%d",
                         obs.shape, obs.dtype, int(obs.min()), int(obs.max()))
                log.info("Unique palette indices in frame: %s", sorted(np.unique(obs).tolist()))
                first_shape_logged = True

            # Policy expects a batch axis. Give it (1, frame_stack, H, W).
            batch_obs = obs[np.newaxis]
            actions = np.zeros(1, dtype=np.int32)
            policy.step_batch(batch_obs, actions)

            action_index = int(actions[0])
            action_counts[action_index] = action_counts.get(action_index, 0) + 1

            # Capture per-tick motion metrics for the before/after
            # comparison. bot.motion and bot.percep are populated by the
            # pipeline this step, so we can just read them back here.
            bot = policy._cores[0].bot
            m = bot.motion
            recent_actions.append(action_index)
            if len(recent_actions) > 10:
                recent_actions.pop(0)
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

            # Convert to BitWorld button mask, pack, send.
            mask = button_mask_for_action(action_index)
            packet = pack_input_packet(mask)
            try:
                ws.send(packet, opcode=websocket.ABNF.OPCODE_BINARY)
            except Exception as e:
                log.info("Send failed: %s", e)
                break

            frame_count += 1

        log.info("Frames received: %d", frame_count)
        if frame_count > 0:
            log.info("Action name -> count:")
            for idx, count in sorted(action_counts.items(), key=lambda kv: -kv[1]):
                log.info("  %s (%d): %d", BITWORLD_ACTION_NAMES[idx], idx, count)
            top_action = max(action_counts.items(), key=lambda kv: kv[1])
            log.info("Most common: %s (%d times)", BITWORLD_ACTION_NAMES[top_action[0]], top_action[1])

            # Motion summary — the headline Phase-1 metrics.
            playing = [m for m in metrics if m["phase"] == "PLAYING"]
            if playing:
                import statistics

                nonzero_v = [
                    abs(m["velocity_x"]) + abs(m["velocity_y"])
                    for m in playing
                    if (m["velocity_x"] or m["velocity_y"])
                ]
                stuck = [m["stuck_ticks"] for m in playing]
                log.info("--- Motion metrics (PLAYING frames only) ---")
                log.info("  frames: %d", len(playing))
                log.info(
                    "  frames with non-zero velocity: %d (%.1f%%)",
                    len(nonzero_v),
                    100.0 * len(nonzero_v) / len(playing),
                )
                if nonzero_v:
                    log.info(
                        "  |velocity| mean=%.2f median=%.1f max=%d",
                        statistics.mean(nonzero_v),
                        statistics.median(nonzero_v),
                        max(nonzero_v),
                    )
                log.info(
                    "  stuck_ticks mean=%.1f p95=%d max=%d",
                    statistics.mean(stuck),
                    sorted(stuck)[int(0.95 * len(stuck))],
                    max(stuck),
                )
                jiggle_frames = sum(1 for m in playing if m["jiggle_ticks"] > 0)
                log.info(
                    "  jiggle-active frames: %d (%.1f%%)",
                    jiggle_frames,
                    100.0 * jiggle_frames / len(playing),
                )

                # Direction-flip rate on the horizontal axis — cheap
                # proxy for orbit-around-target behaviour.
                horizontal = {
                    BITWORLD_ACTION_NAMES.index("left"): -1,
                    BITWORLD_ACTION_NAMES.index("right"): +1,
                }
                flips = 0
                last = 0
                for m in playing:
                    axis = horizontal.get(m["action"], 0)
                    if axis and last and axis != last:
                        flips += 1
                    if axis:
                        last = axis
                log.info(
                    "  horizontal direction flips: %d (%.1f per 100 playing frames)",
                    flips,
                    100.0 * flips / len(playing),
                )
        else:
            log.warning("No frames received — server may not have started the match.")

        if args.metrics_out:
            import json as _json

            out_path = Path(args.metrics_out)
            out_path.parent.mkdir(parents=True, exist_ok=True)
            with out_path.open("w") as f:
                for row in metrics:
                    f.write(_json.dumps(row) + "\n")
            log.info("Wrote %d metric rows to %s", len(metrics), out_path)

    finally:
        log.info("Shutting down...")
        try:
            ws.close()
        except Exception:
            pass
        for p in bot_procs:
            try:
                p.terminate()
                p.wait(timeout=2)
            except Exception:
                try:
                    p.kill()
                except Exception:
                    pass
        try:
            server.terminate()
            server.wait(timeout=2)
        except Exception:
            try:
                server.kill()
            except Exception:
                pass


if __name__ == "__main__":
    main()
