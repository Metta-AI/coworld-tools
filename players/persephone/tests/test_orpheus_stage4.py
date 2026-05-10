"""Unit tests for Orpheus Stage 4 task implementations."""

from __future__ import annotations

from dataclasses import FrozenInstanceError, is_dataclass
from types import SimpleNamespace

import pytest

from orpheus.action_memory import ActionMemory
from orpheus.belief_state import BeliefState, PlayerInfo
from orpheus.occupancy_grid import CellState, OccupancyGrid
from orpheus.perception.types import ChatroomBarState, View
from orpheus.task import ActCommand
from orpheus.tasks import (
    AcceptColorExchangeTask,
    AcceptRoleExchangeTask,
    CancelEntryTask,
    CloseViewTask,
    CreateWhisperTask,
    ExitWhisperTask,
    FollowTask,
    GrantEntryTask,
    IdleTask,
    MoveToTask,
    OfferColorExchangeTask,
    OfferRoleExchangeTask,
    OpenGlobalChatTask,
    OpenInfoScreenTask,
    PassLeadershipTask,
    RequestEntryTask,
    RevealRoleTask,
    SelectHostagesTask,
    SendMessageTask,
    TakeLeadershipTask,
    VoteUsurpTask,
    WanderTask,
    WithdrawColorOfferTask,
    WithdrawRoleOfferTask,
)
from orpheus.tasks._menu_nav import MenuNavigator
from orpheus.tasks.movement import OVERWORLD_VIEWS
from orpheus.tasks.view_management import OPEN_VIEW_VIEWS
from orpheus.types import (
    BUTTON_A,
    BUTTON_B,
    BUTTON_DOWN,
    BUTTON_LEFT,
    BUTTON_RIGHT,
    BUTTON_SELECT,
    BUTTON_UP,
)


def _belief(
    *,
    position: tuple[int, int] = (10, 10),
    room_size: tuple[int, int] = (100, 100),
    view: View = View.PLAYING,
) -> BeliefState:
    return BeliefState(
        position=position,
        room_size=room_size,
        occupancy_grid=OccupancyGrid(room_size),
        view=view,
    )


def _menu_state(
    *,
    bar=ChatroomBarState.MENU,
    category: str | None = "ROLE",
    item: str | None = "R.OFFER",
    target_index: int | None = None,
    target_cursor_index: int | None = None,
):
    return SimpleNamespace(
        bar=bar,
        category=category,
        item=item,
        enabled=True,
        target_index=target_index,
        target_cursor_index=target_cursor_index,
        target_colors=[3, 4, 5],
    )


# ---------------------------------------------------------------------------
# ActionMemory rising-edge sequencing
# ---------------------------------------------------------------------------


def test_step_button_press_alternates_press_release_press() -> None:
    memory = ActionMemory()

    assert memory.step_button_press(BUTTON_A) == BUTTON_A
    assert memory.pressed_last_tick is True
    assert memory.step_button_press(BUTTON_A) == 0
    assert memory.pressed_last_tick is False
    assert memory.step_button_press(BUTTON_B) == BUTTON_B
    assert memory.pressed_last_tick is True


def test_step_button_press_respects_manual_pressed_state() -> None:
    memory = ActionMemory()
    memory.pressed_last_tick = True

    assert memory.step_button_press(BUTTON_SELECT) == 0
    assert memory.pressed_last_tick is False
    assert memory.step_button_press(BUTTON_SELECT) == BUTTON_SELECT


# ---------------------------------------------------------------------------
# MenuNavigator
# ---------------------------------------------------------------------------


def test_menu_navigator_opens_closed_menu_with_b_press() -> None:
    belief = BeliefState(menu_state={"bar": ChatroomBarState.DEFAULT})
    memory = ActionMemory()

    command = MenuNavigator((("category", "ROLE"),)).next_command(belief, memory)

    assert command == ActCommand(buttons=BUTTON_B)
    assert MenuNavigator((("category", "ROLE"),)).next_command(
        belief,
        memory,
    ) == ActCommand()


def test_menu_navigator_advances_wrong_category() -> None:
    belief = BeliefState(menu_state=_menu_state(category="COLOR", item="C.OFFER"))
    memory = ActionMemory()

    command = MenuNavigator((("category", "ROLE"),)).next_command(belief, memory)

    assert command == ActCommand(buttons=BUTTON_RIGHT)


