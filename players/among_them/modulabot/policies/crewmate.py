"""Crewmate decision tree.

Port of modulabot's ``policy_crew.nim``, adapted for the cogames
pixel pipeline. The eight-tier task selection collapses to four tiers
because the pixel-adapter-populated ``bot.percep.tasks`` already
carries the active / icon / arrow / completed flags directly, so we
don't need separate radar/checkout/mandatory bookkeeping.

Decision priority:

1. Body in view → queue chat + navigate / report.
2. Task hold in progress → keep holding A.
3. Pick best actionable task → navigate or press A on arrival.
4. No task signal → patrol (deterministic quadrant rotation).

Navigation is world-space A\\* when ``game_map`` is supplied and the
localizer has a lock; otherwise it degrades to direct screen-space
steering. This is the wiring-up of :mod:`modulabot.path`: task
world positions come from ``game_map.tasks[index].cx / cy``, body
world positions project from the visible-body screen coords via
the current camera.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .. import actions, chat, diag
from ..state import Bot, TaskState
from ..tuning import (
    ACTION_PERIOD,
    ACTION_WINDOW,
    ARRIVAL_DEADBAND,
    BODY_REPORT_DISTANCE,
    CLOSE_DISTANCE,
    TASK_HOLD_TICKS,
)
from . import base
from .base import Policy

if TYPE_CHECKING:  # pragma: no cover
    from ..data import GameMap


class CrewmatePolicy(Policy):
    """Crewmate play: do tasks, report bodies, stay productive."""

    def decide(self, bot: Bot, game_map: "GameMap | None" = None) -> int:
        # Active hold on a task → keep pressing A until the completion timer
        # runs out. We never mix movement into a hold (that cancels the task
        # in the BitWorld sim).
        if bot.tasks.hold_ticks > 0:
            bot.tasks.hold_ticks -= 1
            if bot.tasks.hold_ticks == 0 and 0 <= bot.tasks.hold_index < len(bot.tasks.resolved):
                bot.tasks.resolved[bot.tasks.hold_index] = True
                bot.tasks.states[bot.tasks.hold_index] = TaskState.COMPLETED
                # Hold complete — clear the task-selection commit so
                # ``best_actionable_task`` picks a new target on the
                # next tick instead of sticking to the just-finished
                # one (which is now filtered out by ``_keep``).
                if bot.tasks.chosen_index == bot.tasks.hold_index:
                    bot.tasks.chosen_index = -1
                    bot.tasks.chosen_since_tick = -1
                bot.tasks.hold_index = -1
            bot.fired("crew.task.continue_hold", "holding task")
            return actions.A

        # Body in view → navigate / report.
        body = base.choose_body(bot)
        if body is not None:
            dist = base.manhattan_from_center(body.x, body.y)
            if dist <= BODY_REPORT_DISTANCE:
                self._queue_body_report(bot, body)
                bot.fired("crew.body.report_in_range", "reporting body")
                return actions.press_b_while(actions.NOOP)  # press B = report
            self._queue_body_report(bot, body)
            self._set_body_goal(bot, body)
            bot.fired("crew.body.navigate", "navigating to body")
            intent = self._navigate(bot, game_map, deadband=BODY_REPORT_DISTANCE)
            return base.anti_stuck_nudge(bot, intent)

        # Pick the best actionable task.
        task = base.best_actionable_task(bot)
        if task is None:
            base.clear_goal(bot)
            bot.fired("crew.idle.no_task", "no task signal, patrolling")
            return self._patrol(bot)

        # On top of an active task → start the hold. The task flag
        # ``active`` is set by the pixel adapter when the player's
        # world position sits inside the task's rectangle, so this
        # is the authoritative "we can press A here" check.
        if task.active:
            bot.tasks.hold_ticks = TASK_HOLD_TICKS
            bot.tasks.hold_index = task.index
            base.clear_goal(bot)  # arrived, drop the path
            bot.fired("crew.task.start_hold", f"holding task {task.index}")
            return actions.A

        # On top of an icon-visible task but not yet active → press A as
        # we arrive. Some tasks activate only when standing on the rect.
        if task.icon_visible and base.manhattan_from_center(task.x, task.y) <= CLOSE_DISTANCE:
            bot.tasks.hold_ticks = TASK_HOLD_TICKS
            bot.tasks.hold_index = task.index
            base.clear_goal(bot)
            bot.fired("crew.task.arrive_and_hold", f"arrived at task {task.index}")
            return actions.A

        # Navigate toward the task. When ``game_map`` is available we
        # path in world space; the A\\* waypoint lookahead avoids the
        # old "walk straight at the wall" failure mode. State-obs /
        # un-localized fallback uses the task's screen coords (from
        # the icon/arrow flag) with direct steering — matches the
        # pre-wiring behaviour.
        self._set_task_goal(bot, task, game_map)
        intent = self._navigate(bot, game_map)
        intent = self._maybe_press_a(bot, intent)
        bot.fired("crew.task.navigate", f"navigating to task {task.index}")
        return base.anti_stuck_nudge(bot, intent)

    # ------------------------------------------------------------------
    # Goal setup
    # ------------------------------------------------------------------

    def _set_task_goal(self, bot: Bot, task, game_map: "GameMap | None") -> None:
        """Record a task goal in both screen and world coords.

        World coords come from ``game_map.tasks[task.index]`` — the
        authoritative world position from ``map.json``. If the map
        or index is missing we fall back to the pixel adapter's
        screen-space target (which the pixel pipeline computed as
        ``task.cx - camera_x``). That fallback keeps the state-obs
        test harness working without threading the game map through.
        """
        screen_x = task.x if task.icon_visible else task.arrow_x
        screen_y = task.y if task.icon_visible else task.arrow_y
        if (
            game_map is not None
            and bot.percep.localized
            and 0 <= task.index < len(game_map.tasks)
        ):
            station = game_map.tasks[task.index]
            base.set_world_goal(
                bot,
                station.cx,
                station.cy,
                name=f"task_{task.index}",
                index=task.index,
                screen_x=screen_x,
                screen_y=screen_y,
            )
        else:
            # Fall back to screen coords as "world" when we have no
            # real camera to project through. ``navigate_to_world_goal``
            # detects the missing localization and uses the greedy
            # screen-delta path.
            base.set_world_goal(
                bot,
                screen_x,
                screen_y,
                name=f"task_{task.index}",
                index=task.index,
                screen_x=screen_x,
                screen_y=screen_y,
            )

    def _set_body_goal(self, bot: Bot, body) -> None:
        """Record a body goal. Bodies only come from the pixel adapter
        (screen coords); we project via the camera when possible so the
        pathfinder can route around walls."""
        wx, wy = base.world_pos_from_screen(bot.percep, body.x, body.y)
        if wx < 0:
            wx, wy = body.x, body.y  # fall back to screen-as-world
        base.set_world_goal(
            bot,
            wx,
            wy,
            name="body",
            index=-1,
            screen_x=body.x,
            screen_y=body.y,
        )

    # ------------------------------------------------------------------
    # Navigation wrapper
    # ------------------------------------------------------------------

    def _navigate(
        self,
        bot: Bot,
        game_map: "GameMap | None",
        *,
        deadband: int = ARRIVAL_DEADBAND,
    ) -> int:
        """Emit a movement action toward ``bot.goal``.

        Dispatches to :func:`modulabot.policies.base.navigate_to_world_goal`
        for the A\\* path; legacy state-obs tests with no ``game_map`` fall
        through to the world-delta greedy path (which for un-localized
        observers is equivalent to the old ``move_toward(goal.x,
        goal.y)``).
        """
        return base.navigate_to_world_goal(bot, game_map, deadband=deadband)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _queue_body_report(self, bot, body) -> None:
        """Queue a chat line accusing the sole nearby non-teammate, if any."""
        suspect_color = -1
        if bot.percep.players:
            candidates = [
                p
                for p in base.alive_other_players(bot)
                if p.color != body.color
                and p.color not in bot.identity.known_imposters
                and _manhattan(p.x, p.y, body.x, body.y) <= 30
            ]
            if len(candidates) == 1:
                suspect_color = candidates[0].color
                bot.voting.accusation_color = suspect_color
        chat.queue_body_report(bot, suspect_color=suspect_color)
        diag.thought(bot, f"queued body report, suspect={suspect_color}")

    def _maybe_press_a(self, bot: Bot, intent: int) -> int:
        """Occasionally press A during travel to pick up incidental tasks."""
        if bot.percep.tick % ACTION_PERIOD < ACTION_WINDOW:
            return actions.press_a_while(intent)
        return intent

    def _patrol(self, bot: Bot) -> int:
        """Deterministic quadrant rotation.

        Matches the cyborg reference policy's patrol cadence. Each agent
        gets its own phase offset based on ``rng_seed`` so mixed lobbies
        don't all patrol in lockstep.
        """
        phase = ((bot.percep.tick // 36) + bot.rng_seed + bot.agent_id * 3) % 4
        return (actions.RIGHT, actions.DOWN, actions.LEFT, actions.UP)[phase]


def _manhattan(ax: int, ay: int, bx: int, by: int) -> int:
    return abs(ax - bx) + abs(ay - by)
