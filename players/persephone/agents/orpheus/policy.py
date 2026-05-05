#!/usr/bin/env python3
"""Orpheus agent policy -- LLM-driven dual-loop architecture.

Connects to a Persephone server and plays using a two-loop design:
  - Fast loop (24 FPS): perceive -> update belief -> act (per task)
  - Slow loop (async): belief snapshot -> LLM -> set task

The fast loop runs on the main thread, processing frames as they arrive.
The slow LLM loop runs on a background thread, periodically querying the
LLM to update the active task.

Contract:
    python agents/orpheus/policy.py --url URL --name NAME

Can also be launched via the universal runner:
    python run_agents.py orpheus
"""

from __future__ import annotations

import argparse
import logging
import os
import signal
import sys
import threading
import time
from pathlib import Path

# ---------------------------------------------------------------------------
# Path setup for standalone execution.
# When run as a script (python agents/orpheus/policy.py), relative imports
# don't work. We add the agent directory and project root to sys.path so
# both `perception` and sibling modules are importable.
# ---------------------------------------------------------------------------

_AGENT_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _AGENT_DIR.parent.parent

if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))
if str(_AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(_AGENT_DIR))

import websocket  # noqa: E402

from perception import parse_frame  # noqa: E402
from perception.types import View  # noqa: E402

from belief import BeliefState, GamePhase  # noqa: E402
from llm import LLMError, LLMProvider, create_provider, make_decision  # noqa: E402
from tasks import FrameAction, TaskController, TaskParams, TaskType  # noqa: E402
from trace import TraceWriter  # noqa: E402

# ---------------------------------------------------------------------------
# Agent metadata (read by run_agents.py --list)
# ---------------------------------------------------------------------------

AGENT_ID = "orpheus"
DESCRIPTION = "LLM-driven dual-loop agent: fast reactive loop + slow strategic LLM loop"

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# How often the slow loop queries the LLM (seconds).
# The LLM is only called this often at most; actual interval includes
# LLM latency on top.
LLM_POLL_INTERVAL = float(os.environ.get("ORPHEUS_LLM_INTERVAL", "2.0"))

# Minimum frames between LLM decisions (prevents thrashing if LLM is fast)
MIN_FRAMES_BETWEEN_DECISIONS = 24  # ~1 second at 24 FPS

# Protocol constants
FRAME_SIZE = 8192  # Expected frame size in bytes

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("orpheus")


# ---------------------------------------------------------------------------
# Slow loop (LLM thread)
# ---------------------------------------------------------------------------


class SlowLoop:
    """Background thread that queries the LLM for task decisions.

    Reads belief state snapshots, calls the LLM, and updates the
    task controller. Runs at a configurable interval independent
    of the frame rate.
    """

    def __init__(
        self,
        provider: LLMProvider,
        belief: BeliefState,
        controller: TaskController,
        poll_interval: float = LLM_POLL_INTERVAL,
        tracer: TraceWriter | None = None,
    ) -> None:
        self._provider = provider
        self._belief = belief
        self._controller = controller
        self._poll_interval = poll_interval
        self._tracer = tracer
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._decision_count = 0
        self._last_decision_tick = 0

    def start(self) -> None:
        """Start the background LLM thread."""
        self._thread = threading.Thread(
            target=self._run,
            name="orpheus-llm-loop",
            daemon=True,
        )
        self._thread.start()
        logger.info(
            "Slow loop started (provider=%s, interval=%.1fs)",
            self._provider.provider_name,
            self._poll_interval,
        )

    def stop(self) -> None:
        """Signal the background thread to stop."""
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=5)

    def _run(self) -> None:
        """Main loop for the LLM thread."""
        # Wait for the game to start (skip lobby/role reveal)
        while not self._stop_event.is_set():
            snapshot = self._belief.snapshot()
            if snapshot.phase in (GamePhase.PLAYING, GamePhase.HOSTAGE_SELECT):
                break
            self._stop_event.wait(0.5)

        logger.info("Slow loop: game started, beginning LLM decisions")

        while not self._stop_event.is_set():
            try:
                self._decide_once()
            except Exception:
                logger.exception("Slow loop: unexpected error in decision cycle")

            # Wait before next decision
            self._stop_event.wait(self._poll_interval)

    def _decide_once(self) -> None:
        """Execute one decision cycle."""
        snapshot = self._belief.snapshot()

        # Don't make decisions during non-gameplay phases
        if snapshot.phase in (GamePhase.LOBBY, GamePhase.ROLE_REVEAL, GamePhase.GAME_OVER):
            return

        # Throttle: don't decide too frequently
        frames_since_last = snapshot.tick_count - self._last_decision_tick
        if frames_since_last < MIN_FRAMES_BETWEEN_DECISIONS:
            return

        # Query the LLM
        decision = make_decision(self._provider, snapshot)
        self._decision_count += 1
        self._last_decision_tick = snapshot.tick_count

        logger.info(
            "LLM decision #%d: %s (%.0fms) -- %s",
            self._decision_count,
            decision.task.type.value,
            decision.latency_ms,
            decision.reasoning[:80] if decision.reasoning else "(no reasoning)",
        )

        # Trace the decision
        if self._tracer:
            prev_type = self._controller.active_type
            self._tracer.decision(
                tick=snapshot.tick_count,
                decision_num=self._decision_count,
                task=decision.task.type.value,
                params={
                    k: v for k, v in {
                        "target_x": decision.task.target_x,
                        "target_y": decision.task.target_y,
                        "target_color": decision.task.target_color,
                        "message": decision.task.message,
                    }.items() if v is not None
                },
                reasoning=decision.reasoning,
                latency_ms=decision.latency_ms,
                context_summary=(
                    f"R{snapshot.current_round or '?'} "
                    f"{snapshot.timer_secs or '?'}s, "
                    f"{snapshot.phase.value}, "
                    f"{len(snapshot.minimap_dots)} dots"
                ),
                prev_task=prev_type.value,
                prev_task_duration_ticks=snapshot.tick_count - self._last_decision_tick + frames_since_last,
            )

        # Apply the decision
        self._controller.set_task(decision.task)


