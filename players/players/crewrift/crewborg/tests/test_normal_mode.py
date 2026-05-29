"""Normal mode: task selection + completion detection (design §7.1)."""

from __future__ import annotations

from players.crewrift.crewborg.map.types import MapData, MapPoint, MapRect, TaskStation
from players.crewrift.crewborg.modes import NormalMode
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