def test_menu_navigator_uses_left_for_shorter_category_path() -> None:
    belief = BeliefState(menu_state=_menu_state(category="COLOR", item="C.OFFER"))
    memory = ActionMemory()

    command = MenuNavigator((("category", "EXIT"),)).next_command(belief, memory)

    assert command == ActCommand(buttons=BUTTON_LEFT)


def test_menu_navigator_falls_back_right_for_unknown_category() -> None:
    belief = BeliefState(menu_state=_menu_state(category="UNKNOWN", item="C.OFFER"))
    memory = ActionMemory()

    command = MenuNavigator((("category", "ROLE"),)).next_command(belief, memory)

    assert command == ActCommand(buttons=BUTTON_RIGHT)


def test_menu_navigator_advances_wrong_item_after_category_match() -> None:
    belief = BeliefState(menu_state=_menu_state(category="ROLE", item="ROLE"))
    memory = ActionMemory()

    command = MenuNavigator(
        (("category", "ROLE"), ("item", "R.OFFER"))
    ).next_command(belief, memory)

    assert command == ActCommand(buttons=BUTTON_DOWN)
    assert memory.menu_step == 1


def test_menu_navigator_uses_up_for_shorter_item_path() -> None:
    belief = BeliefState(menu_state=_menu_state(category="ROLE", item="ROLE"))
    memory = ActionMemory()

    command = MenuNavigator(
        (("category", "ROLE"), ("item", "R.ACCPT"))
    ).next_command(belief, memory)

    assert command == ActCommand(buttons=BUTTON_UP)
    assert memory.menu_step == 1


def test_menu_navigator_falls_back_down_for_unknown_item_cycle() -> None:
    belief = BeliefState(menu_state=_menu_state(category="UNKNOWN", item="ROLE"))
    memory = ActionMemory()

    command = MenuNavigator((("item", "R.ACCPT"),)).next_command(belief, memory)

    assert command == ActCommand(buttons=BUTTON_DOWN)


def test_menu_navigator_confirms_when_category_and_item_match() -> None:
    belief = BeliefState(menu_state=_menu_state(category="ROLE", item="R.OFFER"))
    memory = ActionMemory()

    command = MenuNavigator(
        (("category", "ROLE"), ("item", "R.OFFER"), ("confirm",))
    ).next_command(belief, memory)

    assert command == ActCommand(buttons=BUTTON_A)
    assert memory.menu_step == 3
    assert MenuNavigator(
        (("category", "ROLE"), ("item", "R.OFFER"), ("confirm",))
    ).next_command(belief, memory) == ActCommand()


def test_menu_navigator_handles_target_picker_navigation() -> None:
    belief = BeliefState(
        menu_state=_menu_state(
            bar=ChatroomBarState.TARGET_PICKER,
            target_index=0,
        )
    )
    memory = ActionMemory()

    command = MenuNavigator((("target", 2),)).next_command(belief, memory)

    assert command == ActCommand(buttons=BUTTON_RIGHT)
    assert memory.menu_target_index == 1


def test_menu_navigator_prefers_perceived_target_cursor_index() -> None:
    belief = BeliefState(
        menu_state=_menu_state(
            bar=ChatroomBarState.TARGET_PICKER,
            target_cursor_index=2,
        )
    )
    memory = ActionMemory()
    memory.menu_target_index = 0

    command = MenuNavigator((("target", 1),)).next_command(belief, memory)

    assert command == ActCommand(buttons=BUTTON_LEFT)
    assert memory.menu_target_index == 1


def test_menu_navigator_confirms_current_target() -> None:
    belief = BeliefState(
        menu_state=_menu_state(
            bar=ChatroomBarState.TARGET_PICKER,
            target_index=1,
        )
    )
    memory = ActionMemory()

    command = MenuNavigator((("target", 1),)).next_command(belief, memory)

    assert command == ActCommand(buttons=BUTTON_A)
    assert memory.menu_step == 1


def test_menu_navigator_emits_noop_after_all_steps_complete() -> None:
    belief = BeliefState(menu_state=_menu_state())
    memory = ActionMemory()
    memory.menu_step = 1
    memory.pressed_last_tick = True

    command = MenuNavigator((("confirm",),)).next_command(belief, memory)

    assert command == ActCommand()
    assert memory.pressed_last_tick is False


