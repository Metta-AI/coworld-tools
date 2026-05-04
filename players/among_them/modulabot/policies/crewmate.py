"""Crewmate decision tree.

Port of modulabot's ``policy_crew.nim``, adapted for the cogames
pixel pipeline. The eight-tier task selection collapses to four tiers
because :func:`~modulabot.policies.base.best_actionable_task` folds
actives / icons / arrows into a single priority chain.

Assignment evidence (post-Phase-1/2 of CREWMATE_TASK_FIX_PLAN.md) is
supplied by the pixel adapter through three flags on each
``TaskInfo``:

- ``icon_visible`` — server-authoritative. The server only renders
  task icons for tasks assigned to this player, so a sprite match at
  the projected icon position is direct proof of assignment.
- ``arrow_visible`` — off-screen task **and** a matching yellow
  radar dot at the projected screen-edge position **or** the
  per-task ``bot.tasks.checkout`` latch is set. The latch means
  "the server told us this task is ours on an earlier tick";
  without it we'd lose the task whenever the dot briefly
  disappears.
- ``active`` — rect-intersection with the player's world pos AND
  one of the above assignment signals. Previously rect-only, which
  made the bot press A on every task rect it walked into.

``TaskInfo.active_rect`` exposes the raw rect-intersection signal
for diagnostics (traces can still show "standing in rect N without
evidence it's ours").

Decision priority:

1. Body in view → queue chat + navigate / report.
2. Task hold in progress → keep holding A.
3. Pick best actionable task → navigate or press A on arrival.
4. No task signal → patrol (deterministic quadrant rotation).

Navigation is world-space A\\* when ``game_map`` is supplied and the
localizer has a lock; otherwise it degrades to direct screen-space
steering.

Known gap (Phase 3 of CREWMATE_TASK_FIX_PLAN.md): the hold branch
still marks tasks ``resolved`` on a pure 84-tick timer with no
server-side confirmation. If `active` ever fires wrongly (regression
in the pipeline or a transient perception flicker) the bot will
still "complete" an unassigned task locally. Fix pending.
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
    HOLD_CONFIRM_WINDOW_TICKS,
    ICON_MISS_COMPLETE_TICKS,
    TASK_HOLD_TICKS,
    TASK_PROGRESS_CONFIRM_EPSILON,
)
from . import base
from .base import Policy

if TYPE_CHECKING:  # pragma: no cover
    from ..data import GameMap


class CrewmatePolicy(Policy):
    """Crewmate play: do tasks, report bodies, stay productive."""

    def decide(self, bot: Bot, game_map: "GameMap | None" = None) -> int:
        # Phase 3: check for pending server-side hold confirmation
        # every tick, before anything else. The check is a no-op
        # when ``confirming_index < 0``; otherwise it may mark the
        # held task ``resolved`` / ``COMPLETED`` (progress advance
        # or icon-disappearance signal fired), or clear the
        # confirmation state (deadline elapsed — task stays
        # unresolved, checkout latch dropped so the bot either
        # drops the task or re-latches it on a fresh radar dot).
        self._check_hold_confirmation(bot)

        # Active hold on a task → keep pressing A until the completion
        # timer runs out. We never mix movement into a hold (that
        # cancels the task in the BitWorld sim). Unlike pre-Phase-3,
        # the timer expiring does *not* mark the task resolved — it
        # transitions into the confirmation window handled above.
        if bot.tasks.hold_ticks > 0:
            bot.tasks.hold_ticks -= 1
            if bot.tasks.hold_ticks == 0:
                self._begin_confirmation(bot)
            bot.fired("crew.task.continue_hold", "holding task")
            return actions.A

        # Body in view → navigate / report.
        body = base.choose_body(bot)
        if body is not None:
            dist = base.manhattan_from_center(body.x, body.y)
            if dist <= BODY_REPORT_DISTANCE:
                self._queue_body_report(bot, body)
                bot.fired("crew.body.report_in_range", "reporting body")
                return actions.press_a_while(actions.NOOP)  # A = report body
            self._queue_body_report(bot, body)
            self._set_body_goal(bot, body)
            bot.fired("crew.body.navigate", "navigating to body")
            intent = self._navigate(bot, game_map, deadband=BODY_REPORT_DISTANCE)
            return base.anti_stuck_nudge(bot, intent)

        # Pick the best actionable task.
        task = base.best_actionable_task(bot)
        if task is None:
            base.clear_goal(bot)
            if bot.tasks.confirming_index >= 0:
                # Awaiting server confirmation for a held task and
                # no other candidates exist. Stand still (NOOP) rather
                # than patrol; walking away would stall the icon-miss
                # signal in ``_check_hold_confirmation`` and leave the
                # confirmation to time out unnecessarily. Any other
                # higher-priority event (body sighting, confirmation
                # resolving, a new task appearing via radar) will
                # override this on the next tick.
                bot.fired(
                    "crew.task.await_confirm",
                    f"awaiting confirmation on task {bot.tasks.confirming_index}",
                )
                return actions.NOOP
            bot.fired("crew.idle.no_task", "no task signal, patrolling")
            return self._patrol(bot)

        # On top of an active task → start the hold. The task flag
        # ``active`` is set by the pixel adapter when the player's
        # world position sits inside the task's rectangle **and** we
        # have assignment evidence (icon match or radar-dot checkout
        # latch). Pre-Phase-2 this was rect-intersection only, which
        # happily started holds on tasks assigned to other crewmates.
        if task.active:
            # Defense in depth: if anything ever sets ``active`` true
            # without the accompanying evidence, we want to know. The
            # pipeline is the sole writer today; a trace firing this
            # branch means a regression in ``_populate_tasks_from_camera``
            # or a state-obs path that bypassed the new gate.
            if not (
                task.icon_visible
                or (
                    0 <= task.index < len(bot.tasks.checkout)
                    and bot.tasks.checkout[task.index]
                )
            ):
                diag.thought(
                    bot,
                    f"active task {task.index} without icon/checkout evidence "
                    "(regression suspected)",
                )
            self._begin_hold(bot, task)
            base.clear_goal(bot)  # arrived, drop the path
            bot.fired("crew.task.start_hold", f"holding task {task.index}")
            return actions.A

        # On top of an icon-visible task but not yet active → press A as
        # we arrive. Some tasks activate only when standing on the rect.
        if task.icon_visible and base.manhattan_from_center(task.x, task.y) <= CLOSE_DISTANCE:
            self._begin_hold(bot, task)
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
    # Hold / confirmation state machine (Phase 3 of the fix plan)
    # ------------------------------------------------------------------

    def _begin_hold(self, bot: Bot, task) -> None:
        """Initialize hold + confirmation state for a fresh hold.

        Captures the pre-hold ``task_progress`` snapshot that the
        confirmation window will compare against, records whether the
        hold was icon-triggered (so ``_check_hold_confirmation`` knows
        the icon-miss signal is usable), and sets the hold timer.
        """
        # Phase 4.3 invariant: the only way ``hold_index`` and
        # ``chosen_index`` can diverge is via a bug somewhere upstream
        # (e.g. a goal-set without going through best_actionable_task,
        # or a confirmation timeout that didn't clear chosen_index).
        # Trace it so we notice; don't crash, since the policy will
        # still produce a sensible action via the new hold.
        if (
            bot.tasks.hold_index >= 0
            and bot.tasks.chosen_index >= 0
            and bot.tasks.hold_index != bot.tasks.chosen_index
        ):
            diag.thought(
                bot,
                f"hold/chosen index mismatch: hold={bot.tasks.hold_index} "
                f"chosen={bot.tasks.chosen_index}",
            )
        bot.tasks.hold_ticks = TASK_HOLD_TICKS
        bot.tasks.hold_index = task.index
        bot.tasks.hold_start_tick = bot.percep.tick
        bot.tasks.pre_hold_progress = bot.percep.task_progress
        # A hold started from a bare ``active`` flag could be either
        # icon- or checkout-driven. We record whichever evidence was
        # *currently* visible; icon_visible is the stronger signal
        # when present, so prefer it.
        bot.tasks.confirming_via_icon = bool(task.icon_visible)

    def _begin_confirmation(self, bot: Bot) -> None:
        """Called at hold-timer expiry. Transitions from holding (A
        pressed) to confirming (A released, watching for server
        signals)."""
        bot.tasks.confirming_index = bot.tasks.hold_index
        bot.tasks.confirming_deadline = (
            bot.percep.tick + HOLD_CONFIRM_WINDOW_TICKS
        )
        bot.tasks.confirming_miss_count = 0
        bot.tasks.hold_index = -1

    def _check_hold_confirmation(self, bot: Bot) -> None:
        """Advance or resolve the pending hold-confirmation, if any.

        Three signals are considered, in priority order. The icon
        path is *primary* (Phase 7 of CREWMATE_TASK_FIX_PLAN.md):
        the icon is server-rendered ground truth for "is this task
        mine and active", so its disappearance — gated by the
        Phase 6 ``clear_area_visible`` + ``maybe_visible`` checks
        applied via the live ``TaskInfo`` flags — is the most
        reliable confirmation we can produce.

        1. Icon-disappearance (primary): only active when the hold
           was icon-triggered (``confirming_via_icon``). Increments
           a consecutive-miss counter each tick the task's
           ``icon_visible`` flag is False **and** the bot is still
           rect-inside (so the icon would have been rendered if the
           task were still assigned). Once the count hits
           :data:`ICON_MISS_COMPLETE_TICKS` we confirm. The counter
           resets on any positive icon match.

           Note: we don't double-call the heavy
           ``maybe_matches_sprite`` check here — Phase 6's
           negative-evidence pass already runs every tick over
           every task and handles the fuzzy-match gate. If a task
           survives that pass with ``icon_misses[i] = 0`` then a
           positive maybe-match cleared the counter, and we
           treat that as "icon still present" for confirmation
           purposes too. We piggy-back on Phase 6's bookkeeping
           rather than duplicating the work.

        2. ``percep.task_progress`` advance (fallback, gated on
           ``not confirming_via_icon``): for checkout-only holds
           where the icon was never visible, this is the only
           positive signal we have. The signal is team-wide so it
           false-positives if a sibling bot completes their task
           during our window — accepted because checkout-only
           holds become rare once Phase 6 is pruning the radar
           candidate set.

        3. Deadline: after :data:`HOLD_CONFIRM_WINDOW_TICKS` ticks
           with no confirmation, give up. The task is NOT marked
           resolved; ``checkout[idx]`` is cleared so the task
           drops out of the candidate set unless a fresh radar
           dot re-latches it on a later tick.
        """
        idx = bot.tasks.confirming_index
        if idx < 0:
            return

        info = next(
            (t for t in bot.percep.tasks if t.index == idx),
            None,
        )

        # Signal 1: icon-miss (primary, when applicable). Phase 6's
        # negative-evidence pass already maintains
        # ``bot.tasks.icon_misses[idx]`` with the strict + fuzzy +
        # clear-area gates baked in. Here we bound the confirmation
        # via a separate per-confirmation counter so we don't race
        # with the Phase 6 latch (which would itself mark the task
        # resolved-not-mine — wrong attribution but same outcome).
        if bot.tasks.confirming_via_icon and info is not None and info.active_rect:
            if info.icon_visible:
                bot.tasks.confirming_miss_count = 0
            else:
                bot.tasks.confirming_miss_count += 1
                if (
                    bot.tasks.confirming_miss_count
                    >= ICON_MISS_COMPLETE_TICKS
                ):
                    self._mark_confirmed(bot, idx)
                    return

        # Signal 2: task_progress advance (fallback). Only honoured
        # for checkout-only holds (no icon ever visible) — for
        # icon-triggered holds the icon is the source of truth and
        # we ignore the team-wide progress bar to avoid the
        # sibling-completion false positive.
        if not bot.tasks.confirming_via_icon and (
            bot.percep.task_progress
            > bot.tasks.pre_hold_progress + TASK_PROGRESS_CONFIRM_EPSILON
        ):
            self._mark_confirmed(bot, idx)
            return

        # Signal 3: deadline. Give up without marking resolved.
        if bot.percep.tick > bot.tasks.confirming_deadline:
            diag.thought(
                bot,
                f"hold confirmation timed out for task {idx}; "
                "un-latching checkout",
            )
            bot.tasks.confirming_index = -1
            bot.tasks.confirming_miss_count = 0
            bot.tasks.confirming_via_icon = False
            # Drop the checkout latch so the task stops being a
            # tier-3 candidate unless a fresh radar dot re-latches
            # it. Without this we'd pathologically re-hold the same
            # unconfirmable task every time best_actionable_task ran.
            if 0 <= idx < len(bot.tasks.checkout):
                bot.tasks.checkout[idx] = False
            if bot.tasks.chosen_index == idx:
                bot.tasks.chosen_index = -1
                bot.tasks.chosen_since_tick = -1

    def _mark_confirmed(self, bot: Bot, idx: int) -> None:
        """Flag a task as server-confirmed-complete and clear the
        pending-confirmation state."""
        if 0 <= idx < len(bot.tasks.resolved):
            bot.tasks.resolved[idx] = True
        if 0 <= idx < len(bot.tasks.states):
            bot.tasks.states[idx] = TaskState.COMPLETED
        bot.tasks.confirming_index = -1
        bot.tasks.confirming_miss_count = 0
        bot.tasks.confirming_via_icon = False
        if bot.tasks.chosen_index == idx:
            bot.tasks.chosen_index = -1
            bot.tasks.chosen_since_tick = -1
        diag.thought(bot, f"confirmed completion of task {idx}")

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
