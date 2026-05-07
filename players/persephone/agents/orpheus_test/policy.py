#!/usr/bin/env python3
"""Orpheus test-agent policy entry point.

Contract:
    python agents/orpheus_test/policy.py --url URL --name NAME
"""

from __future__ import annotations

import argparse
import signal
import struct
import sys
import threading
import traceback
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import websocket

_AGENT_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _AGENT_DIR.parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from agents.orpheus_test.meta_decide import meta_decide  # noqa: E402
from agents.orpheus_test.modes import (  # noqa: E402
    ApproachNearestPlayerMode,
    IdleMode,
    WanderMode,
)
from orpheus.logging import Logger  # noqa: E402
from orpheus.mode import ModeDirective, ModeParams, ModeRegistry  # noqa: E402
from orpheus.outer_loop import OuterLoop  # noqa: E402
from orpheus.perception._common import PROTOCOL_BYTES  # noqa: E402
from orpheus.perception._unpack import unpack_frame  # noqa: E402
from orpheus.pipeline import Pipeline  # noqa: E402


AGENT_ID = "orpheus_test"
DESCRIPTION = "Minimal Orpheus test agent that idles, wanders, and approaches known players"


def run(*, url: str, name: str, log_level: str = "events") -> int:
    """Connect to a Persephone server and run the Orpheus two-loop agent."""
    stop_event = threading.Event()
    ws: websocket.WebSocket | None = None
    outer_loop: OuterLoop | None = None

    def request_stop(signum: int, _frame: object) -> None:
        del signum
        stop_event.set()

    old_sigint = signal.signal(signal.SIGINT, request_stop)
    old_sigterm = signal.signal(signal.SIGTERM, request_stop)

    try:
        logger = Logger(level=log_level, sink=sys.stdout.write)
        def send_input(mask: int) -> None:
            assert ws is not None
            ws.send(struct.pack("BB", 0x00, mask & 0xFF), opcode=0x2)

        def send_chat(text: str) -> None:
            assert ws is not None
            payload = b"\x01" + text.encode("ascii", errors="replace")
            ws.send(payload, opcode=0x2)

        registry = _build_registry()
        pipeline = Pipeline(
            initial_mode=IdleMode(),
            mode_registry=registry,
            send_input=send_input,
            send_chat=send_chat,
            logger=logger,
            current_mode_name="idle",
            fallback_directive=ModeDirective("idle", ModeParams()),
        )

        outer_loop = OuterLoop(
            meta_decide,
            pipeline.belief_buffer,
            pipeline.mode_buffer,
            logger=logger,
        )
        outer_loop.start()

        ws = websocket.create_connection(_url_with_name(url, name), timeout=1.0)

        while not stop_event.is_set():
            try:
                data = ws.recv()
            except websocket.WebSocketTimeoutException:
                continue
            except (
                websocket.WebSocketConnectionClosedException,
                ConnectionError,
                OSError,
            ):
                break

            if not isinstance(data, bytes) or len(data) != PROTOCOL_BYTES:
                continue

            frame = unpack_frame(data)
            pipeline.tick(frame)

        return 0
    except KeyboardInterrupt:
        stop_event.set()
        return 0
    except Exception:
        traceback.print_exc()
        return 1
    finally:
        if outer_loop is not None:
            outer_loop.stop()
        if ws is not None:
            try:
                ws.close()
            except Exception:
                pass
        signal.signal(signal.SIGINT, old_sigint)
        signal.signal(signal.SIGTERM, old_sigterm)


def _build_registry() -> ModeRegistry:
    registry = ModeRegistry()
    registry.register("idle", IdleMode)
    registry.register("wander", WanderMode)
    registry.register("approach_nearest", ApproachNearestPlayerMode)
    return registry


def _url_with_name(url: str, name: str) -> str:
    parts = urlsplit(url)
    query = parse_qsl(parts.query, keep_blank_values=True)
    if not any(key == "name" for key, _ in query):
        query.append(("name", name))
    return urlunsplit(
        (
            parts.scheme,
            parts.netloc,
            parts.path,
            urlencode(query),
            parts.fragment,
        )
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run the Orpheus test agent against a Persephone server.",
    )
    parser.add_argument("--url", required=True, help="Server WebSocket URL")
    parser.add_argument("--name", required=True, help="Player name")
    parser.add_argument(
        "--log-level",
        default="events",
        choices=("off", "events", "decisions", "verbose"),
        help="Orpheus JSONL log level (default: events)",
    )
    args = parser.parse_args()
    return run(url=args.url, name=args.name, log_level=args.log_level)


if __name__ == "__main__":
    sys.exit(main())
