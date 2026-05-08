#!/usr/bin/env python3
"""Eurydice agent policy entry point."""
from __future__ import annotations

# CRITICAL: Remove the script's own directory from sys.path BEFORE any
# stdlib import that could trigger the types.py shadow (our local types.py
# conflicts with stdlib types module via enum -> types import chain).
# Only sys and os.path are safe here (built-in C modules).
import os
import sys

_AGENT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path[:] = [p for p in sys.path if os.path.abspath(p) != _AGENT_DIR]

_PROJECT_ROOT = os.path.dirname(os.path.dirname(_AGENT_DIR))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

import argparse, signal, struct, threading, traceback  # noqa: E402
from pathlib import Path  # noqa: E402
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit  # noqa: E402
import websocket  # noqa: E402

from agents.eurydice.meta_decide import meta_decide
from agents.eurydice.advanced_modes import (
    CheckInfoScreenMode,
    CoordinateCrossRoomMode,
    DecoyMode,
    HoldPositionMode,
    HostageSelectMode,
    RelayIntelligenceMode,
    SeekLeadershipMode,
    SummitInteractMode,
    TimeWasteMode,
    UsurpMode,
)
from agents.eurydice.modes import EurydiceIdleMode, ScoutMode, ProbeTargetMode, ProbeSystematicMode
from agents.eurydice.whisper_mode import InWhisperMode
from agents.eurydice.pipeline import eurydice_post_belief_update
from orpheus.hooks import HookPoint
from orpheus.idle import IdleMode
from orpheus.logging import Logger
from orpheus.mode import Mode, ModeDirective, ModeParams, ModeRegistry
from orpheus.outer_loop import OuterLoop
from orpheus.perception._common import PROTOCOL_BYTES
from orpheus.perception._unpack import unpack_frame
from orpheus.pipeline import Pipeline
from orpheus.task import Task, ActCommand
from orpheus.types import View

AGENT_ID = "eurydice"
DESCRIPTION = "Rule-based strategic agent for all roles (Orpheus framework)"

# Stub mode for unimplemented modes -- returns IdleTask every tick
class _StubMode(Mode):
    params_type = ModeParams
    def select_task(self, belief_state, action_memory) -> Task | None:
        from orpheus.idle import IdleTask
        return IdleTask()
    def mode_enter(self, belief_state, action_memory) -> None: pass
    def mode_switch_cleanup(self, belief_state, action_memory, new_mode_directive) -> None: pass

def build_registry() -> ModeRegistry:
    """Build ModeRegistry with all Eurydice modes (implemented + stubs)."""
    registry = ModeRegistry()
    # Implemented modes
    registry.register("idle", EurydiceIdleMode)
    registry.register("scout", ScoutMode)
    registry.register("probe_target", ProbeTargetMode)
    registry.register("probe_systematic", ProbeSystematicMode)
    registry.register("in_whisper", InWhisperMode)
    registry.register("hold_position", HoldPositionMode)
    registry.register("coordinate_cross_room", CoordinateCrossRoomMode)
    registry.register("seek_leadership", SeekLeadershipMode)
    registry.register("hostage_select", HostageSelectMode)
    registry.register("summit_interact", SummitInteractMode)
    registry.register("time_waste", TimeWasteMode)
    registry.register("relay_intelligence", RelayIntelligenceMode)
    registry.register("decoy", DecoyMode)
    registry.register("usurp", UsurpMode)
    registry.register("check_info_screen", CheckInfoScreenMode)
    return registry

def run(*, url: str, name: str, log_level: str = "events") -> int:
    stop_event = threading.Event()
    ws = None
    outer_loop = None
    old_sigint = signal.signal(signal.SIGINT, lambda *_: stop_event.set())
    old_sigterm = signal.signal(signal.SIGTERM, lambda *_: stop_event.set())
    try:
        logger = Logger(level=log_level, sink=sys.stdout.write)
        def send_input(mask):
            assert ws is not None
            ws.send(struct.pack("BB", 0x00, mask & 0xFF), opcode=0x2)
        def send_chat(text):
            assert ws is not None
            ws.send(b"\x01" + text.encode("ascii", errors="replace"), opcode=0x2)

        registry = build_registry()
        pipeline = Pipeline(
            initial_mode=EurydiceIdleMode(),
            mode_registry=registry,
            send_input=send_input,
            send_chat=send_chat,
            logger=logger,
            current_mode_name="idle",
            fallback_directive=ModeDirective("idle", ModeParams()),
        )
        pipeline.hook_registry.register_hook(HookPoint.POST_BELIEF_UPDATE, eurydice_post_belief_update)

        outer_loop = OuterLoop(meta_decide, pipeline.belief_buffer, pipeline.mode_buffer, logger=logger, tick_provider=lambda: pipeline.belief_state.tick)
        outer_loop.start()

        parts = urlsplit(url)
        query = parse_qsl(parts.query, keep_blank_values=True)
        if not any(k == "name" for k, _ in query):
            query.append(("name", name))
        full_url = urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))
        ws = websocket.create_connection(full_url, timeout=1.0)

        while not stop_event.is_set():
            try:
                data = ws.recv()
            except websocket.WebSocketTimeoutException:
                continue
            except (websocket.WebSocketConnectionClosedException, ConnectionError, OSError):
                break
            if not isinstance(data, bytes) or len(data) != PROTOCOL_BYTES:
                continue
            pipeline.tick(unpack_frame(data))
        return 0
    except KeyboardInterrupt:
        return 0
    except Exception:
        traceback.print_exc()
        return 1
    finally:
        if outer_loop: outer_loop.stop()
        if ws:
            try: ws.close()
            except Exception: pass
        signal.signal(signal.SIGINT, old_sigint)
        signal.signal(signal.SIGTERM, old_sigterm)

def main() -> int:
    parser = argparse.ArgumentParser(description="Run Eurydice agent")
    parser.add_argument("--url", required=True)
    parser.add_argument("--name", required=True)
    parser.add_argument("--log-level", default="events", choices=("off","events","decisions","verbose"))
    args = parser.parse_args()
    return run(url=args.url, name=args.name, log_level=args.log_level)

if __name__ == "__main__":
    sys.exit(main())
