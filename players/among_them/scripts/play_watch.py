"""Live debug viewer — one modulabot against an existing server, with a
real-time tkinter window showing the debug overlay every tick.

Combines :mod:`scripts.play_live` (connect + run policy) with
:mod:`scripts.debug_overlay`'s renderer, but instead of post-hoc
scrubbing of captured frames it paints the overlay as the bot plays.
Use it to *watch the bot decide* rather than reconstruct its decisions
after the fact.

Usage:

    # Requires a running server on the given host/port.
    PYTHONPATH=among_them python among_them/scripts/play_watch.py \\
        --host 127.0.0.1 --port 2000 --name modulabot-debug

    # With trace + frame capture (same flags as play_live.py)
    PYTHONPATH=among_them python among_them/scripts/play_watch.py \\
        --host 127.0.0.1 --port 12345 \\
        --trace-dir /tmp/watched --capture-frames /tmp/watched/frames.npy

The tkinter window pops up after the first received frame and updates
every tick (~22-24 fps at BitWorld's rate). Close the window or press
q/Esc to stop.

Notes on cost: rendering the overlay + updating the tk canvas runs at
roughly ~30-50 ms per frame. The BitWorld server ticks at ~42 ms, so
we're borderline — under heavy game load some frames may be skipped
in the UI (the bot still processes every received frame). Use
``--render-every N`` to render every Nth frame instead if you see
lag.
"""

from __future__ import annotations

import argparse
import logging
import signal
import sys
import time
from collections import Counter
from typing import Any

import numpy as np
import websocket

from _lib import (
    add_client_args,
    add_output_args,
    add_policy_args,
    add_session_args,
    build_env_info,
    button_mask_for_action,
    derive_player_name,
    parse_policy_kwargs,
    resolve_policy,
    setup_pythonpath,
    setup_trace_env,
    write_captured_frames,
)

setup_pythonpath()

from mettagrid.bitworld import (  # noqa: E402
    BITWORLD_ACTION_NAMES,
    pack_input_packet,
)
from mettagrid.runner.bitworld_runner import (  # noqa: E402
    BitWorldRuntime,
    PlayerConnection,
    _connect_websocket,
    _receive_player_frame,
    _stack_observation,
)

from modulabot.data import load_reference_data  # noqa: E402