# ---------------------------------------------------------------------------
# Fast loop (main thread)
# ---------------------------------------------------------------------------


class FastLoop:
    """Main frame-processing loop.

    Runs on the main thread. For each frame received via WebSocket:
    1. Parse the frame (perception)
    2. Update the belief state
    3. Query the task controller for this frame's action
    4. Send the action to the server
    """

    def __init__(
        self,
        ws: websocket.WebSocket,
        belief: BeliefState,
        controller: TaskController,
        tracer: TraceWriter | None = None,
    ) -> None:
        self._ws = ws
        self._belief = belief
        self._controller = controller
        self._tracer = tracer
        self._frame_count = 0
        self._stop = False

    def run(self) -> None:
        """Run the fast loop until disconnected or stopped."""
        logger.info("Fast loop started")

        while not self._stop:
            try:
                data = self._ws.recv()
            except websocket.WebSocketConnectionClosedException:
                logger.info("Server disconnected")
                break
            except websocket.WebSocketTimeoutException:
                continue
            except Exception:
                logger.exception("WebSocket recv error")
                break

            # Validate frame
            if not isinstance(data, bytes) or len(data) != FRAME_SIZE:
                continue

            self._frame_count += 1
            if self._tracer:
                self._tracer.increment_frames()

            # 1. Perceive
            perception = parse_frame(data, room_size=self._belief.room_size)

            # 2. Update belief
            self._belief.update(perception)

            # 3. Act (task produces frame action)
            action = self._controller.tick(perception, self._belief)

            # 4. Send
            self._send_action(action)

    def stop(self) -> None:
        """Signal the fast loop to stop after the current frame."""
        self._stop = True

    def _send_action(self, action: FrameAction) -> None:
        """Send the frame action to the server."""
        try:
            # Always send button packet
            self._ws.send(action.to_button_packet(), opcode=0x2)

            # Send chat if present
            chat_packet = action.to_chat_packet()
            if chat_packet:
                self._ws.send(chat_packet, opcode=0x2)
        except Exception:
            logger.exception("Failed to send action")


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


