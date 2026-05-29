"""Normal mode: the default crewmate stance — complete assigned tasks (design §7.1).

Each tick it concludes completion of the station it is standing on, picks the
nearest incomplete assigned task, and emits ``complete_task(T)`` until belief
shows ``T`` done, then moves to the next. With no tasks left it idles.

Completion is concluded here (not in ``update_belief``) because only the mode
knows which task it is standing on: a task bubble also leaves the visible set by
going off-screen, so "bubble gone" alone is ambiguous. While we hold A on a
station the bubble stays visible until the task actually completes; so a task we
are *inside the rect of* leaving the visible set means we finished it.
"""

from __future__ import annotations

from players.crewrift.crewborg.map.types import TaskStation
from players.crewrift.crewborg.types import ActionState, Belief, Intent
from players.player_sdk import EmptyModeParams, Mode

PROGRESS_COMPLETE_PCT = 100


class NormalMode(Mode[Belief, ActionState, Intent]):
    name = "normal"
    params_type = EmptyModeParams

    def __init__(self, params=None) -> None:
        super().__init__(params)
        self._target: int | None = None

    def decide(self, belief: Belief, action_state: ActionState) -> Intent:
        del action_state
        tasks = belief.map.tasks if belief.map is not None else ()

        self._conclude_completion(belief, tasks)
        self._target = self._select_target(belief, tasks)

        if self._target is None:
            return Intent(kind="idle", reason="no incomplete tasks remain")
        return Intent(kind="complete_task", task_index=self._target, reason="completing assigned task")

    def _conclude_completion(self, belief: Belief, tasks: tuple[TaskStation, ...]) -> None:
        target = self._target
        if target is None or target >= len(tasks):
            return
        if target in belief.completed_task_indices:
            self._target = None
            return
        # Finished if our task's progress reached 100, or its bubble vanished
        # while we are standing inside its rect (we completed it).
        on_station = _inside(tasks[target], belief.self_world_x, belief.self_world_y)
        progress_done = belief.active_task_progress_pct == PROGRESS_COMPLETE_PCT
        bubble_gone = target not in belief.visible_task_indices
        if progress_done or (on_station and bubble_gone):
            belief.completed_task_indices.add(target)
            self._target = None

    def _select_target(self, belief: Belief, tasks: tuple[TaskStation, ...]) -> int | None:
        candidates = [
            index
            for index in belief.assigned_task_indices
            if index < len(tasks) and index not in belief.completed_task_indices
        ]
        if not candidates:
            return None
        # Keep the current target if still valid, to avoid thrashing between tasks.
        if self._target in candidates:
            return self._target
        if belief.self_world_x is None or belief.self_world_y is None:
            return min(candidates)
        self_xy = (belief.self_world_x, belief.self_world_y)
        return min(candidates, key=lambda i: _dist2(self_xy, (tasks[i].center.x, tasks[i].center.y)))


def _inside(task: TaskStation, x: int | None, y: int | None) -> bool:
    if x is None or y is None:
        return False
    return task.x <= x < task.x + task.w and task.y <= y < task.y + task.h


def _dist2(a: tuple[int, int], b: tuple[int, int]) -> int:
    return (a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2
