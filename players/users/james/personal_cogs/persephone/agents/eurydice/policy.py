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
from datetime import datetime  # noqa: E402
from pathlib import Path  # noqa: E402
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit  # noqa: E402
import websocket  # noqa: E402

from agents.eurydice.frame_recorder import FrameRecorder
from agents.eurydice.log import set_logger
from agents.eurydice.meta_decide import meta_decide
from agents.eurydice.advanced_modes import (
    AnnounceIdentityMode,
    CheckInfoScreenMode,
    CoordinateCrossRoomMode,
    DecoyMode,
    HoldPositionMode,
    HostageSelectMode,
    RelayIntelligenceMode,
    ReviewGlobalChatMode,
    SeekLeadershipMode,
    SummitInteractMode,
    TimeWasteMode,
    UsurpMode,
)
from agents.eurydice.modes import EurydiceIdleMode, ScoutMode, ProbeTargetMode, ProbeSystematicMode
from agents.eurydice.llm_action_mode import LLMActionMode
from agents.eurydice.whisper_mode import InWhisperMode, InWhisperParams
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


class _ConnectionClosed(Exception):
    """Raised when the game server closes while the policy is sending."""


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
    registry.register("review_global_chat", ReviewGlobalChatMode)
    registry.register("announce_identity", AnnounceIdentityMode)
    registry.register("decoy", DecoyMode)
    registry.register("usurp", UsurpMode)
    registry.register("check_info_screen", CheckInfoScreenMode)
    registry.register("llm_action", LLMActionMode)
    return registry


def register_eurydice_hooks(
    pipeline: Pipeline,
    *,
    llm_control: str = "off",
    llm_provider: str = "hold",
) -> None:
    """Register Eurydice hooks, including view-critical local overrides."""

    def post_belief_update(belief_state):
        eurydice_post_belief_update(belief_state)
        _push_immediate_whisper_directive(
            pipeline,
            llm_control=llm_control,
            llm_provider=llm_provider,
        )

    pipeline.hook_registry.register_hook(
        HookPoint.POST_BELIEF_UPDATE,
        post_belief_update,
    )


def _push_immediate_whisper_directive(
    pipeline: Pipeline,
    *,
    llm_control: str,
    llm_provider: str,
) -> None:
    belief_state = pipeline.belief_state
    if belief_state.view is not View.WHISPER:
        return
    if pipeline.current_mode_name == "in_whisper":
        return
    pipeline.mode_buffer.push(
        ModeDirective(
            "in_whisper",
            InWhisperParams(
                llm_control=llm_control,
                llm_provider=llm_provider,
            ),
        ),
        dict(getattr(belief_state, "inferences", {})),
    )

def run(
    *,
    url: str,
    name: str,
    log_level: str = "events",
    record_frames: str | None = None,
    llm_control: str = "off",
    llm_provider: str = "hold",
) -> int:
    stop_event = threading.Event()
    ws = None
    outer_loop = None
    recorder = None
    old_sigint = signal.signal(signal.SIGINT, lambda *_: stop_event.set())
    old_sigterm = signal.signal(signal.SIGTERM, lambda *_: stop_event.set())
    try:
        logger = Logger(level=log_level, sink=sys.stdout.write)
        set_logger(logger)
        if record_frames is not None:
            recorder = FrameRecorder(_frame_recording_path(record_frames, name))
        def send_input(mask):
            assert ws is not None
            try:
                ws.send(struct.pack("BB", 0x00, mask & 0xFF), opcode=0x2)
            except (
                websocket.WebSocketConnectionClosedException,
                BrokenPipeError,
                ConnectionError,
                OSError,
            ) as exc:
                stop_event.set()
                raise _ConnectionClosed() from exc
        def send_chat(text):
            assert ws is not None
            try:
                ws.send(b"\x01" + text.encode("ascii", errors="replace"), opcode=0x2)
            except (
                websocket.WebSocketConnectionClosedException,
                BrokenPipeError,
                ConnectionError,
                OSError,
            ) as exc:
                stop_event.set()
                raise _ConnectionClosed() from exc

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
        register_eurydice_hooks(
            pipeline,
            llm_control=llm_control,
            llm_provider=llm_provider,
        )

        def decide_with_optional_llm(belief_state, action_memory):
            return meta_decide(
                belief_state,
                action_memory,
                llm_control=llm_control,
                llm_provider=llm_provider,
            )

        outer_loop = OuterLoop(decide_with_optional_llm, pipeline.belief_buffer, pipeline.mode_buffer, logger=logger, tick_provider=lambda: pipeline.belief_state.tick)
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
            if recorder is not None:
                recorder.record(pipeline.belief_state.tick + 1, data)
            pipeline.tick(unpack_frame(data))
        return 0
    except KeyboardInterrupt:
        return 0
    except _ConnectionClosed:
        return 0
    except Exception:
        traceback.print_exc()
        return 1
    finally:
        if outer_loop: outer_loop.stop()
        if recorder:
            recorder.close()
        set_logger(None)
        if ws:
            try: ws.close()
            except Exception: pass
        signal.signal(signal.SIGINT, old_sigint)
        signal.signal(signal.SIGTERM, old_sigterm)

def _frame_recording_path(directory: str, name: str) -> Path:
    safe_name = "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in name)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return Path(directory) / f"{safe_name}_{timestamp}.frames"

def main() -> int:
    parser = argparse.ArgumentParser(description="Run Eurydice agent")
    parser.add_argument("--url", required=True)
    parser.add_argument("--name", required=True)
    parser.add_argument("--log-level", default="events", choices=("off","events","decisions","verbose"))
    parser.add_argument("--record-frames", metavar="DIR", default=None)
    parser.add_argument("--llm-control", default="off", choices=("off", "shadow", "targets", "whispers", "all"))
    parser.add_argument(
        "--llm-provider",
        default="hold",
        choices=("hold", "heuristic", "haiku", "bedrock-haiku", "bedrock"),
    )
    args = parser.parse_args()
    return run(
        url=args.url,
        name=args.name,
        log_level=args.log_level,
        record_frames=args.record_frames,
        llm_control=args.llm_control,
        llm_provider=args.llm_provider,
    )

if __name__ == "__main__":
    sys.exit(main())
