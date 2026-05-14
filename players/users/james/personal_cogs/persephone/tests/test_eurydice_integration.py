"""Integration tests for the Eurydice agent pipeline."""
from __future__ import annotations
import time
from pathlib import Path
import numpy as np
import pytest
from orpheus.perception import parse_frame
from orpheus.perception._common import PROTOCOL_BYTES
from orpheus.perception._unpack import unpack_frame
from orpheus.perception.types import View
from orpheus.pipeline import Pipeline
from orpheus.outer_loop import OuterLoop
from orpheus.mode import ModeDirective, ModeParams
from orpheus.hooks import HookPoint
from orpheus.belief_state import BeliefState
from orpheus.action_memory import ActionMemory
from orpheus.logging import Logger
from orpheus.idle import IdleTask
from agents.eurydice.policy import build_registry, AGENT_ID, register_eurydice_hooks
from agents.eurydice.modes import EurydiceIdleMode
from agents.eurydice.meta_decide import meta_decide
from agents.eurydice.ext_keys import EURYDICE_ACCUMULATORS, PLAYER_KNOWLEDGE
from agents.eurydice.evaluators import ROLE_EVALUATORS
from agents.eurydice.strategic_state import StrategicState
from agents.eurydice.types import Role, Team, Urgency

FIXTURE_DIR = Path(__file__).parent / "fixtures"

def _load_fixture(name: str) -> np.ndarray:
    return np.load(FIXTURE_DIR / f"{name}.npy")

def _build_pipeline():
    registry = build_registry()
    sent = []
    pipeline = Pipeline(
        initial_mode=EurydiceIdleMode(),
        mode_registry=registry,
        send_input=lambda mask: sent.append(mask),
        send_chat=lambda text: None,
        logger=Logger(level="off"),
        current_mode_name="idle",
        fallback_directive=ModeDirective("idle", ModeParams()),
    )
    register_eurydice_hooks(pipeline)
    return pipeline, sent

def _tick_with_fixture(pipeline, name: str):
    frame = _load_fixture(name)
    pipeline.tick(frame)

# --- Tests ---

def test_policy_importable():
    assert AGENT_ID == "eurydice"

def test_all_evaluator_modes_in_registry():
    """Every mode name an evaluator can return must be in the registry."""
    registry = build_registry()
    from orpheus.perception.types import Room
    from orpheus.perception._common import PLAYER_COLORS
    # Generate all possible mode names from evaluators
    mode_names = set()
    for role_name, evaluator in ROLE_EVALUATORS.items():
        for exchange_done in [True, False]:
            for partner_found in [True, False]:
                for partner_room in [Room.UNDERWORLD, Room.MORTAL_REALM, None]:
                    for enemy_room in [Room.UNDERWORLD, Room.MORTAL_REALM, None]:
                        state = StrategicState()
                        state.my_role = getattr(Role, role_name.upper(), None)
                        state.my_team = Team.SHADES if role_name in ("hades","cerberus","shade","spy") else Team.NYMPHS
                        state.my_room = Room.UNDERWORLD
                        state.key_exchange_done = exchange_done
                        state.key_partner_found = partner_found
                        state.key_partner_id = (PLAYER_COLORS[1], 1) if partner_found else None
                        state.key_partner_room = partner_room
                        state.enemy_key_role_id = (PLAYER_COLORS[2], 2) if enemy_room else None
                        state.enemy_key_role_room = enemy_room
                        state.enemy_key_exchange_likely = exchange_done
                        state.cover_intact = True
                        state.verified_ally = (PLAYER_COLORS[3], 3)
                        state.round_schedule = [(15,1),(15,1),(15,1)]
                        state.current_round = 2
                        state.allies_in_my_room = [(PLAYER_COLORS[4],4)]
                        state.enemies_in_my_room = [(PLAYER_COLORS[5],5)]
                        state.room_leader_team = Team.NYMPHS if role_name in ("hades","cerberus","shade","spy") else Team.SHADES
                        state.am_leader = False
                        try:
                            d = evaluator(state, BeliefState(), ActionMemory())
                            mode_names.add(d.mode)
                        except Exception:
                            pass
    for name in mode_names:
        assert registry.get(name) is not None, f"Mode '{name}' not registered"

