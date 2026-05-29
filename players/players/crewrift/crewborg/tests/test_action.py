"""Action-layer tests: input encoding and idle resolution (design §3.3, §9)."""

from __future__ import annotations

from players.crewrift.crewborg.action import (
    BTN_A,
    BTN_DOWN,
    BTN_LEFT,
    BTN_RIGHT,
    BTN_UP,
    INPUT_HEADER,
    encode_input,
    resolve_action,
)
from players.crewrift.crewborg.map.types import MapData, MapPoint, MapRect, TaskStation
from players.crewrift.crewborg.types import ActionState, Belief, Intent


def _one_task_map() -> MapData:
    return MapData(
        width=200,
        height=200,
        tasks=(TaskStation(name="t", x=100, y=100, w=20, h=20),),  # center (110, 110)
        vents=(),
        rooms=(),
        button=MapRect(x=0, y=0, w=28, h=34),
        home=MapPoint(x=0, y=0),
    )


def test_encode_input_emits_header_and_masked_byte() -> None:
    assert encode_input(0) == bytes([INPUT_HEADER, 0x00])
    assert encode_input(BTN_UP | BTN_A) == bytes([INPUT_HEADER, 0x21])
    assert encode_input(BTN_DOWN | BTN_LEFT | BTN_RIGHT) == bytes([INPUT_HEADER, 0x0E])


def test_encode_input_masks_reserved_bit_7() -> None:
    # Bit 7 is reserved and must never reach the wire.
    assert encode_input(0xFF) == bytes([INPUT_HEADER, 0x7F])


def test_resolve_idle_holds_nothing() -> None:
    action_state = ActionState(held_mask=BTN_UP)
    command = resolve_action(Intent(kind="idle"), Belief(), action_state)
    assert command.held_mask == 0
    assert command.chat is None
    assert action_state.held_mask == 0


def test_navigate_presses_dpad_toward_target() -> None:
    belief = Belief(self_world_x=0, self_world_y=0)
    command = resolve_action(Intent(kind="navigate_to", point=(100, 0)), belief, ActionState())
    assert command.held_mask == BTN_RIGHT

    belief = Belief(self_world_x=0, self_world_y=0)
    command = resolve_action(Intent(kind="navigate_to", point=(0, 100)), belief, ActionState())
    assert command.held_mask == BTN_DOWN


def test_navigate_releases_within_arrive_deadband() -> None:
    belief = Belief(self_world_x=0, self_world_y=0)
    command = resolve_action(Intent(kind="navigate_to", point=(3, 0)), belief, ActionState())
    assert command.held_mask == 0


def test_navigate_predictive_stop_coasts_when_close_and_moving() -> None:
    belief = Belief(self_world_x=0, self_world_y=0)
    intent = Intent(kind="navigate_to", point=(5, 0))
    # Same intent as last tick (no reset) and a +5px/tick velocity toward target.
    action_state = ActionState(current_intent=intent, route=[(5, 0)], route_goal=(5, 0))
    action_state.last_self_x, action_state.last_self_y = -5, 0
    command = resolve_action(intent, belief, action_state)
    # Remaining 5px is within ~1.3*5 stopping distance, so release and coast.
    assert command.held_mask == 0


def test_navigate_without_self_position_holds_still() -> None:
    command = resolve_action(Intent(kind="navigate_to", point=(100, 0)), Belief(), ActionState())
    assert command.held_mask == 0


def test_intent_change_resets_the_route() -> None:
    belief = Belief(self_world_x=0, self_world_y=0)
    action_state = ActionState()
    resolve_action(Intent(kind="navigate_to", point=(100, 0)), belief, action_state)
    assert action_state.route_goal == (100, 0)
    resolve_action(Intent(kind="navigate_to", point=(0, 100)), belief, action_state)
    assert action_state.route_goal == (0, 100)


def test_complete_task_holds_a_inside_rect_and_navigates_outside() -> None:
    belief_inside = Belief(map=_one_task_map(), self_world_x=105, self_world_y=105)
    command = resolve_action(Intent(kind="complete_task", task_index=0), belief_inside, ActionState())
    assert command.held_mask == BTN_A  # on the station: hold A, no d-pad

    belief_outside = Belief(map=_one_task_map(), self_world_x=0, self_world_y=0)
    command = resolve_action(Intent(kind="complete_task", task_index=0), belief_outside, ActionState())
    assert command.held_mask == BTN_RIGHT | BTN_DOWN  # drive toward center (110, 110)
