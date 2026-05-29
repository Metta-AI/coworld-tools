"""Normal mode: task selection + completion detection (design §7.1)."""

from __future__ import annotations

import numpy as np

from players.crewrift.crewborg.map.types import MapData, MapPoint, MapRect, TaskStation
from players.crewrift.crewborg.modes import NormalMode
from players.crewrift.crewborg.nav import build_nav_grid
from players.crewrift.crewborg.types import ActionState, Belief


def _map_with_tasks() -> MapData:
    return MapData(
        width=1000,
        height=1000,
        tasks=(
            TaskStation(name="near", x=100, y=100, w=20, h=20),  # center (110, 110)
            TaskStation(name="far", x=500, y=500, w=20, h=20),  # center (510, 510)
        ),
        vents=(),
        rooms=(),
        button=MapRect(x=0, y=0, w=28, h=34),
        home=MapPoint(x=0, y=0),
    )


def test_picks_nearest_incomplete_assigned_task() -> None:
    belief = Belief(
        map=_map_with_tasks(),
        assigned_task_indices={0, 1},
        visible_task_indices={0, 1},
        self_world_x=490,
        self_world_y=490,  # nearest to task 1's center (510, 510)
    )
    intent = NormalMode().decide(belief, ActionState())
    assert intent.kind == "complete_task" and intent.task_index == 1


def test_advances_to_next_task_after_completion() -> None:
    belief = Belief(
        map=_map_with_tasks(),
        assigned_task_indices={0, 1},
        visible_task_indices={0, 1},
        self_world_x=110,
        self_world_y=110,  # standing on task 0
    )
    mode = NormalMode()

    first = mode.decide(belief, ActionState())
    assert first.task_index == 0  # nearest is task 0

    # Task 0 completes: progress hits 100 and its bubble leaves the visible set.
    belief.active_task_progress_pct = 100
    belief.visible_task_indices = {1}
    second = mode.decide(belief, ActionState())
    assert 0 in belief.completed_task_indices
    assert second.kind == "complete_task" and second.task_index == 1


def test_idles_when_no_tasks_remain() -> None:
    belief = Belief(
        map=_map_with_tasks(),
        assigned_task_indices={0, 1},
        completed_task_indices={0, 1},
        self_world_x=110,
        self_world_y=110,
    )
    intent = NormalMode().decide(belief, ActionState())
    assert intent.kind == "idle"


def test_sweeps_baked_tasks_when_no_signals_arrive() -> None:
    # showTaskArrows disabled: no task signals, so assigned stays empty. Rather
    # than idle forever, sweep toward the nearest baked station to discover tasks.
    belief = Belief(map=_map_with_tasks(), self_world_x=0, self_world_y=0, crew_tasks_remaining=5)
    intent = NormalMode().decide(belief, ActionState())
    assert intent.kind == "navigate_to"
    assert intent.point == (110, 110)  # nearest station center to (0, 0)


def test_no_sweep_once_crew_tasks_are_done() -> None:
    belief = Belief(map=_map_with_tasks(), self_world_x=0, self_world_y=0, crew_tasks_remaining=0)
    assert NormalMode().decide(belief, ActionState()).kind == "idle"


def test_picks_reachable_task_over_nearer_unreachable_one() -> None:
    mask = np.ones((24, 48), dtype=bool)
    mask[:, 24:32] = False  # wall splits the map
    belief = Belief(
        map=MapData(
            width=48,
            height=24,
            tasks=(
                TaskStation(name="L", x=6, y=10, w=4, h=4),  # center (8, 12), left
                TaskStation(name="R", x=38, y=10, w=4, h=4),  # center (40, 12), right
            ),
            vents=(),
            rooms=(),
            button=MapRect(x=0, y=0, w=4, h=4),
            home=MapPoint(x=0, y=0),
        ),
        assigned_task_indices={0, 1},
        visible_task_indices={0, 1},
        self_world_x=8,
        self_world_y=12,  # left of the wall
    )
    belief.nav = build_nav_grid(mask, cell_size=8)
    intent = NormalMode().decide(belief, ActionState())
    assert intent.kind == "complete_task" and intent.task_index == 0  # task 1 is unreachable
