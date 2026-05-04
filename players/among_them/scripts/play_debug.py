"""One agent with a live debug overlay window.

Replaces ``play_debug.sh``.  Starts a server, fills the lobby with
filler bots, connects one policy agent, and opens a tkinter window
showing the debug overlay in real time (same renderer as
``debug_overlay.py``).

Usage::

    # Quick local debug session
    PYTHONPATH=among_them python among_them/scripts/play_debug.py

    # Custom duration + trace + capture
    PYTHONPATH=among_them python among_them/scripts/play_debug.py \\
        --duration 120 --trace-dir /tmp/debug_trace \\
        --capture-frames /tmp/debug_frames.npy

    # Different policy
    PYTHONPATH=among_them python among_them/scripts/play_debug.py \\
        -p modulabot.policy.AmongThemPolicy --seed 123

Close the window or press ``q`` / ``Esc`` to stop.  The server and
fillers are cleaned up automatically.
"""

from __future__ import annotations

import argparse
import logging
import signal
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any

import numpy as np
import websocket

from _lib import (
    add_output_args,
    add_policy_args,
    add_server_args,
    add_session_args,
    build_env_info,
    button_mask_for_action,
    derive_max_ticks,
    derive_player_name,
    find_filler_binary,
    find_server_binary,
    parse_policy_kwargs,
    resolve_policy,
    setup_pythonpath,
    setup_trace_env,
    spawn_fillers,
    start_server,
    terminate_processes,
    write_captured_frames,
)

setup_pythonpath()

from mettagrid.bitworld import (  # noqa: E402
    BITWORLD_ACTION_NAMES,
    pack_input_packet,
)
from mettagrid.runner.bitworld_runner import (  # noqa: E402
    PlayerConnection,
    _connect_websocket,
    _receive_player_frame,
    _stack_observation,
)