# ---------------------------------------------------------------------------
# Construction, equality, frozen dataclasses, and valid views
# ---------------------------------------------------------------------------


TASK_CASES = [
    (MoveToTask(1, 2), MoveToTask(1, 2), MoveToTask(2, 2), OVERWORLD_VIEWS),
    (FollowTask(1), FollowTask(1), FollowTask(2), OVERWORLD_VIEWS),
    (WanderTask(), WanderTask(), MoveToTask(1, 1), OVERWORLD_VIEWS),
    (
        OpenGlobalChatTask(),
        OpenGlobalChatTask(),
        OpenInfoScreenTask(),
        OPEN_VIEW_VIEWS,
    ),
    (
        OpenInfoScreenTask(),
        OpenInfoScreenTask(),
        OpenGlobalChatTask(),
        OPEN_VIEW_VIEWS,
    ),
    (
        CloseViewTask(),
        CloseViewTask(),
        OpenGlobalChatTask(),
        frozenset({View.GLOBAL_CHAT, View.INFO_SCREEN, View.WHISPER}),
    ),
    (CreateWhisperTask(), CreateWhisperTask(), CancelEntryTask(), OPEN_VIEW_VIEWS),
    (RequestEntryTask(1), RequestEntryTask(1), RequestEntryTask(2), OPEN_VIEW_VIEWS),
    (CancelEntryTask(), CancelEntryTask(), CreateWhisperTask(), frozenset({View.WAITING_ENTRY})),
    (ExitWhisperTask(), ExitWhisperTask(), CreateWhisperTask(), frozenset({View.WHISPER})),
    (GrantEntryTask(), GrantEntryTask(), ExitWhisperTask(), frozenset({View.WHISPER})),
    (OfferColorExchangeTask(), OfferColorExchangeTask(), RevealRoleTask(), frozenset({View.WHISPER})),
    (AcceptColorExchangeTask(1), AcceptColorExchangeTask(1), AcceptColorExchangeTask(2), frozenset({View.WHISPER})),
    (WithdrawColorOfferTask(), WithdrawColorOfferTask(), OfferColorExchangeTask(), frozenset({View.WHISPER})),
    (OfferRoleExchangeTask(), OfferRoleExchangeTask(), RevealRoleTask(), frozenset({View.WHISPER})),
    (AcceptRoleExchangeTask(1), AcceptRoleExchangeTask(1), AcceptRoleExchangeTask(2), frozenset({View.WHISPER})),
    (WithdrawRoleOfferTask(), WithdrawRoleOfferTask(), OfferRoleExchangeTask(), frozenset({View.WHISPER})),
    (RevealRoleTask(), RevealRoleTask(), OfferRoleExchangeTask(), frozenset({View.WHISPER})),
    (PassLeadershipTask(), PassLeadershipTask(), TakeLeadershipTask(), frozenset({View.WHISPER})),
    (TakeLeadershipTask(), TakeLeadershipTask(), PassLeadershipTask(), frozenset({View.WHISPER})),
    (VoteUsurpTask(1), VoteUsurpTask(1), VoteUsurpTask(2), frozenset({View.GLOBAL_CHAT})),
    (SelectHostagesTask((1, 2)), SelectHostagesTask((1, 2)), SelectHostagesTask((2,)), frozenset({View.GLOBAL_CHAT})),
    (SendMessageTask("hi"), SendMessageTask("hi"), SendMessageTask("bye"), frozenset({View.WHISPER, View.GLOBAL_CHAT, View.PLAYING})),
]


@pytest.mark.parametrize(("task", "same", "different", "valid_views"), TASK_CASES)
def test_task_construction_equality_frozen_and_valid_views(
    task,
    same,
    different,
    valid_views,
) -> None:
    assert is_dataclass(task)
    assert task.__dataclass_params__.frozen is True
    assert task == same
    assert task != different
    assert task.valid_views == valid_views
    with pytest.raises(FrozenInstanceError):
        task._stage4_mutation_check = True


def test_idle_task_is_reexported_from_tasks_package() -> None:
    assert IdleTask().select_action(BeliefState(), ActionMemory()) == ActCommand()


# ---------------------------------------------------------------------------
# Movement
# ---------------------------------------------------------------------------


def test_move_to_task_paths_toward_goal_on_empty_grid() -> None:
    belief = _belief(position=(10, 10))
    memory = ActionMemory()

    command = MoveToTask(50, 50).select_action(belief, memory)

    assert command.buttons & BUTTON_RIGHT
    assert command.buttons & BUTTON_DOWN
    assert memory.path


