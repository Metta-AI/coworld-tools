"""Normal mode: the default crewmate stance — complete assigned tasks (design §7.1).

Each tick it concludes completion of the station it is standing on, picks the
nearest **reachable** incomplete assigned task, and emits ``complete_task(T)``
until belief shows ``T`` done, then moves to the next.

Two stall guards (design §5):

- *Reachability* — prefer tasks the nav graph can actually route to, so we don't
  fixate on an unreachable station (the action layer holds still on no path).
- *Arrows-disabled sweep* — when ``showTaskArrows`` is off, off-screen tasks emit
  no signals, so ``assigned_task_indices`` can stay empty at spawn. Rather than
  idle forever, sweep the baked task stations (``navigate_to`` each) to discover
  our assigned ones, whose bubbles appear once we are near them.

Completion is concluded here (not in ``update_belief``) because only the mode
knows which task it is standing on: a bubble also leaves the visible set by going
off-screen, so "bubble gone" alone is ambiguous — but a task whose rect we are
*inside* leaving the visible set means we finished it.
"""

from __future__ import annotations

from players.crewrift.crewborg.map.types import TaskStation
from players.crewrift.crewborg.types import ActionState, Belief, Intent
from players.player_sdk import EmptyModeParams, Mode

PROGRESS_COMPLETE_PCT = 100
SWEEP_ARRIVE_RADIUS = 24  # within this of a station center ⇒ count it as checked


class NormalMode(Mode[Belief, ActionState, Intent]):
    name = "normal"
    params_type = EmptyModeParams

    def __init__(self, params=None) -> None:
        super().__init__(params)
        self._target: int | None = None
        self._swept: set[int] = set()

    def decide(self, belief: Belief, action_state: ActionState) -> Intent:
        del action_state
        tasks = belief.map.tasks if belief.map is not None else ()

        self._conclude_completion(belief, tasks)
        self._target = self._select_target(belief, tasks)
        if self._target is not None:
            return Intent(kind="complete_task", task_index=self._target, reason="completing assigned task")

        sweep = self._sweep_intent(belief, tasks)
        if sweep is not None:
            return sweep
        return Intent(kind="idle", reason="no incomplete tasks remain")

    def _conclude_completion(self, belief: Belief, tasks: tuple[TaskStation, ...]) -> None:
        target = self._target
        if target is None or target >= len(tasks):
            return
        if target in belief.completed_task_indices:
            self._target = None
            return
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

        self_xy = _self_xy(belief)
        # Prefer tasks with a baked reachable anchor; fall back to all if none have
        # one (rare — the action layer then holds still rather than wall-drive).
        if belief.nav is not None:
            reachable = [i for i in candidates if belief.nav.task_anchor(i) is not None]
            if reachable:
                candidates = reachable

        if self._target in candidates:
            return self._target  # keep the current target to avoid thrashing
        if self_xy is None:
            return min(candidates)
        return min(candidates, key=lambda i: _dist2(self_xy, _nav_point(belief, tasks[i], i)))

    def _sweep_intent(self, belief: Belief, tasks: tuple[TaskStation, ...]) -> Intent | None:
        """Sweep baked stations to discover assigned tasks (arrows-disabled, §5)."""

        # Only sweep before any task signal has arrived, while the crew still has
        # tasks to do, and once we know where we are.
        if belief.assigned_task_indices or not tasks or belief.crew_tasks_remaining == 0:
            return None
        self_xy = _self_xy(belief)
        if self_xy is None:
            return None

        # Mark stations we have reached as checked.
        for index, task in enumerate(tasks):
            if _dist2(self_xy, _center(task)) <= SWEEP_ARRIVE_RADIUS**2:
                self._swept.add(index)

        remaining = [i for i in range(len(tasks)) if i not in self._swept]
        if not remaining:
            return None  # checked every station and found no assigned tasks
        nearest = min(remaining, key=lambda i: _dist2(self_xy, _nav_point(belief, tasks[i], i)))
        return Intent(kind="navigate_to", point=_nav_point(belief, tasks[nearest], nearest), reason="sweeping for tasks")


def _inside(task: TaskStation, x: int | None, y: int | None) -> bool:
    if x is None or y is None:
        return False
    return task.x <= x < task.x + task.w and task.y <= y < task.y + task.h


def _center(task: TaskStation) -> tuple[int, int]:
    return task.center.x, task.center.y


def _nav_point(belief: Belief, task: TaskStation, index: int) -> tuple[int, int]:
    """The station's baked reachable anchor, or its center before the graph exists."""

    if belief.nav is not None:
        anchor = belief.nav.task_anchor(index)
        if anchor is not None:
            return anchor
    return task.center.x, task.center.y


def _self_xy(belief: Belief) -> tuple[int, int] | None:
    if belief.self_world_x is None or belief.self_world_y is None:
        return None
    return belief.self_world_x, belief.self_world_y


def _dist2(a: tuple[int, int], b: tuple[int, int]) -> int:
    return (a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2
