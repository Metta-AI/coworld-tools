"""Unit tests for the Orpheus Stage 0 type contracts."""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

import orpheus.perception.types as perception_types
import orpheus.types as orpheus_types
from orpheus.action_memory import ActionMemory
from orpheus.belief_state import (
    BeliefState,
    ChatMessageRecord,
    MinimapSighting,
    PlayerInfo,
)
from orpheus.mode import Mode, ModeDirective, ModeParams, ModeRegistry
from orpheus.task import ActCommand, Task
from orpheus.types import (
    BUTTON_A,
    BUTTON_B,
    BUTTON_DOWN,
    BUTTON_LEFT,
    BUTTON_RIGHT,
    BUTTON_SELECT,
    BUTTON_UP,
    PLAYER_COLORS,
    RESET_MASK,
    ActionMask,
    KnowledgeSource,
    PlayerShape,
    Room,
    View,
)


# ---------------------------------------------------------------------------
# Public imports and constants
# ---------------------------------------------------------------------------


def test_public_imports_work() -> None:
    """All Stage 0 public names are importable."""
    assert View is not None
    assert Room is not None
    assert PlayerShape is not None
    assert PLAYER_COLORS is not None
    assert ActionMask is int
    assert BUTTON_UP is not None
    assert BUTTON_DOWN is not None
    assert BUTTON_LEFT is not None
    assert BUTTON_RIGHT is not None
    assert BUTTON_SELECT is not None
    assert BUTTON_A is not None
    assert BUTTON_B is not None
    assert RESET_MASK is not None
    assert KnowledgeSource is not None
    assert Mode is not None
    assert ModeParams is not None
    assert ModeDirective is not None
    assert ModeRegistry is not None
    assert Task is not None
    assert ActCommand is not None
    assert ActionMemory is not None
    assert BeliefState is not None
    assert PlayerInfo is not None
    assert ChatMessageRecord is not None
    assert MinimapSighting is not None


def test_button_mask_values_match_protocol() -> None:
    """Button masks match GAME_API.md."""
    assert BUTTON_UP == 0x01
    assert BUTTON_DOWN == 0x02
    assert BUTTON_LEFT == 0x04
    assert BUTTON_RIGHT == 0x08
    assert BUTTON_SELECT == 0x10
    assert BUTTON_A == 0x20
    assert BUTTON_B == 0x40
    assert RESET_MASK == 0xFF


def test_player_colors_match_game_constants() -> None:
    """Player color order is re-exported from perception constants."""
    assert PLAYER_COLORS == [3, 14, 8, 10, 7, 9, 11, 12]


def test_perception_enums_are_reexported_by_identity() -> None:
    """Re-exported perception enums are the same objects, not copies."""
    assert orpheus_types.View is perception_types.View
    assert orpheus_types.Room is perception_types.Room
    assert orpheus_types.PlayerShape is perception_types.PlayerShape


def test_knowledge_source_values() -> None:
    """KnowledgeSource exposes the six DESIGN.md provenance values."""
    assert {source.name: source.value for source in KnowledgeSource} == {
        "MUTUAL_EXCHANGE": "mutual_exchange",
        "ROLE_REVEAL": "role_reveal",
        "COLOR_EXCHANGE": "color_exchange",
        "GAME_DISPLAY": "game_display",
        "CHAT_CLAIM": "chat_claim",
        "INFERRED": "inferred",
    }


# ---------------------------------------------------------------------------
# Dataclass contracts
# ---------------------------------------------------------------------------


def test_frozen_dataclasses_construct_and_are_immutable() -> None:
    """Stage 0 frozen dataclasses have the expected defaults and equality."""
    default_command = ActCommand()
    assert default_command.buttons == 0
    assert default_command.chat_text is None
    assert default_command.reset_input is False

    command = ActCommand(buttons=BUTTON_A, chat_text="hi")
    assert command.buttons == BUTTON_A
    assert command.chat_text == "hi"

    with pytest.raises(FrozenInstanceError):
        command.buttons = 5

    params = ModeParams()
    directive = ModeDirective(mode="x", params=params)
    assert directive.mode == "x"
    assert directive.params == params
    assert directive == ModeDirective(mode="x", params=ModeParams())

    default_params_directive = ModeDirective(mode="idle")
    assert default_params_directive.params == ModeParams()
    assert default_params_directive == ModeDirective(
        mode="idle",
        params=ModeParams(),
    )


# ---------------------------------------------------------------------------
# Abstract interfaces
# ---------------------------------------------------------------------------


def test_abcs_cannot_be_instantiated_directly() -> None:
    """Task and Mode remain abstract until subclasses implement methods."""
    with pytest.raises(TypeError):
        Task()
    with pytest.raises(TypeError):
        Mode()


class SuperTask(Task):
    """Concrete Task that delegates to the abstract method body."""

    valid_views: set[View] = {View.PLAYING}

    def select_action(self, belief_state, action_memory) -> ActCommand:
        """Delegate to the base implementation for contract testing."""
        return super().select_action(belief_state, action_memory)