def test_move_to_task_noops_when_at_goal() -> None:
    belief = _belief(position=(50, 50))

    command = MoveToTask(51, 52).select_action(belief, ActionMemory())

    assert command == ActCommand()


def test_move_to_task_repaths_after_stuck_detection() -> None:
    belief = _belief(position=(10, 10))
    memory = ActionMemory()
    task = MoveToTask(50, 50)

    first = task.select_action(belief, memory)
    for _ in range(10):
        task.select_action(belief, memory)
    after_stuck = task.select_action(belief, memory)

    assert first.buttons
    assert after_stuck == ActCommand()
    assert memory.path is None
    assert task.select_action(belief, memory).buttons


def test_move_to_task_noops_without_position() -> None:
    command = MoveToTask(50, 50).select_action(BeliefState(), ActionMemory())

    assert command == ActCommand()


def test_move_to_task_without_grid_uses_direct_path() -> None:
    belief = BeliefState(
        position=(10, 10),
        room_size=(100, 100),
        view=View.PLAYING,
    )
    memory = ActionMemory()

    command = MoveToTask(50, 50).select_action(belief, memory)

    assert command.buttons & BUTTON_RIGHT
    assert command.buttons & BUTTON_DOWN
    assert memory.path == [(10, 10), (50, 50)]


def test_follow_task_noops_when_target_player_is_missing() -> None:
    belief = _belief(position=(10, 10))

    command = FollowTask(99).select_action(belief, ActionMemory())

    assert command == ActCommand()


def test_follow_task_noops_when_target_has_no_position() -> None:
    belief = _belief(position=(10, 10))
    belief.players[2] = PlayerInfo(position=None)

    command = FollowTask(2).select_action(belief, ActionMemory())

    assert command == ActCommand()


def test_follow_task_noops_within_stop_distance() -> None:
    belief = _belief(position=(10, 10))
    belief.players[2] = PlayerInfo(position=(14, 14, 0))

    command = FollowTask(2, stop_distance=10).select_action(belief, ActionMemory())

    assert command == ActCommand()


def test_follow_task_moves_toward_distant_target() -> None:
    belief = _belief(position=(10, 10))
    belief.players[2] = PlayerInfo(position=(50, 50, 0))

    command = FollowTask(2, stop_distance=10).select_action(belief, ActionMemory())

    assert command.buttons & BUTTON_RIGHT
    assert command.buttons & BUTTON_DOWN


def test_wander_task_picks_waypoint_and_moves() -> None:
    belief = _belief(position=(10, 10))
    memory = ActionMemory()

    command = WanderTask().select_action(belief, memory)

    assert hasattr(memory, "wander_waypoint")
    assert command.buttons != 0


def test_wander_task_prefers_unknown_cells_when_grid_has_free_data() -> None:
    belief = _belief(position=(10, 10), room_size=(60, 60))
    grid = belief.occupancy_grid
    assert grid is not None
    grid.mark_free_region(4, 4, 4, 4, viewport_confirmed=True)
    memory = ActionMemory()

    WanderTask().select_action(belief, memory)

    gx, gy = grid.world_to_grid(*memory.wander_waypoint)
    assert grid.get(gx, gy) == CellState.UNKNOWN


def test_wander_task_falls_back_to_free_cells_when_unknown_is_unreachable() -> None:
    belief = _belief(position=(12, 12), room_size=(40, 40))
    grid = belief.occupancy_grid
    assert grid is not None
    grid.cells[:, :] = CellState.WALL
    grid.cells[4:12, 4:12] = CellState.FREE
    grid.cells[15, 15] = CellState.UNKNOWN
    memory = ActionMemory()

    WanderTask().select_action(belief, memory)

    waypoint_cell = grid.world_to_grid(*memory.wander_waypoint)
    assert waypoint_cell != grid.world_to_grid(*belief.position)
    assert grid.get(*waypoint_cell) == CellState.FREE


def test_wander_task_noops_without_room_size() -> None:
    belief = BeliefState(position=(10, 10), view=View.PLAYING)

    command = WanderTask().select_action(belief, ActionMemory())

    assert command == ActCommand()