def run(
    *,
    url: str,
    name: str,
    provider: str = "stub",
    model: str | None = None,
    llm_interval: float = LLM_POLL_INTERVAL,
    trace_dir: str | None = None,
    trace_level: str | None = None,
) -> int:
    """Connect to the server and play until disconnected or interrupted.

    Args:
        url: WebSocket URL (e.g., ws://localhost:2500/player).
        name: Player name to use when connecting.
        provider: LLM provider name ("anthropic", "openai", "bedrock", "stub").
        model: Model identifier (uses provider default if None).
        llm_interval: Seconds between LLM decision calls.
        trace_dir: Trace output directory (None = use env var or disabled).
        trace_level: Trace level override (None = use env var or "full").

    Returns:
        Exit code (0 = clean, 1 = error).
    """
    # Create LLM provider
    try:
        llm_provider = create_provider(provider, model)
    except LLMError as e:
        logger.error("Failed to create LLM provider: %s", e)
        return 1

    # Create tracer (None if disabled)
    tracer = TraceWriter.from_env(trace_dir=trace_dir, trace_level=trace_level)
    if tracer:
        tracer.set_config({
            "provider": provider,
            "model": model or "(default)",
            "llm_interval": llm_interval,
            "trace_level": trace_level or os.environ.get("ORPHEUS_TRACE_LEVEL", "full"),
        })

    logger.info("Orpheus agent starting (provider=%s)", llm_provider.provider_name)

    # Connect to server
    ws_url = f"{url}?name={name}" if "?" not in url else f"{url}&name={name}"
    logger.info("Connecting to %s", ws_url)

    try:
        ws = websocket.WebSocket()
        ws.connect(ws_url)
    except Exception as e:
        logger.error("Failed to connect: %s", e)
        if tracer:
            tracer.set_ended_reason("connection_failed")
            tracer.close()
        return 1

    logger.info("Connected as '%s'", name)

    # Emit session_start event
    if tracer:
        tracer.event("session_start", {
            "name": name,
            "url": url,
            "provider": provider,
            "model": model or "(default)",
            "llm_interval": llm_interval,
        }, tick=0)

    # Initialize components
    belief = BeliefState()
    if tracer:
        belief.set_tracer(tracer)
    controller = TaskController(llm_provider=llm_provider, tracer=tracer)
    slow_loop = SlowLoop(
        llm_provider, belief, controller,
        poll_interval=llm_interval, tracer=tracer,
    )
    fast_loop = FastLoop(ws, belief, controller, tracer=tracer)

    # Handle signals for graceful shutdown
    def shutdown(signum: int = 0, _frame: object = None) -> None:
        logger.info("Shutting down (signal %d)", signum)
        fast_loop.stop()
        slow_loop.stop()

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    # Start loops
    slow_loop.start()

    try:
        fast_loop.run()
    except KeyboardInterrupt:
        pass
    finally:
        slow_loop.stop()
        try:
            ws.close()
        except Exception:
            pass
        logger.info(
            "Orpheus agent stopped (frames=%d, decisions=%d)",
            fast_loop._frame_count,
            slow_loop._decision_count,
        )
        # Close tracer (writes manifest)
        if tracer:
            tracer.event("session_end", {
                "reason": "shutdown",
                "total_frames": fast_loop._frame_count,
                "total_decisions": slow_loop._decision_count,
            }, tick=belief.tick_count)
            tracer.set_ended_reason("shutdown")
            tracer.close()

    return 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> int:
    p = argparse.ArgumentParser(
        description="Run the Orpheus agent against a Persephone server.",
    )
    p.add_argument("--url", required=True, help="Server WebSocket URL")
    p.add_argument("--name", required=True, help="Player name")
    p.add_argument(
        "--provider",
        default=os.environ.get("ORPHEUS_LLM_PROVIDER", "stub"),
        help="LLM provider: anthropic, openai, bedrock, stub (default: stub)",
    )
    p.add_argument(
        "--model",
        default=os.environ.get("ORPHEUS_LLM_MODEL"),
        help="LLM model identifier (uses provider default if not set)",
    )
    p.add_argument(
        "--llm-interval",
        type=float,
        default=LLM_POLL_INTERVAL,
        help=f"Seconds between LLM decisions (default: {LLM_POLL_INTERVAL})",
    )
    p.add_argument(
        "--trace-dir",
        default=None,
        help="Trace output directory (overrides ORPHEUS_TRACE_DIR)",
    )
    p.add_argument(
        "--trace-level",
        default=None,
        choices=["events", "decisions", "full"],
        help="Trace level (overrides ORPHEUS_TRACE_LEVEL, default: full)",
    )

    args = p.parse_args()

    return run(
        url=args.url,
        name=args.name,
        provider=args.provider,
        model=args.model,
        llm_interval=args.llm_interval,
        trace_dir=args.trace_dir,
        trace_level=args.trace_level,
    )


if __name__ == "__main__":
    sys.exit(main())