class SuperMode(Mode):
    """Concrete Mode that delegates to abstract method bodies."""

    def select_task(self, belief_state, action_memory) -> Task | None:
        """Delegate to the base implementation for contract testing."""
        return super().select_task(belief_state, action_memory)

    def mode_enter(self, belief_state, action_memory) -> None:
        """Delegate to the base implementation for contract testing."""
        super().mode_enter(belief_state, action_memory)

    def mode_switch_cleanup(
        self, belief_state, action_memory, new_mode_directive: ModeDirective
    ) -> None:
        """Delegate to the base implementation for contract testing."""
        super().mode_switch_cleanup(
            belief_state,
            action_memory,
            new_mode_directive,
        )


def test_concrete_abc_subclasses_reach_not_implemented_bodies() -> None:
    """Abstract method bodies raise NotImplementedError when delegated to."""
    task = SuperTask()
    mode = SuperMode()

    with pytest.raises(NotImplementedError):
        task.select_action(None, None)
    with pytest.raises(NotImplementedError):
        mode.select_task(None, None)
    with pytest.raises(NotImplementedError):
        mode.mode_enter(None, None)
    with pytest.raises(NotImplementedError):
        mode.mode_switch_cleanup(
            None,
            None,
            ModeDirective(mode="next", params=ModeParams()),
        )


def test_mode_registry_round_trip() -> None:
    """ModeRegistry stores and retrieves mode classes by string key."""
    registry = ModeRegistry()
    assert len(registry) == 0

    registry.register("foo", SuperMode)

    assert "foo" in registry
    assert len(registry) == 1
    assert registry.get("foo") is SuperMode
    assert registry.get("missing") is None


# ---------------------------------------------------------------------------
# Action memory
# ---------------------------------------------------------------------------


def test_action_memory_initial_state() -> None:
    """ActionMemory starts with empty task-control state."""
    action_memory = ActionMemory()

    assert action_memory.ticks_active == 0
    assert action_memory.commands_sent == 0
    assert action_memory.last_command is None
    assert len(action_memory.command_history) == 0
    assert action_memory.command_history.maxlen == 16
    assert action_memory.pressed_last_tick is False
    assert action_memory.sequence_step == 0


def test_action_memory_clear_resets_standard_fields_and_ad_hoc_state() -> None:
    """clear() restores standard fields and removes task-private fields."""
    action_memory = ActionMemory()
    command = ActCommand(buttons=BUTTON_RIGHT)
    action_memory.ticks_active = 5
    action_memory.commands_sent = 2
    action_memory.last_command = command
    action_memory.command_history.append(command)
    action_memory.pressed_last_tick = True
    action_memory.sequence_step = 3
    action_memory.path = [(1, 2), (3, 4)]

    action_memory.clear()

    assert action_memory.ticks_active == 0
    assert action_memory.commands_sent == 0
    assert action_memory.last_command is None
    assert len(action_memory.command_history) == 0
    assert action_memory.command_history.maxlen == 16
    assert action_memory.pressed_last_tick is False
    assert action_memory.sequence_step == 0
    assert not hasattr(action_memory, "path")


# ---------------------------------------------------------------------------
# Belief state
# ---------------------------------------------------------------------------


def test_belief_state_defaults() -> None:
    """BeliefState is zero-argument constructible with Stage 0 defaults."""
    belief_state = BeliefState()

    assert belief_state.tick == 0
    assert belief_state.view == View.UNKNOWN
    assert belief_state.in_whisper is False
    assert belief_state.is_leader is False
    assert belief_state.players == {}
    assert belief_state.chat_history == []
    assert belief_state.cooldowns == {}
    assert belief_state.inferences == {}
    assert belief_state.extra == {}
    assert belief_state.pending_offers == {"role": False, "color": False}
    assert belief_state.active_color_offers == []
    assert belief_state.active_role_offers == []
    assert belief_state.last_exchange_event is None


def test_belief_state_reset_restores_defaults() -> None:
    """reset() returns a mutated BeliefState to a fresh default state."""
    belief_state = BeliefState()
    belief_state.tick = 99
    belief_state.my_index = 3
    belief_state.players[0] = PlayerInfo(role="hades")
    belief_state.chat_history.append(
        ChatMessageRecord(
            sender_index=0,
            tick=99,
            channel="whisper",
            text="hello",
            occupants=[0, 1],
        )
    )
    belief_state.minimap_sightings.append(
        MinimapSighting(color=3, position=(10, 20), tick=99)
    )
    belief_state.pending_offers["role"] = True
    belief_state.active_color_offers.append(1)
    belief_state.active_role_offers.append(2)
    belief_state.last_exchange_event = {
        "type": "shared_roles",
        "tick": 99,
        "participants": [1, 2],
    }
    belief_state.inferences["plan"] = "test"
    belief_state.extra["mode"] = {"counter": 1}
    belief_state.ad_hoc_mode_counter = 5

    belief_state.reset()

    assert belief_state.tick == 0
    assert belief_state.my_index is None
    assert belief_state.players == {}
    assert belief_state.chat_history == []
    assert belief_state.minimap_sightings == []
    assert belief_state.pending_offers == {"role": False, "color": False}
    assert belief_state.active_color_offers == []
    assert belief_state.active_role_offers == []
    assert belief_state.last_exchange_event is None
    assert belief_state.inferences == {}
    assert belief_state.extra == {}
    assert not hasattr(belief_state, "ad_hoc_mode_counter")