# ---------------------------------------------------------------------------
# Per-task select_action happy paths
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("task", "button"),
    [
        (OpenGlobalChatTask(), BUTTON_SELECT),
        (OpenInfoScreenTask(), BUTTON_B),
        (CloseViewTask(), BUTTON_SELECT),
        (CreateWhisperTask(), BUTTON_A),
        (CancelEntryTask(), BUTTON_B),
        (ExitWhisperTask(), BUTTON_SELECT),
    ],
)
def test_single_button_tasks_emit_rising_edge(task, button) -> None:
    memory = ActionMemory()

    assert task.select_action(BeliefState(), memory) == ActCommand(buttons=button)
    assert task.select_action(BeliefState(), memory) == ActCommand()


def _next_nonzero_button(task, belief, memory) -> int:
    for _ in range(16):
        command = task.select_action(belief, memory)
        if command.buttons:
            return command.buttons
    raise AssertionError("task did not emit a nonzero button")


def test_vote_usurp_navigates_to_candidate_before_confirming() -> None:
    task = VoteUsurpTask(candidate=2)
    belief = BeliefState(player_count=10)
    memory = ActionMemory()

    assert _next_nonzero_button(task, belief, memory) == BUTTON_RIGHT
    assert memory.usurp_cursor_index == 1
    assert _next_nonzero_button(task, belief, memory) == BUTTON_RIGHT
    assert memory.usurp_cursor_index == 2
    assert _next_nonzero_button(task, belief, memory) == BUTTON_A


def test_vote_usurp_uses_shortest_wrap_direction() -> None:
    task = VoteUsurpTask(candidate=9)
    belief = BeliefState(player_count=10)
    memory = ActionMemory()

    assert _next_nonzero_button(task, belief, memory) == BUTTON_LEFT
    assert memory.usurp_cursor_index == 9
    assert _next_nonzero_button(task, belief, memory) == BUTTON_A


def test_vote_usurp_prefers_perceived_cursor_index() -> None:
    task = VoteUsurpTask(candidate=3)
    belief = BeliefState(player_count=10, extra={"usurp_cursor_index": 4})
    memory = ActionMemory()
    memory.usurp_cursor_index = 0

    assert _next_nonzero_button(task, belief, memory) == BUTTON_LEFT
    assert memory.usurp_cursor_index == 3


def test_request_entry_presses_a_when_close_to_recent_whisper() -> None:
    belief = _belief(position=(10, 10))
    belief.tick = 100
    belief.players[1] = PlayerInfo(position=(14, 14, 0), last_seen_in_whisper=80)

    command = RequestEntryTask(1).select_action(belief, ActionMemory())

    assert command == ActCommand(buttons=BUTTON_A)


def test_request_entry_moves_when_target_is_far() -> None:
    belief = _belief(position=(10, 10))
    belief.tick = 100
    belief.players[1] = PlayerInfo(position=(50, 50, 0), last_seen_in_whisper=80)

    command = RequestEntryTask(1).select_action(belief, ActionMemory())

    assert command.buttons & BUTTON_RIGHT
    assert command.buttons & BUTTON_DOWN


def test_request_entry_noops_when_close_but_whisper_sighting_is_stale() -> None:
    belief = _belief(position=(10, 10))
    belief.tick = 100
    belief.players[1] = PlayerInfo(position=(14, 14, 0), last_seen_in_whisper=10)

    command = RequestEntryTask(1).select_action(belief, ActionMemory())

    assert command == ActCommand()


def test_request_entry_noops_when_target_has_no_position() -> None:
    belief = _belief(position=(10, 10))
    belief.players[1] = PlayerInfo(position=None, last_seen_in_whisper=80)

    command = RequestEntryTask(1).select_action(belief, ActionMemory())

    assert command == ActCommand()


@pytest.mark.parametrize(
    ("task", "category", "item"),
    [
        (GrantEntryTask(), "LEADER", "GRANT"),
        (OfferColorExchangeTask(), "COLOR", "C.OFFER"),
        (AcceptColorExchangeTask(1), "COLOR", "C.ACCPT"),
        (WithdrawColorOfferTask(), "COLOR", "C.UNOFFR"),
        (OfferRoleExchangeTask(), "ROLE", "R.OFFER"),
        (AcceptRoleExchangeTask(1), "ROLE", "R.ACCPT"),
        (WithdrawRoleOfferTask(), "ROLE", "R.UNOFFR"),
        (RevealRoleTask(), "ROLE", "ROLE"),
        (PassLeadershipTask(), "LEADER", "PASS"),
        (TakeLeadershipTask(), "LEADER", "TAKE"),
    ],
)
def test_menu_backed_tasks_confirm_matching_menu_item(task, category, item) -> None:
    belief = BeliefState(menu_state=_menu_state(category=category, item=item))

    command = task.select_action(belief, ActionMemory())

    assert command == ActCommand(buttons=BUTTON_A)