# Import rendering from the debug overlay module (sibling script).
sys.path.insert(0, str(Path(__file__).resolve().parent))
from debug_overlay import (  # noqa: E402
    FrameSnapshot,
    compose,
    render_info_panel,
    render_overlay,
    render_raw,
    summary_line,
)
from modulabot.data import load_reference_data  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("play_debug")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Local Among Them match with a live debug overlay window."
    )
    add_server_args(parser)
    add_policy_args(parser)
    add_session_args(parser)
    add_output_args(parser)
    parser.add_argument(
        "--render-every",
        type=int,
        default=1,
        help="Render the overlay every N frames (raise to 2-3 if laggy).",
    )
    parser.add_argument(
        "--scale",
        type=int,
        default=4,
        help="Pixel zoom factor for the frame display (4 = 512x512).",
    )
    args = parser.parse_args()

    setup_trace_env(args.trace_dir, args.trace_level)

    # --- Start server + fillers ------------------------------------------

    server_bin = find_server_binary(args.server_binary)
    max_ticks = derive_max_ticks(args)

    server, config = start_server(
        server_bin,
        num_players=args.num_players,
        max_ticks=max_ticks,
        seed=args.seed,
        imposter_count=args.imposter_count,
        force_role=args.force_role,
    )

    filler_procs = []
    try:
        # Connect the agent.
        player_name = derive_player_name(args)
        ws = _connect_websocket(
            config, "/player", player_name, player_name=player_name
        )

        # Spawn fillers.
        try:
            filler_bin = find_filler_binary(args.filler_binary)
            filler_procs = spawn_fillers(
                filler_bin,
                config.host,
                config.port,
                args.num_players - 1,
            )
        except FileNotFoundError:
            log.warning("Filler bot binary not found — playing solo.")

        # --- Build policy ------------------------------------------------

        env_info = build_env_info(frame_stack=args.frame_stack, num_agents=1)
        policy_kwargs = parse_policy_kwargs(args.policy_kwarg)
        if "seed" not in policy_kwargs:
            policy_kwargs["seed"] = str(args.seed)
        policy = resolve_policy(
            args.policy, env_info, policy_kwargs=policy_kwargs
        )

        conn = PlayerConnection(ws=ws, player_index=0, address=player_name)
        data = load_reference_data()
        log.info("Policy instantiated; env=%s", env_info.observation_shape)

        # --- Tkinter window ----------------------------------------------

        import tkinter as tk
        from PIL import ImageTk

        root = tk.Tk()
        root.title(f"Among Them debug · {player_name}")
        root.configure(bg="#1e1e22")

        canvas = tk.Label(root, bg="#1e1e22")
        canvas.pack(padx=4, pady=4)
        status = tk.Label(
            root,
            bg="#1e1e22",
            fg="#cccccc",
            font=("Menlo", 11),
            anchor="w",
            justify="left",
        )
        status.pack(fill="x", padx=4)
        tk_image_ref: dict[str, Any] = {}

        shutdown = {"flag": False}

        def stop(*_a):
            shutdown["flag"] = True

        root.protocol("WM_DELETE_WINDOW", stop)
        root.bind(
            "<Key>",
            lambda e: stop() if e.keysym.lower() in ("q", "escape") else None,
        )
        signal.signal(signal.SIGINT, lambda *_: stop())
        signal.signal(signal.SIGTERM, lambda *_: stop())

        def render(snap: FrameSnapshot) -> None:
            raw_img = render_raw(snap.frame, scale=args.scale)
            overlay_img = render_overlay(snap, data, scale=args.scale)
            info_img = render_info_panel(snap, 0, 1, 360, raw_img.height)
            composite = compose(raw_img, overlay_img, info_img)
            tk_image = ImageTk.PhotoImage(composite)
            canvas.configure(image=tk_image)
            tk_image_ref["img"] = tk_image
            status.configure(text=summary_line(snap))

        # --- Main loop ---------------------------------------------------

        log.info(
            "Window open.  Close or press q/Esc to stop.  "
            "Viewer URL: ws://%s:%d/global",
            config.host,
            config.port,
        )

        deadline = time.monotonic() + args.duration
        frame_count = 0
        action_counts: Counter[int] = Counter()
        captured: list[np.ndarray] = []

        try:
            while not shutdown["flag"] and time.monotonic() < deadline:
                frame_data, frame_advance = _receive_player_frame(conn)
                if frame_data is None:
                    if not conn.alive:
                        log.info("WebSocket closed.")
                        break
                    try:
                        root.update()
                    except tk.TclError:
                        shutdown["flag"] = True
                        break
                    continue

                obs = _stack_observation(conn, frame_data, args.frame_stack)
                if args.capture_frames:
                    captured.append(obs[-1].copy())

                batch_obs = obs[np.newaxis]
                actions_out = np.zeros(1, dtype=np.int32)
                policy.step_batch(batch_obs, actions_out)
                action_index = int(actions_out[0])
                action_counts[action_index] += 1

                mask = button_mask_for_action(action_index)
                try:
                    ws.send(
                        pack_input_packet(mask),
                        opcode=websocket.ABNF.OPCODE_BINARY,
                    )
                except Exception as exc:
                    log.info("Send failed: %s", exc)
                    break

                frame_count += 1

                if frame_count % args.render_every == 0:
                    bot = policy._cores[0].bot
                    snap = FrameSnapshot.from_bot(bot, obs[-1])
                    try:
                        render(snap)
                        root.update()
                    except tk.TclError:
                        shutdown["flag"] = True
                        break
        finally:
            elapsed = max(
                1e-6, time.monotonic() - (deadline - args.duration)
            )
            fps = frame_count / elapsed if frame_count else 0
            log.info(
                "Session ended: %.1fs, %d frames (%.1f fps).",
                elapsed,
                frame_count,
                fps,
            )
            if frame_count:
                log.info("Action mix (top 5):")
                for idx, cnt in action_counts.most_common(5):
                    log.info(
                        "  %-14s %5d  (%5.1f%%)",
                        BITWORLD_ACTION_NAMES[idx],
                        cnt,
                        100.0 * cnt / frame_count,
                    )

            if args.capture_frames and captured:
                from _lib import AgentResult

                r = AgentResult(captured_frames=captured)
                write_captured_frames(args.capture_frames, [r], 1)

            try:
                ws.close()
            except Exception:
                pass
            if hasattr(policy, "close"):
                policy.close(reason="session_end")
            try:
                root.destroy()
            except Exception:
                pass

    finally:
        log.info("Shutting down...")
        terminate_processes(filler_procs, label="filler")
        terminate_processes([server], label="server")

    return 0


if __name__ == "__main__":
    sys.exit(main())