# Re-use the exact renderer from the offline overlay so the live view
# is visually identical (and fixes in one land in both).
from debug_overlay import (  # noqa: E402
    FrameSnapshot,
    compose,
    render_info_panel,
    render_overlay,
    render_raw,
    summary_line,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("play_watch")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Connect to a running server with a live debug overlay window."
    )
    add_client_args(parser)
    add_policy_args(parser)
    add_session_args(parser)
    add_output_args(parser)
    parser.add_argument(
        "--render-every",
        type=int,
        default=1,
        help="Render the overlay every N frames. Raise to 2-3 if the UI "
        "can't keep up at full tick rate.",
    )
    parser.add_argument(
        "--scale",
        type=int,
        default=4,
        help="Pixel zoom factor for the frame display (4 = 512x512 window).",
    )
    args = parser.parse_args()
    # Default name for the watch script differs from the generic default.
    if args.name is None:
        args.name = derive_player_name(args) + "w"

    setup_trace_env(args.trace_dir, args.trace_level)

    # ---------------- WebSocket + policy setup ---------------------
    config = BitWorldRuntime(host=args.host, port=args.port)
    log.info("Connecting to ws://%s:%d as %s...", args.host, args.port, args.name)
    try:
        ws = _connect_websocket(config, "/player", args.name, player_name=args.name,
                                connect_timeout_s=args.connect_timeout)
    except ConnectionError as exc:
        log.error("Failed to connect: %s", exc)
        return 1

    env_info = build_env_info(frame_stack=args.frame_stack, num_agents=1)
    policy_kwargs = parse_policy_kwargs(args.policy_kwarg)
    if "seed" not in policy_kwargs:
        policy_kwargs["seed"] = str(args.seed)
    policy = resolve_policy(args.policy, env_info, policy_kwargs=policy_kwargs)
    conn = PlayerConnection(ws=ws, player_index=0, address=args.name)
    data = load_reference_data()
    log.info("Policy instantiated; env=%s", env_info.observation_shape)

    # ---------------- Tkinter window --------------------------------
    import tkinter as tk
    from PIL import ImageTk

    root = tk.Tk()
    root.title(f"modulabot live · {args.name}")
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

    def stop(*_a):  # pragma: no cover — handler
        shutdown["flag"] = True

    root.protocol("WM_DELETE_WINDOW", stop)
    root.bind("<Key>", lambda e: stop() if e.keysym.lower() in ("q", "escape") else None)
    signal.signal(signal.SIGINT, lambda *_: stop())
    signal.signal(signal.SIGTERM, lambda *_: stop())

    def render(snap: FrameSnapshot) -> None:
        raw = render_raw(snap.frame, scale=args.scale)
        overlay = render_overlay(snap, data, scale=args.scale)
        info = render_info_panel(snap, 0, 1, 360, raw.height)
        composite = compose(raw, overlay, info)
        tk_image = ImageTk.PhotoImage(composite)
        canvas.configure(image=tk_image)
        tk_image_ref["img"] = tk_image  # keep alive
        status.configure(text=summary_line(snap))

    # ---------------- Main loop -------------------------------------
    deadline = time.monotonic() + args.duration
    frame_count = 0
    action_counts: Counter[int] = Counter()
    captured: list[np.ndarray] = [] if args.capture_frames else []
    # Diagnostic: how far ahead the server was each tick. _receive_player_frame
    # returns the count of frames skipped (latest - oldest drained). A healthy
    # session has frame_advance=1 most ticks; persistently >1 means Python
    # can't keep up with the 24 FPS server.
    frame_advance_total = 0
    frame_advance_max = 0
    frame_advance_skipped = 0  # sum of (advance - 1) across all ticks

    log.info(
        "Window open. Close the window or press q/Esc to stop. "
        "Duration cap: %ss.",
        int(args.duration),
    )

    try:
        while not shutdown["flag"] and time.monotonic() < deadline:
            # Drain queued frames via the tournament runner's helper —
            # returns the *latest* frame plus a count of frames skipped
            # (frame_advance). Hand-rolling ``ws.recv()`` in FIFO order
            # lets stale frames pile up when Python can't keep up with
            # the server's 24 FPS send rate, which caused the bot to
            # act on state that was already minutes out of date.
            frame_data, frame_advance = _receive_player_frame(conn)
            if frame_data is None:
                if not conn.alive:
                    log.info("WebSocket closed.")
                    break
                # Timeout with no frame queued — keep UI responsive
                # (e.g. lobby waiting for match start).
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

            # Use the canonical button mask lookup from _lib.
            mask = button_mask_for_action(action_index)
            try:
                ws.send(pack_input_packet(mask), opcode=websocket.ABNF.OPCODE_BINARY)
            except Exception as exc:  # noqa: BLE001
                log.info("Send failed: %s", exc)
                break

            frame_count += 1
            frame_advance_total += frame_advance
            frame_advance_skipped += max(0, frame_advance - 1)
            if frame_advance > frame_advance_max:
                frame_advance_max = frame_advance

            # Render the overlay every N frames and pump the tk loop.
            # Rendering is the expensive bit (~30-50 ms); we skip
            # frames with ``--render-every`` if the UI can't keep up.
            if frame_count % args.render_every == 0:
                bot = policy._cores[0].bot
                snap = FrameSnapshot.from_bot(bot, obs[-1])
                try:
                    render(snap)
                    root.update()
                except tk.TclError:
                    # Window was closed by the user mid-step.
                    shutdown["flag"] = True
                    break
    finally:
        elapsed = max(1e-6, time.monotonic() - (deadline - args.duration))
        fps = frame_count / elapsed if frame_count else 0
        log.info(
            "Session ended after %.1fs, %d frames processed (%.1f fps).",
            elapsed, frame_count, fps,
        )
        if frame_count:
            log.info("Action mix (top 5):")
            for idx, cnt in action_counts.most_common(5):
                log.info(
                    "  %-14s %5d  (%5.1f%%)",
                    BITWORLD_ACTION_NAMES[idx], cnt, 100.0 * cnt / frame_count,
                )
            avg_advance = frame_advance_total / frame_count
            log.info(
                "Frame advance: avg=%.2f  max=%d  skipped=%d (%d%% of server frames dropped)",
                avg_advance,
                frame_advance_max,
                frame_advance_skipped,
                int(100.0 * frame_advance_skipped / max(1, frame_advance_total)),
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

    return 0


if __name__ == "__main__":
    sys.exit(main())