@pytest.mark.parametrize(
    "task",
    [
        OfferColorExchangeTask(),
        AcceptColorExchangeTask(1),
        WithdrawColorOfferTask(),
        OfferRoleExchangeTask(),
        AcceptRoleExchangeTask(1),
        WithdrawRoleOfferTask(),
        RevealRoleTask(),
        PassLeadershipTask(),
        TakeLeadershipTask(),
    ],
)
def test_menu_backed_tasks_open_menu_when_menu_state_missing(task) -> None:
    memory = ActionMemory()

    command = task.select_action(BeliefState(menu_state=None), memory)

    assert command == ActCommand(buttons=BUTTON_B)
    assert task.select_action(BeliefState(menu_state=None), memory) == ActCommand()


def test_accept_role_exchange_confirms_target_after_item_confirm() -> None:
    task = AcceptRoleExchangeTask(1)
    memory = ActionMemory()
    belief = BeliefState(menu_state=_menu_state(category="ROLE", item="R.ACCPT"))

    assert task.select_action(belief, memory) == ActCommand(buttons=BUTTON_A)
    assert task.select_action(belief, memory) == ActCommand()
    belief.menu_state = _menu_state(
        bar=ChatroomBarState.TARGET_PICKER,
        target_index=1,
    )

    assert task.select_action(belief, memory) == ActCommand(buttons=BUTTON_A)


def test_select_hostages_tracks_remaining_and_toggles() -> None:
    memory = ActionMemory()
    task = SelectHostagesTask((2, 4))
    belief = BeliefState(player_count=10)

    assert _next_nonzero_button(task, belief, memory) == BUTTON_RIGHT
    assert memory.hostage_cursor == (0, 1)
    assert _next_nonzero_button(task, belief, memory) == BUTTON_RIGHT
    assert memory.hostage_cursor == (0, 2)
    assert _next_nonzero_button(task, belief, memory) == BUTTON_A
    assert memory.hostage_remaining == [4]
    assert _next_nonzero_button(task, belief, memory) == BUTTON_DOWN
    assert memory.hostage_cursor == (1, 2)
    assert _next_nonzero_button(task, belief, memory) == BUTTON_LEFT
    assert memory.hostage_cursor == (1, 1)
    assert _next_nonzero_button(task, belief, memory) == BUTTON_LEFT
    assert memory.hostage_cursor == (1, 0)
    assert _next_nonzero_button(task, belief, memory) == BUTTON_A
    assert memory.hostage_remaining == []
    assert _next_nonzero_button(task, belief, memory) == BUTTON_B


def test_send_message_emits_chat_text_and_sets_global_cooldown() -> None:
    belief = BeliefState(in_whisper=False)

    command = SendMessageTask("HELLO").select_action(belief, ActionMemory())

    assert command == ActCommand(buttons=0, chat_text="HELLO")
    assert belief.cooldowns["chat"] == 240


def test_send_message_sets_whisper_cooldown() -> None:
    belief = BeliefState(in_whisper=True)

    command = SendMessageTask("SECRET").select_action(belief, ActionMemory())

    assert command == ActCommand(buttons=0, chat_text="SECRET")
    assert belief.cooldowns["chat"] == 48


def test_send_message_respects_cooldown() -> None:
    belief = BeliefState(cooldowns={"chat": 1})

    command = SendMessageTask("HELLO").select_action(belief, ActionMemory())

    assert command == ActCommand()


@pytest.mark.parametrize(
    ("task", "in_whisper"),
    [
        (SendMessageTask("HELLO", channel="chatroom"), False),
        (SendMessageTask("HELLO", channel="global"), True),
    ],
)
def test_send_message_channel_mismatch_noops(task, in_whisper) -> None:
    belief = BeliefState(in_whisper=in_whisper)

    command = task.select_action(belief, ActionMemory())

    assert command == ActCommand()
    assert "chat" not in belief.cooldowns