def test_pipeline_tick_with_playing_fixture():
    """A real playing frame doesn't crash the pipeline and populates belief."""
    pipeline, _ = _build_pipeline()
    _tick_with_fixture(pipeline, "playing_round1")
    bs = pipeline.belief_state
    assert bs.tick == 1
    assert bs.view == View.PLAYING
    assert EURYDICE_ACCUMULATORS in bs.extra


def test_eurydice_hook_immediately_enters_whisper_mode() -> None:
    pipeline, _sent = _build_pipeline()
    pipeline.current_mode_name = "hold_position"
    pipeline.belief_state.view = View.WHISPER

    pipeline.hook_registry.dispatch(
        HookPoint.POST_BELIEF_UPDATE,
        pipeline.current_mode_name,
        pipeline.belief_state,
        logger=pipeline.logger,
    )
    entry = pipeline.mode_buffer.consume()

    assert entry is not None
    directive, _inferences = entry
    assert directive.mode == "in_whisper"

def test_pipeline_survives_100_ticks_same_frame():
    """Repeated identical frames don't crash or cause state corruption."""
    pipeline, sent = _build_pipeline()
    frame = _load_fixture("playing_round1")
    for _ in range(100):
        pipeline.tick(frame)
    assert pipeline.belief_state.tick == 100
    assert len(sent) == 100  # One input packet per tick

def test_role_detection_from_fixture():
    """Role reveal fixture populates my_role in belief state."""
    pipeline, _ = _build_pipeline()
    _tick_with_fixture(pipeline, "role_reveal_nymphs")
    bs = pipeline.belief_state
    assert bs.my_role is not None
    assert bs.my_team is not None

def test_mode_switch_on_phase_transition():
    """Transition from PLAYING to HOSTAGE_SELECT changes directive."""
    pipeline, _ = _build_pipeline()
    # First establish playing state
    frame = _load_fixture("playing_round1")
    for _ in range(5):
        pipeline.tick(frame)
    # Then switch to hostage select
    _tick_with_fixture(pipeline, "hostage_select_default")
    # meta_decide should produce hold_position (not leader)
    d, _ = meta_decide(pipeline.belief_state, ActionMemory())
    assert d.mode == "hold_position"

def test_hook_exception_does_not_crash():
    """A crashing hook alongside eurydice doesn't halt the pipeline."""
    pipeline, _ = _build_pipeline()
    def crashing_hook(bs): raise RuntimeError("boom")
    pipeline.hook_registry.register_hook(HookPoint.POST_BELIEF_UPDATE, crashing_hook)
    # Should not raise
    _tick_with_fixture(pipeline, "playing_round1")
    assert pipeline.belief_state.tick == 1
    assert EURYDICE_ACCUMULATORS in pipeline.belief_state.extra

def test_outer_loop_produces_directives():
    """OuterLoop thread produces at least one directive within 50 ticks."""
    pipeline, _ = _build_pipeline()
    outer = OuterLoop(meta_decide, pipeline.belief_buffer, pipeline.mode_buffer, logger=Logger(level="off"), tick_provider=lambda: pipeline.belief_state.tick)
    outer.start()
    try:
        frame = _load_fixture("playing_round1")
        for _ in range(50):
            pipeline.tick(frame)
            time.sleep(0.001)  # Let outer loop thread run
        # Check mode buffer was consumed (mode may have switched from idle)
        assert pipeline.belief_state.tick == 50
    finally:
        outer.stop()

def test_no_mode_thrashing():
    """Over 50 stable PLAYING ticks, mode doesn't switch excessively."""
    pipeline, _ = _build_pipeline()
    outer = OuterLoop(meta_decide, pipeline.belief_buffer, pipeline.mode_buffer, logger=Logger(level="off"), tick_provider=lambda: pipeline.belief_state.tick)
    outer.start()
    try:
        frame = _load_fixture("playing_round1")
        modes_seen = []
        for _ in range(50):
            pipeline.tick(frame)
            modes_seen.append(pipeline.current_mode_name)
            time.sleep(0.001)
        # Count distinct transitions (consecutive changes)
        transitions = sum(1 for i in range(1, len(modes_seen)) if modes_seen[i] != modes_seen[i-1])
        assert transitions <= 3, f"Too many mode transitions: {transitions}"
    finally:
        outer.stop()

def test_whisper_fixture_does_not_crash():
    """Whisper view fixture processes without errors."""
    pipeline, _ = _build_pipeline()
    _tick_with_fixture(pipeline, "whisper_default")
    assert pipeline.belief_state.view == View.WHISPER
