"""Action-layer tests: input encoding and idle resolution (design §3.3, §9)."""

from __future__ import annotations

import numpy as np

from players.crewrift.crewborg.action import (
    BTN_A,
    BTN_B,
    BTN_DOWN,
    BTN_LEFT,
    BTN_RIGHT,
    BTN_UP,
    CHAT_HEADER,
    INPUT_HEADER,
    encode_chat,
    encode_input,
    resolve_action,
)
from players.crewrift.crewborg.map.types import MapData, MapPoint, MapRect, TaskStation, Vent
from players.crewrift.crewborg.nav import build_nav_grid
from players.crewrift.crewborg.perception.entities import VotingState
from players.crewrift.crewborg.types import ActionState, Belief, BodyEntry, Intent, RosterEntry


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


def test_navigate_holds_still_when_nav_route_unreachable() -> None:
    # A full-height wall splits the map; the goal across it is unreachable.
    mask = np.ones((24, 48), dtype=bool)
    mask[:, 24:32] = False
    belief = Belief(self_world_x=8, self_world_y=12)  # left of the wall
    belief.nav = build_nav_grid(mask, cell_size=8)
    command = resolve_action(Intent(kind="navigate_to", point=(40, 12)), belief, ActionState())
    # nav present + no path ⇒ hold still rather than steer into the wall.
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


def test_encode_chat_wire_format() -> None:
    assert encode_chat("hi") == bytes([CHAT_HEADER, 0x02, 0x00]) + b"hi"
    # Non-ASCII is dropped; length is the ASCII byte count.
    packet = encode_chat("héllo")
    assert packet == bytes([CHAT_HEADER, 0x04, 0x00]) + b"hllo"


def _belief_with_body(self_xy: tuple[int, int], body_xy: tuple[int, int]) -> Belief:
    belief = Belief(self_world_x=self_xy[0], self_world_y=self_xy[1])
    belief.bodies[2003] = BodyEntry(
        object_id=2003, color="green", world_x=body_xy[0], world_y=body_xy[1], first_seen_tick=1
    )
    return belief


def test_report_in_range_edge_presses_a_refiring_requires_release() -> None:
    belief = _belief_with_body((10, 10), (10, 10))  # on top of the body
    action_state = ActionState()
    intent = Intent(kind="report", target_id=2003)

    assert resolve_action(intent, belief, action_state).held_mask == BTN_A  # fresh press
    assert resolve_action(intent, belief, action_state).held_mask == 0  # release to reset edge
    assert resolve_action(intent, belief, action_state).held_mask == BTN_A  # re-press


def test_report_out_of_range_navigates_to_body() -> None:
    belief = _belief_with_body((200, 200), (10, 10))
    command = resolve_action(Intent(kind="report", target_id=2003), belief, ActionState())
    assert command.held_mask == BTN_UP | BTN_LEFT  # toward (10, 10) from (200, 200)


def test_vote_skip_steps_to_skip_then_confirms_once() -> None:
    belief = Belief()
    belief.voting = VotingState(cursor_present=True)  # on a player cell, not skip
    action_state = ActionState()
    intent = Intent(kind="vote")

    assert resolve_action(intent, belief, action_state).held_mask == BTN_DOWN  # step toward skip
    assert resolve_action(intent, belief, action_state).held_mask == 0  # release (edge)

    belief.voting = VotingState(skip_cursor_present=True)  # cursor now on skip
    confirm = resolve_action(intent, belief, action_state)
    assert confirm.held_mask == BTN_A and action_state.vote_confirmed
    # Vote is cast: no further input.
    assert resolve_action(intent, belief, action_state).held_mask == 0


def test_chat_emitted_once() -> None:
    action_state = ActionState()
    intent = Intent(kind="chat", text="gg")
    first = resolve_action(intent, Belief(), action_state)
    assert first.chat == "gg" and first.held_mask == 0
    assert resolve_action(intent, Belief(), action_state).chat is None  # not resent


def test_flee_moves_away_from_threat() -> None:
    belief = Belief(self_world_x=100, self_world_y=100)
    belief.roster[1004] = RosterEntry(
        object_id=1004, color="red", facing="left", world_x=110, world_y=100, last_seen_tick=1
    )
    command = resolve_action(Intent(kind="flee_from", target_id=1004), belief, ActionState())
    assert command.held_mask == BTN_LEFT  # threat is to our right ⇒ flee left


def _belief_with_target(self_xy: tuple[int, int], target_xy: tuple[int, int]) -> Belief:
    belief = Belief(self_world_x=self_xy[0], self_world_y=self_xy[1])
    belief.roster[1004] = RosterEntry(
        object_id=1004, color="red", facing="left", world_x=target_xy[0], world_y=target_xy[1], last_seen_tick=1
    )
    return belief


def test_kill_navigates_then_edge_presses_a_in_range() -> None:
    on_target = _belief_with_target((50, 50), (50, 50))
    action_state = ActionState()
    intent = Intent(kind="kill", target_id=1004)
    assert resolve_action(intent, on_target, action_state).held_mask == BTN_A  # fresh press
    assert resolve_action(intent, on_target, action_state).held_mask == 0  # release (edge)

    far = _belief_with_target((300, 300), (50, 50))
    assert resolve_action(Intent(kind="kill", target_id=1004), far, ActionState()).held_mask == BTN_UP | BTN_LEFT


def _belief_with_vent(self_xy: tuple[int, int], vent_xy: tuple[int, int]) -> Belief:
    vent = Vent(x=vent_xy[0] - 7, y=vent_xy[1] - 7, w=14, h=14, group="1", group_index=1)  # center vent_xy
    map_data = MapData(
        width=1235, height=659, tasks=(), vents=(vent,), rooms=(), button=MapRect(x=0, y=0, w=28, h=34),
        home=MapPoint(x=0, y=0),
    )
    return Belief(map=map_data, self_world_x=self_xy[0], self_world_y=self_xy[1])


def test_vent_navigates_then_holds_b_level_in_range() -> None:
    on_vent = _belief_with_vent((100, 100), (100, 100))
    action_state = ActionState()
    intent = Intent(kind="vent")
    # B is level-triggered: held every tick in range (no edge release).
    assert resolve_action(intent, on_vent, action_state).held_mask == BTN_B
    assert resolve_action(intent, on_vent, action_state).held_mask == BTN_B

    far = _belief_with_vent((300, 300), (100, 100))
    assert resolve_action(Intent(kind="vent"), far, ActionState()).held_mask == BTN_UP | BTN_LEFT
