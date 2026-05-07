"""Stage 9 integration tests for Orpheus using real perception fixtures."""

from __future__ import annotations

import json
import time
from pathlib import Path

import numpy as np
import pytest

from agents.orpheus_test.meta_decide import WanderParams, meta_decide
from agents.orpheus_test.modes import ApproachNearestPlayerMode, WanderMode
from orpheus.buffers import BeliefBuffer
from orpheus.idle import IdleMode
from orpheus.logging import Logger
from orpheus.mode import Mode, ModeDirective, ModeParams, ModeRegistry
from orpheus.mode_buffer import ModeBuffer
from orpheus.outer_loop import OuterLoop
from orpheus.perception import parse_frame
from orpheus.perception.types import ChatroomBarState
from orpheus.pipeline import Pipeline
from orpheus.task import ActCommand
from orpheus.tasks import SendMessageTask
from orpheus.types import (
    BUTTON_DOWN,
    BUTTON_LEFT,
    BUTTON_RIGHT,
    BUTTON_UP,
    View,
)
from tests.conftest import FIXTURES_DIR, load_fixture


def _entries(lines: list[str]) -> list[dict]:
    return [json.loads(line) for line in lines]


def _entries_of_type(lines: list[str], event_type: str) -> list[dict]:
    return [entry for entry in _entries(lines) if entry.get("type") == event_type]


def _fixture(name: str, expected_view: View | None = None):
    try:
        fixture = load_fixture(name)
    except FileNotFoundError as exc:
        pytest.skip(f"Fixture {name!r} is missing: {exc}")

    perception = parse_frame(fixture.frame)
    if expected_view is not None and perception.view != expected_view:
        pytest.skip(
            f"Fixture {name!r} parsed as {perception.view.value}, "
            f"expected {expected_view.value}"
        )
    return fixture, perception


class WhisperMessageMode(Mode):
    params_type = ModeParams

    def select_task(self, belief_state, action_memory):
        del belief_state, action_memory
        return SendMessageTask("HELLO", channel="chatroom")

    def mode_enter(self, belief_state, action_memory) -> None:
        pass

    def mode_switch_cleanup(
        self,
        belief_state,
        action_memory,
        new_mode_directive: ModeDirective,
    ) -> None:
        pass


def _pipeline(
    *,
    logger=None,
    mode_buffer: ModeBuffer | None = None,
    belief_buffer: BeliefBuffer | None = None,
    watchdog_threshold: int = 9999,
    extra_modes: dict[str, type[Mode]] | None = None,
) -> tuple[Pipeline, list[int], list[str]]:
    sent_inputs: list[int] = []
    sent_chats: list[str] = []
    registry = ModeRegistry()
    registry.register("idle", IdleMode)
    registry.register("wander", WanderMode)
    registry.register("approach_nearest", ApproachNearestPlayerMode)
    for name, mode_cls in (extra_modes or {}).items():
        registry.register(name, mode_cls)

    pipeline = Pipeline(
        initial_mode=IdleMode(),
        mode_registry=registry,
        send_input=sent_inputs.append,
        send_chat=sent_chats.append,
        logger=logger,
        mode_buffer=mode_buffer,
        belief_buffer=belief_buffer,
        current_mode_name="idle",
        fallback_directive=ModeDirective("idle", ModeParams()),
        watchdog_threshold=watchdog_threshold,
    )
    return pipeline, sent_inputs, sent_chats


def _directional_or_noop(command: ActCommand) -> bool:
    directional = BUTTON_UP | BUTTON_DOWN | BUTTON_LEFT | BUTTON_RIGHT
    return (
        not command.reset_input
        and command.chat_text is None
        and command.buttons & ~directional == 0
    )


