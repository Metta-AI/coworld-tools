"""Normal mode: the default crewmate stance — complete assigned tasks (design §7.1).

Targeting is driven off the **live task-signal set** (``visible_task_indices`` — the
arrows + bubbles, which together mark exactly the incomplete assigned tasks): pick
the nearest **reachable** signalled task, emit ``complete_task(T)`` until it's done,
then move to the next. When **no** task signal remains, every task is done, so head
back to the spawn / start room rather than standing still.

**Completion detection.** The authoritative signal is the **bubble disappearing**
(``T`` leaving the signal set while we are inside its rect). But a bubble can also
blink out for a tick from occlusion (an imposter overlapping us) or a screen-edge —
so we *gate* it on the progress bar: ``T`` is concluded done only if we recently saw
its progress reach ``COMPLETION_PROGRESS_PCT`` (≈ done). A bubble vanishing without
that progress is treated as a flicker — we keep holding the same task. Progress is
only a gate, never the trigger (so we never stop the hold early at, say, 98%); and
because targeting uses the live signals, a falsely-concluded task that is still
signalled is simply re-targeted (self-healing).

Two stall guards (design §5):

- *Reachability* — prefer tasks the nav graph can actually route to, so we don't
  fixate on an unreachable station (the action layer holds still on no path).
- *Arrows-disabled sweep* — when ``showTaskArrows`` is off, off-screen tasks emit
  no signals, so the signal set can be empty at spawn even with tasks to do. Rather
  than head home immediately, sweep the baked stations to discover assigned ones.
"""

from __future__ import annotations

from typing import ClassVar

from players.crewrift.crewborg.map.types import TaskStation
from players.crewrift.crewborg.types import ActionState, Belief, Intent
from players.player_sdk import EmptyModeParams, Mode

# A bubble leaving the signal set counts as completion only if progress recently
# reached at least this — otherwise it's treated as a flicker/occlusion.
COMPLETION_PROGRESS_PCT = 90
SWEEP_ARRIVE_RADIUS = 24  # within this of a station center ⇒ count it as checked


class NormalMode(Mode[Belief, ActionState, Intent]):
    name = "normal"
    params_type = EmptyModeParams
    travel_intent_kind: ClassVar[str] = "navigate_to"
    use_nav_targets: ClassVar[bool] = True

    def __init__(self, params=None) -> None:
        super().__init__(params)
        self._target: int | None = None
        self._max_progress: int = 0  # peak progress seen for the current target
        self._swept: set[int] = set()

    def decide(self, belief: Belief, action_state: ActionState) -> Intent:
        del action_state
        tasks = belief.map.tasks if belief.map is not None else ()

        self._update_target(belief, tasks)
        if self._target is not None:
            return self._task_intent(belief, tasks, self._target)

        sweep = self._sweep_intent(belief, tasks)
        if sweep is not None:
            return sweep
        return self._return_to_start(belief)

    def _update_target(self, belief: Belief, tasks: tuple[TaskStation, ...]) -> None:
        """Conclude/keep the current target, then pick a new one off the live signals."""

        signals = belief.visible_task_indices
        target = self._target
        if target is not None and target < len(tasks):
            on_station = _inside(tasks[target], belief.self_world_x, belief.self_world_y)
            if on_station and belief.active_task_progress_pct is not None:
                self._max_progress = max(self._max_progress, belief.active_task_progress_pct)
            if target not in signals:
                # Bubble gone: a real completion only if progress reached ~done.
                # Otherwise it's a flicker/occlusion — keep holding the same task.
                if self._max_progress >= COMPLETION_PROGRESS_PCT:
                    belief.completed_task_indices.add(target)
                    self._target = None
            # if still signalled, keep the current target (avoids thrashing).

        if self._target is None:
            self._target = self._pick_target(belief, tasks, signals)
            self._max_progress = 0

    def _pick_target(self, belief: Belief, tasks: tuple[TaskStation, ...], signals: set[int]) -> int | None:
        # The live signal set is the authoritative list of remaining tasks; a task
        # still signalled is still to do (even if we earlier mis-concluded it done).
        candidates = [index for index in signals if index < len(tasks)]
        if not candidates:
            return None

        # Prefer tasks with a baked reachable anchor; fall back to all if none have
        # one (rare — the action layer then holds still rather than wall-drive).
        if self.use_nav_targets and belief.nav is not None:
            reachable = [i for i in candidates if belief.nav.task_anchor(i) is not None]
            if reachable:
                candidates = reachable

        self_xy = _self_xy(belief)
        if self_xy is None:
            return min(candidates)
        return min(candidates, key=lambda i: _dist2(self_xy, self._task_target_point(belief, tasks[i], i)))

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
        nearest = min(remaining, key=lambda i: _dist2(self_xy, self._task_target_point(belief, tasks[i], i)))
        return self._travel_intent(
            self._task_target_point(belief, tasks[nearest], nearest),
            reason="sweeping for tasks",
            task_index=nearest,
        )

    def _task_intent(self, belief: Belief, tasks: tuple[TaskStation, ...], target: int) -> Intent:
        del belief, tasks
        return Intent(kind="complete_task", task_index=target, reason="completing assigned task")

    def _task_target_point(self, belief: Belief, task: TaskStation, index: int) -> tuple[int, int]:
        if self.use_nav_targets:
            return _nav_point(belief, task, index)
        return _center(task)

    def _travel_intent(self, point: tuple[int, int], *, reason: str, task_index: int | None = None) -> Intent:
        return Intent(kind=self.travel_intent_kind, point=point, task_index=task_index, reason=reason)

    def _return_to_start(self, belief: Belief) -> Intent:
        return _return_to_start(belief, kind=self.travel_intent_kind, snap_to_nav=self.use_nav_targets)


class CrewmateGhostMode(NormalMode):
    """Crewmate ghost tasking: finish tasks with wall-ignoring navigation."""

    name = "crewmate_ghost"
    travel_intent_kind = "navigate_to_noclip"
    use_nav_targets = False

    def _task_intent(self, belief: Belief, tasks: tuple[TaskStation, ...], target: int) -> Intent:
        task = tasks[target]
        if _inside(task, belief.self_world_x, belief.self_world_y):
            return Intent(kind="complete_task", task_index=target, reason="ghost: completing assigned task")
        return self._travel_intent(
            _center(task),
            reason="ghost: moving through walls to assigned task",
            task_index=target,
        )


def _return_to_start(belief: Belief, *, kind: str = "navigate_to", snap_to_nav: bool = True) -> Intent:
    """All assigned tasks done — head back to the spawn / start room instead of
    standing still (which strands a finished crewmate and earns stuck penalties)."""

    if belief.map is None:
        return Intent(kind="idle", reason="no incomplete tasks remain")
    goal = (belief.map.home.x, belief.map.home.y)
    if snap_to_nav and belief.nav is not None:
        cell = belief.nav.nearest_reachable_node(*goal)
        if cell is not None:
            goal = belief.nav.node_point[cell]
    return Intent(kind=kind, point=goal, reason="tasks done: returning to the start room")


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