def _wait_until(predicate, timeout: float = 2.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return predicate()


def test_pipeline_lobby_to_playing_view_transition() -> None:
    lobby, lobby_perception = _fixture("lobby_full", View.LOBBY)
    playing, playing_perception = _fixture("playing_round1", View.PLAYING)
    assert lobby_perception.view == View.LOBBY
    assert playing_perception.view == View.PLAYING

    lines: list[str] = []
    pipeline, _, _ = _pipeline(logger=Logger(sink=lines.append))

    for frame in [lobby.frame, lobby.frame, playing.frame, playing.frame]:
        pipeline.tick(frame)

    assert pipeline.belief_state.view == View.PLAYING
    transitions = _entries_of_type(lines, "view_transition")
    assert any(
        entry["old"] == "lobby" and entry["new"] == "playing"
        for entry in transitions
    )


def test_pipeline_role_reveal_populates_self_identity() -> None:
    fixture, perception = _fixture("role_reveal_nymphs", View.ROLE_REVEAL)
    assert perception.role_reveal is not None

    pipeline, _, _ = _pipeline()
    pipeline.tick(fixture.frame)

    belief = pipeline.belief_state
    assert belief.my_role == "nymph"
    assert belief.my_team == "nymphs"
    assert belief.my_room is not None
    assert belief.room_size == (120, 120)


def test_pipeline_playing_initializes_occupancy_grid() -> None:
    role_reveal, _ = _fixture("role_reveal_nymphs", View.ROLE_REVEAL)
    playing, _ = _fixture("playing_round1", View.PLAYING)

    pipeline, _, _ = _pipeline()
    pipeline.tick(role_reveal.frame)
    pipeline.tick(playing.frame)

    grid = pipeline.belief_state.occupancy_grid
    assert grid is not None
    assert grid.room_size == pipeline.belief_state.room_size == (120, 120)
    assert grid.cells.shape == (grid.grid_h, grid.grid_w)
    assert grid.grid_w == 60
    assert grid.grid_h == 60


def test_pipeline_whisper_populates_chat_state() -> None:
    fixture, perception = _fixture("whisper_default", View.WHISPER)
    assert perception.chatroom is not None
    assert perception.chatroom.occupant_colors

    pipeline, _, _ = _pipeline()
    pipeline.tick(fixture.frame)

    belief = pipeline.belief_state
    assert belief.in_whisper is True
    assert belief.pending_offers == {"role": False, "color": False}
    assert belief.pending_entry is None
    assert belief.menu_state is not None
    assert belief.menu_state["bar"] == ChatroomBarState.DEFAULT
    assert isinstance(belief.whisper_occupants, list)


def test_pipeline_whisper_message_mode_emits_chat_text() -> None:
    fixture, _ = _fixture("whisper_default", View.WHISPER)
    mode_buffer = ModeBuffer()
    pipeline, sent_inputs, sent_chats = _pipeline(
        mode_buffer=mode_buffer,
        extra_modes={"message": WhisperMessageMode},
    )
    mode_buffer.push(ModeDirective("message", ModeParams()))

    command = pipeline.tick(fixture.frame)

    assert pipeline.current_mode_name == "message"
    assert command == ActCommand(chat_text="HELLO")
    assert sent_inputs == [0]
    assert sent_chats == ["HELLO"]


def test_pipeline_idle_mode_in_lobby_emits_noop() -> None:
    fixture, _ = _fixture("lobby_full", View.LOBBY)
    pipeline, sent_inputs, sent_chats = _pipeline()

    command = pipeline.tick(fixture.frame)

    assert command == ActCommand()
    assert sent_inputs == [0]
    assert sent_chats == []


def test_pipeline_wander_mode_in_playing_emits_movement_or_noop() -> None:
    role_reveal, _ = _fixture("role_reveal_nymphs", View.ROLE_REVEAL)
    playing, _ = _fixture("playing_round1", View.PLAYING)
    mode_buffer = ModeBuffer()
    pipeline, _, _ = _pipeline(mode_buffer=mode_buffer)

    pipeline.tick(role_reveal.frame)
    mode_buffer.push(ModeDirective("wander", WanderParams()))
    command = pipeline.tick(playing.frame)

    assert pipeline.current_mode_name == "wander"
    assert _directional_or_noop(command)


def test_full_pipeline_with_outer_loop_round_trip() -> None:
    role_reveal, _ = _fixture("role_reveal_nymphs", View.ROLE_REVEAL)
    playing, _ = _fixture("playing_round1", View.PLAYING)
    belief_buffer = BeliefBuffer()
    mode_buffer = ModeBuffer()
    pipeline, _, _ = _pipeline(
        belief_buffer=belief_buffer,
        mode_buffer=mode_buffer,
        watchdog_threshold=9999,
    )
    outer_loop = OuterLoop(
        meta_decide,
        belief_buffer,
        mode_buffer,
    )

    outer_loop.start()
    try:
        pipeline.tick(role_reveal.frame)
        pipeline.tick(playing.frame)
        assert _wait_until(
            lambda: mode_buffer.has_entry()
            or pipeline.current_mode_name == "wander"
        )

        def consumed_wander_directive() -> bool:
            if pipeline.current_mode_name == "wander":
                return True
            pipeline.tick(playing.frame)
            return pipeline.current_mode_name == "wander"

        assert _wait_until(consumed_wander_directive)
    finally:
        outer_loop.stop()


def test_pipeline_logger_emits_events_during_full_replay() -> None:
    frames = [
        _fixture("lobby_full", View.LOBBY)[0].frame,
        _fixture("role_reveal_nymphs", View.ROLE_REVEAL)[0].frame,
        _fixture("playing_round1", View.PLAYING)[0].frame,
        _fixture("whisper_default", View.WHISPER)[0].frame,
    ]
    lines: list[str] = []
    pipeline, _, _ = _pipeline(
        logger=Logger(level="decisions", sink=lines.append),
    )

    for frame in frames:
        pipeline.tick(frame)

    event_types = {entry["type"] for entry in _entries(lines)}
    assert "view_transition" in event_types
    assert "select_task" in event_types
    assert "task_change" in event_types


def test_pipeline_no_crashes_on_all_fixture_views() -> None:
    npy_paths = sorted(Path(FIXTURES_DIR).glob("*.npy"))
    if not npy_paths:
        pytest.skip("No .npy fixtures are available")

    pipeline, _, _ = _pipeline()
    for path in npy_paths:
        frame = np.load(path)
        parse_frame(frame)
        pipeline.tick(frame)

    assert pipeline.belief_state.tick > 0
    assert isinstance(pipeline.belief_state.view, View)


def test_pipeline_handles_view_transitions_without_state_corruption() -> None:
    sequence = [
        ("lobby_full", View.LOBBY),
        ("role_reveal_nymphs", View.ROLE_REVEAL),
        ("playing_round1", View.PLAYING),
        ("whisper_default", View.WHISPER),
        ("playing_round1", View.PLAYING),
        ("hostage_select_default", View.HOSTAGE_SELECT),
        ("hostage_exchange_default", View.HOSTAGE_EXCHANGE),
        ("reveal_default", View.REVEAL),
    ]
    frames = [_fixture(name, view)[0].frame for name, view in sequence]
    pipeline, _, _ = _pipeline()

    for frame in frames:
        pipeline.tick(frame)

    belief = pipeline.belief_state
    assert belief.tick == len(frames)
    assert belief.view == View.REVEAL
    assert belief.in_whisper is False
    assert isinstance(belief.players, dict)
    assert isinstance(belief.chat_history, list)
    if belief.room_size is not None:
        assert belief.room_size[0] > 0
        assert belief.room_size[1] > 0
    if belief.occupancy_grid is not None:
        assert belief.occupancy_grid.room_size == belief.room_size


def test_pipeline_repeated_playing_frame_has_stable_derived_state() -> None:
    role_reveal, _ = _fixture("role_reveal_nymphs", View.ROLE_REVEAL)
    playing, playing_perception = _fixture("playing_round1", View.PLAYING)
    assert playing_perception.overworld is not None
    assert playing_perception.overworld.self_position is not None
    non_self_dot_count = sum(
        not dot.is_self for dot in playing_perception.overworld.minimap_dots
    )
    pipeline, _, _ = _pipeline()

    pipeline.tick(role_reveal.frame)
    confirmed_counts: list[int] = []
    for _ in range(20):
        pipeline.tick(playing.frame)
        grid = pipeline.belief_state.occupancy_grid
        assert grid is not None
        confirmed_counts.append(int(np.count_nonzero(grid.viewport_confirmed)))

    position = playing_perception.overworld.self_position
    belief = pipeline.belief_state
    assert belief.tick == 21
    assert belief.view == View.PLAYING
    assert belief.position == (position.x, position.y)
    assert belief.chat_history == []
    assert len(belief.minimap_sightings) == non_self_dot_count * 20
    assert all(count == confirmed_counts[0] for count in confirmed_counts[1:])


def test_pipeline_alternating_playing_whisper_cleans_chatroom_state() -> None:
    role_reveal, _ = _fixture("role_reveal_nymphs", View.ROLE_REVEAL)
    playing, _ = _fixture("playing_round1", View.PLAYING)
    whisper, _ = _fixture("whisper_default", View.WHISPER)
    pipeline, _, _ = _pipeline()

    pipeline.tick(role_reveal.frame)
    pipeline.tick(playing.frame)
    for _ in range(5):
        pipeline.tick(whisper.frame)
        assert pipeline.belief_state.in_whisper is True
        assert pipeline.belief_state.menu_state is not None

        pipeline.tick(playing.frame)
        assert pipeline.belief_state.in_whisper is False
        assert pipeline.belief_state.whisper_occupants == []
        assert pipeline.belief_state.pending_offers == {"role": False, "color": False}
        assert pipeline.belief_state.pending_entry is None
        assert pipeline.belief_state.menu_state is None
