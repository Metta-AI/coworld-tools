"""Phase 0 reproducer tests for the crewmate task-selection bugs.

See ``among_them/modulabot/CREWMATE_TASK_FIX_PLAN.md``.

These tests assert the *desired post-fix* behaviour and are therefore
expected to fail against the current implementation. They are marked
``expectedFailure`` so the overall suite stays green in Phase 0; the
``expectedFailure`` decorator will be removed phase by phase as the
fixes land:

- ``test_active_requires_assignment_evidence`` → Phase 2 removes xfail.
- ``test_arrow_requires_radar_match`` → Phase 1 removes xfail.
- ``test_hold_completion_requires_server_confirmation`` → Phase 3
  removes xfail.

All three tests exercise layers in isolation (no real pixel frames, no
``BotCore`` pipeline), so they're cheap and stay focused on the bugs.
"""

from __future__ import annotations

import types
import unittest

import numpy as np

from modulabot import actions
from modulabot.data import SCREEN_HEIGHT, SCREEN_WIDTH, SPRITE_SIZE, Sprite, TaskStation
from modulabot.geometry import PLAYER_WORLD_OFF_X, PLAYER_WORLD_OFF_Y
from modulabot.perception.pixel_pipeline import (
    _populate_tasks_from_camera,
    _projected_radar_dot,
)
from modulabot.policies import base
from modulabot.policies.crewmate import CrewmatePolicy
from modulabot.state import Bot, CameraLock, Phase, RadarDotMatch, Role, TaskInfo, TaskState
from modulabot.tuning import (
    HOLD_CONFIRM_WINDOW_TICKS,
    ICON_MISS_COMPLETE_TICKS,
    ICON_MISS_THRESHOLD,
    RADAR_MATCH_TOLERANCE,
    TASK_HOLD_TICKS,
    TASK_PROGRESS_CONFIRM_EPSILON,
)


def _stub_map(tasks: list[TaskStation]):
    """Return a minimal stand-in for ``GameMap`` that exposes the
    ``.tasks`` attribute used by ``_populate_tasks_from_camera``."""
    return types.SimpleNamespace(tasks=tasks)


# Phase 6: ``_populate_tasks_from_camera`` now requires a frame and the
# task sprite. For tests that don't care about the icon-miss
# negative-evidence pass we use a blank frame + a fully transparent
# sprite. ``maybe_matches_sprite`` returns False whenever the sprite
# has zero opaque pixels, so the negative-evidence loop will see "no
# match" but the threshold (``ICON_MISS_THRESHOLD``) won't fire within
# a single test call.
_BLANK_FRAME = np.zeros((SCREEN_HEIGHT, SCREEN_WIDTH), dtype=np.uint8)
_TRANSPARENT_SPRITE = Sprite(
    width=SPRITE_SIZE,
    height=SPRITE_SIZE,
    pixels=np.full((SPRITE_SIZE, SPRITE_SIZE), 255, dtype=np.uint8),
)


def _populate(bot: Bot, game_map, frame=None, sprite=None) -> None:
    """Test wrapper around ``_populate_tasks_from_camera`` that
    supplies a blank frame + transparent sprite by default. Tests
    that exercise the negative-evidence path provide their own
    frame / sprite."""
    _populate_tasks_from_camera(
        bot,
        game_map,
        _BLANK_FRAME if frame is None else frame,
        _TRANSPARENT_SPRITE if sprite is None else sprite,
    )


def _localized_bot_at(task_wx: int, task_wy: int) -> Bot:
    """Construct a Bot whose camera places the player at the given
    world coordinates. Sets ``localized=True`` so the pipeline doesn't
    short-circuit out of task population."""
    bot = Bot(agent_id=0)
    bot.role = Role.CREWMATE
    bot.percep.phase = Phase.PLAYING
    bot.percep.localized = True
    bot.percep.camera_lock = CameraLock.FRAME_MAP_LOCK
    # player_world_x(p) = camera_x + PLAYER_WORLD_OFF_X
    bot.percep.camera_x = task_wx - PLAYER_WORLD_OFF_X
    bot.percep.camera_y = task_wy - PLAYER_WORLD_OFF_Y
    return bot


class _Phase0ActiveRectTests(unittest.TestCase):
    """Pixel-pipeline emits ``active=True`` for any task rect the player
    is standing in, even when no icon / radar evidence says the task is
    assigned. Phase 2 gates ``active`` on assignment evidence."""

    def test_active_requires_assignment_evidence(self):
        # One task station whose rect contains the player's world pos.
        station = TaskStation(
            index=0, name="fake", x=500, y=500, w=20, h=20
        )
        # Second station off somewhere else, irrelevant.
        other = TaskStation(
            index=1, name="other", x=100, y=100, w=20, h=20
        )
        bot = _localized_bot_at(task_wx=510, task_wy=510)  # inside station 0
        # No visible task icons, no radar dots → no assignment evidence.
        bot.percep.visible_task_icons = []
        bot.percep.radar_dots = []

        _populate(bot, _stub_map([station, other]))

        task_zero = next(t for t in bot.percep.tasks if t.index == 0)
        self.assertFalse(
            task_zero.active,
            "player inside a task rect should NOT be 'active' without "
            "icon or radar evidence that the task is assigned",
        )


class _Phase0ArrowGatingTests(unittest.TestCase):
    """Every off-screen task currently gets ``arrow_visible=True``
    unconditionally; ``best_actionable_task`` then picks one and the
    bot chases it. Phase 1 gates ``arrow_visible`` on a matching
    yellow radar dot."""

    def test_arrow_requires_radar_match(self):
        # Three off-screen tasks far from the player, no radar dots at all.
        tasks = [
            TaskStation(index=i, name=f"t{i}", x=1000 + 50 * i, y=1000, w=20, h=20)
            for i in range(3)
        ]
        bot = _localized_bot_at(task_wx=100, task_wy=100)  # far from the tasks
        bot.percep.visible_task_icons = []
        bot.percep.radar_dots = []

        _populate(bot, _stub_map(tasks))

        for info in bot.percep.tasks:
            self.assertFalse(
                info.arrow_visible,
                f"off-screen task {info.index} should not surface an "
                "arrow without a matching radar dot",
            )

        # And therefore best_actionable_task returns None → patrol.
        self.assertIsNone(base.best_actionable_task(bot))


class Phase1RadarGatingTests(unittest.TestCase):
    """Positive-path tests for Phase 1: a matching yellow radar dot
    admits the task as a tier-3 candidate, and the checkout latch
    keeps it admitted when the dot momentarily disappears."""

    def _off_screen_task_setup(self):
        # Single far-away task; player at world (100, 100). The
        # projected screen-edge position is deterministic from the
        # camera offset and task position.
        station = TaskStation(index=0, name="t0", x=1000, y=1000, w=20, h=20)
        bot = _localized_bot_at(task_wx=100, task_wy=100)
        bot.percep.visible_task_icons = []
        return bot, station

    def test_arrow_visible_when_radar_dot_matches(self):
        bot, station = self._off_screen_task_setup()
        cam_x = bot.percep.camera_x
        cam_y = bot.percep.camera_y
        on_screen, proj_x, proj_y = _projected_radar_dot(
            station, cam_x, cam_y, 100, 100
        )
        self.assertFalse(on_screen, "test precondition: task must be off-screen")
        # Drop a radar dot right on the projected edge position.
        bot.percep.radar_dots = [RadarDotMatch(x=proj_x, y=proj_y)]

        _populate(bot, _stub_map([station]))

        info = bot.percep.tasks[0]
        self.assertTrue(info.arrow_visible)
        self.assertEqual((info.arrow_x, info.arrow_y), (proj_x, proj_y))
        self.assertTrue(bot.tasks.checkout[0], "first dot-match must latch checkout")

    def test_checkout_latch_persists_when_dot_disappears(self):
        bot, station = self._off_screen_task_setup()
        cam_x = bot.percep.camera_x
        cam_y = bot.percep.camera_y
        _, proj_x, proj_y = _projected_radar_dot(station, cam_x, cam_y, 100, 100)
        # First frame: dot visible → latch fires.
        bot.percep.radar_dots = [RadarDotMatch(x=proj_x, y=proj_y)]
        _populate(bot, _stub_map([station]))
        self.assertTrue(bot.tasks.checkout[0])

        # Second frame: dot gone. Task must stay a candidate.
        bot.percep.tasks = []  # pipeline clears per-frame
        bot.percep.radar_dots = []
        _populate(bot, _stub_map([station]))

        info = bot.percep.tasks[0]
        self.assertTrue(
            info.arrow_visible,
            "checkout latch should keep arrow_visible across a missing-dot frame",
        )
        # best_actionable_task should pick it, not return None.
        chosen = base.best_actionable_task(bot)
        self.assertIsNotNone(chosen)
        self.assertEqual(chosen.index, 0)

    def test_radar_dot_match_tolerance(self):
        bot, station = self._off_screen_task_setup()
        cam_x = bot.percep.camera_x
        cam_y = bot.percep.camera_y
        _, proj_x, proj_y = _projected_radar_dot(station, cam_x, cam_y, 100, 100)
        # Dot exactly at the tolerance edge → still matches.
        bot.percep.radar_dots = [
            RadarDotMatch(x=proj_x + RADAR_MATCH_TOLERANCE, y=proj_y)
        ]
        _populate(bot, _stub_map([station]))
        self.assertTrue(bot.percep.tasks[0].arrow_visible)

        # Reset latch + one pixel further → no match.
        bot.tasks.checkout[0] = False
        bot.percep.tasks = []
        bot.percep.radar_dots = [
            RadarDotMatch(x=proj_x + RADAR_MATCH_TOLERANCE + 1, y=proj_y)
        ]
        _populate(bot, _stub_map([station]))
        self.assertFalse(bot.percep.tasks[0].arrow_visible)


class Phase2ActiveGatingTests(unittest.TestCase):
    """Positive tests for Phase 2: ``active`` flag now requires
    ``active_rect AND (icon_visible OR checkout[i])``."""

    def _task_and_bot_inside_rect(self, index: int = 0):
        station = TaskStation(
            index=index, name=f"t{index}", x=500, y=500, w=20, h=20
        )
        bot = _localized_bot_at(task_wx=510, task_wy=510)  # inside rect
        bot.percep.visible_task_icons = []
        bot.percep.radar_dots = []
        return bot, station

    def test_active_when_icon_visible(self):
        # We don't have easy access to a real matching IconMatch in
        # unit tests, so exercise the icon path by pretending the
        # pipeline already produced a matching icon. We seed the
        # expected icon position so the sprite-match loop fires.
        from modulabot.state import IconMatch

        bot, station = self._task_and_bot_inside_rect()
        cam_x = bot.percep.camera_x
        cam_y = bot.percep.camera_y
        # The icon-match branch compares ``match.x + 6`` / ``match.y
        # + 6`` against ``(task.cx - cam_x, task.y - cam_y)``, so an
        # IconMatch placed at ``(task.cx - cam_x - 6, task.y - cam_y - 6)``
        # gives an exact hit.
        proj_icon_x = station.cx - cam_x
        proj_icon_y = station.y - cam_y
        bot.percep.visible_task_icons = [
            IconMatch(x=proj_icon_x - 6, y=proj_icon_y - 6)
        ]

        _populate(bot, _stub_map([station]))
        info = bot.percep.tasks[0]
        self.assertTrue(info.icon_visible, "precondition: icon must be visible")
        self.assertTrue(info.active_rect)
        self.assertTrue(info.active, "icon_visible inside rect → active")

    def test_active_when_checkout_latched(self):
        bot, station = self._task_and_bot_inside_rect()
        bot.tasks.checkout = [True]  # pretend we latched on a prior tick

        _populate(bot, _stub_map([station]))
        info = bot.percep.tasks[0]
        self.assertTrue(info.active_rect)
        self.assertTrue(info.active, "checkout-latched inside rect → active")

    def test_active_rect_preserved_for_diagnostics(self):
        # No icon, no radar, no checkout → active=False but active_rect=True.
        bot, station = self._task_and_bot_inside_rect()

        _populate(bot, _stub_map([station]))
        info = bot.percep.tasks[0]
        self.assertTrue(
            info.active_rect,
            "active_rect must still reflect the raw rect intersection "
            "for diagnostic/tracing purposes",
        )
        self.assertFalse(info.active)

    def test_crewmate_does_not_hold_on_unassigned_rect(self):
        """End-to-end sanity: sitting in a non-assigned rect does NOT
        start a hold. Bot should either navigate elsewhere (if another
        candidate exists) or patrol, never return ``actions.A`` on the
        first decide-call."""
        bot, station = self._task_and_bot_inside_rect()
        bot.role = Role.CREWMATE
        # No other tasks, no body, no icon, no radar → patrol branch.
        _populate(bot, _stub_map([station]))
        action = CrewmatePolicy().decide(bot, game_map=None)
        self.assertNotEqual(
            action,
            actions.A,
            "standing in an unassigned task rect must not press A",
        )
        self.assertEqual(bot.tasks.hold_ticks, 0)


class _Phase0HoldCompletionTests(unittest.TestCase):
    """``crewmate.py`` currently marks a task ``resolved`` / ``COMPLETED``
    purely on the ``TASK_HOLD_TICKS`` timer decrementing to zero, with
    no server-side confirmation. Phase 3 replaces this with a
    confirmation gate (icon disappearance or task_progress advance)."""

    def test_hold_completion_requires_server_confirmation(self):
        bot = Bot(agent_id=0)
        bot.role = Role.CREWMATE
        bot.percep.phase = Phase.PLAYING
        # Seed a single task: active, on-screen, icon visible. Mimics
        # "bot is standing on a task rect" as far as the policy can
        # tell — except the server will not actually complete it
        # (e.g. it's assigned to another crewmate; the server simply
        # ignores the A-presses). We simulate that by never advancing
        # ``task_progress`` and never removing the icon.
        bot.tasks.resolved = [False]
        bot.tasks.states = [TaskState.NOT_DOING]
        bot.percep.tasks = [
            TaskInfo(
                index=0,
                x=0,
                y=0,
                icon_visible=True,
                arrow_visible=False,
                active=True,
                state=TaskState.NOT_DOING,
            )
        ]
        bot.percep.task_progress = 0.0

        policy = CrewmatePolicy()
        # First decide: enters the hold branch, returns A, sets hold_ticks.
        policy.decide(bot, game_map=None)
        # Drive the hold to completion — the existing code decrements
        # one tick per call, so call exactly TASK_HOLD_TICKS more times.
        for _ in range(TASK_HOLD_TICKS):
            # Keep the task state steady: still active, icon still
            # visible, task_progress unchanged. No external completion
            # signal of any kind.
            bot.percep.tick += 1
            policy.decide(bot, game_map=None)

        self.assertFalse(
            bot.tasks.resolved[0],
            "hold timer expiring alone must not mark a task resolved; "
            "require icon-disappearance or task_progress advance",
        )
        self.assertNotEqual(
            bot.tasks.states[0],
            TaskState.COMPLETED,
            "hold timer expiring alone must not mark a task COMPLETED",
        )


class Phase3HoldConfirmationTests(unittest.TestCase):
    """Positive-path tests for Phase 3: the hold-completion latch
    transitions through a confirmation window and only resolves the
    task when a server-side signal (``task_progress`` advance or
    icon-disappearance) arrives, or stays unresolved on deadline."""

    def _bot_on_active_task(self):
        """Synthetic bot standing on an icon-visible active task."""
        bot = Bot(agent_id=0)
        bot.role = Role.CREWMATE
        bot.percep.phase = Phase.PLAYING
        bot.tasks.resolved = [False]
        bot.tasks.states = [TaskState.NOT_DOING]
        bot.tasks.checkout = [True]
        bot.percep.tasks = [
            TaskInfo(
                index=0,
                x=0,
                y=0,
                icon_visible=True,
                arrow_visible=False,
                active=True,
                active_rect=True,
                state=TaskState.NOT_DOING,
            )
        ]
        bot.percep.task_progress = 0.0
        return bot

    def _drive_through_hold(self, policy, bot):
        """Drive a fresh bot through the full hold-timer window.
        Returns with ``hold_ticks == 0`` and
        ``confirming_index == 0``. ``bot.percep.tick`` is left at the
        tick where confirmation began."""
        policy.decide(bot, game_map=None)  # starts hold
        for _ in range(TASK_HOLD_TICKS):
            bot.percep.tick += 1
            policy.decide(bot, game_map=None)
        self.assertEqual(bot.tasks.hold_ticks, 0)
        self.assertEqual(bot.tasks.confirming_index, 0)

    def test_progress_advance_confirms_completion(self):
        # Phase 7: ``task_progress`` only confirms checkout-only holds
        # (``confirming_via_icon=False``). Use a checkout-triggered
        # hold setup: no icon, just rect-inside + checkout latch.
        bot = self._bot_on_active_task()
        bot.percep.tasks[0].icon_visible = False
        policy = CrewmatePolicy()
        self._drive_through_hold(policy, bot)
        self.assertFalse(
            bot.tasks.confirming_via_icon,
            "precondition: hold must be checkout-only for this test",
        )

        # Next tick: server reports a progress advance. Confirmation
        # fires at the top of ``decide``.
        bot.percep.tick += 1
        bot.percep.task_progress = 0.1  # anything above epsilon
        policy.decide(bot, game_map=None)

        self.assertTrue(bot.tasks.resolved[0])
        self.assertEqual(bot.tasks.states[0], TaskState.COMPLETED)
        self.assertEqual(bot.tasks.confirming_index, -1)

    def test_progress_advance_does_not_confirm_icon_hold(self):
        """Phase 7 false-positive elimination: an icon-triggered hold
        ignores ``task_progress`` advance because the bar is
        team-wide and a sibling completing during our window would
        otherwise spuriously confirm. Only the icon-disappearance
        signal can confirm this kind of hold."""
        bot = self._bot_on_active_task()
        # Default setup has icon_visible=True, so confirming_via_icon
        # should be True after _drive_through_hold.
        policy = CrewmatePolicy()
        self._drive_through_hold(policy, bot)
        self.assertTrue(
            bot.tasks.confirming_via_icon,
            "precondition: hold must be icon-triggered for this test",
        )

        # Sibling-bot scenario: icon stays visible (server hasn't
        # marked our task done) but task_progress jumps.
        bot.percep.tick += 1
        bot.percep.task_progress = 0.5  # huge advance, would have confirmed pre-Phase-7
        policy.decide(bot, game_map=None)

        self.assertFalse(
            bot.tasks.resolved[0],
            "icon-triggered hold must not confirm on task_progress advance alone",
        )

    def test_icon_disappearance_confirms_completion(self):
        bot = self._bot_on_active_task()
        policy = CrewmatePolicy()
        self._drive_through_hold(policy, bot)

        # Icon vanishes (server no longer renders it for this player)
        # but task_progress stays at 0.0 (e.g. the host's progress
        # bar is debounced). After ICON_MISS_COMPLETE_TICKS
        # consecutive misses while still in the rect, confirm.
        bot.percep.tasks[0].icon_visible = False
        for _ in range(ICON_MISS_COMPLETE_TICKS):
            bot.percep.tick += 1
            policy.decide(bot, game_map=None)
            if bot.tasks.resolved[0]:
                break

        self.assertTrue(bot.tasks.resolved[0])
        self.assertEqual(bot.tasks.states[0], TaskState.COMPLETED)

    def test_icon_miss_resets_when_icon_reappears(self):
        """Flickering sprite matches (icon absent one tick, present
        the next) must not accumulate toward the confirmation
        threshold."""
        bot = self._bot_on_active_task()
        policy = CrewmatePolicy()
        self._drive_through_hold(policy, bot)

        # Alternate icon-missing / icon-visible for ICON_MISS_COMPLETE_TICKS
        # * 2 ticks. We should never confirm (no sustained miss).
        for i in range(ICON_MISS_COMPLETE_TICKS * 2):
            bot.percep.tick += 1
            bot.percep.tasks[0].icon_visible = bool(i % 2)
            policy.decide(bot, game_map=None)
            # Confirmation deadline may elapse; that clears confirming_index
            # but the test's assertion is about NOT marking resolved.
        self.assertFalse(
            bot.tasks.resolved[0],
            "alternating icon visibility must not confirm completion",
        )

    def test_timeout_leaves_task_unresolved_and_clears_checkout(self):
        bot = self._bot_on_active_task()
        policy = CrewmatePolicy()
        self._drive_through_hold(policy, bot)

        # Hold just transitioned to confirming. Drive through the
        # full window without any signal. Icon stays visible (so the
        # icon-miss counter stays at 0), task_progress stays at 0.
        for _ in range(HOLD_CONFIRM_WINDOW_TICKS + 2):
            bot.percep.tick += 1
            policy.decide(bot, game_map=None)

        self.assertFalse(bot.tasks.resolved[0])
        self.assertNotEqual(bot.tasks.states[0], TaskState.COMPLETED)
        self.assertEqual(bot.tasks.confirming_index, -1)
        self.assertFalse(
            bot.tasks.checkout[0],
            "deadline timeout should un-latch checkout so the bot "
            "doesn't pathologically re-hold the same task",
        )

    def test_checkout_hold_cannot_confirm_via_icon_miss(self):
        """When the hold was triggered by a checkout-latched radar
        dot (no icon ever visible), the icon-miss signal must not
        fire — the icon may never have been renderable in the first
        place, so its absence means nothing."""
        bot = self._bot_on_active_task()
        # Override the default setup: no icon, only checkout.
        bot.percep.tasks[0].icon_visible = False
        policy = CrewmatePolicy()
        self._drive_through_hold(policy, bot)
        self.assertFalse(
            bot.tasks.confirming_via_icon,
            "hold from checkout-only evidence should not mark "
            "confirming_via_icon",
        )

        # Drive through the full confirmation window with icon absent
        # and no task_progress advance. Should NOT resolve — the
        # icon-miss path is disabled because the hold was
        # checkout-triggered.
        for _ in range(HOLD_CONFIRM_WINDOW_TICKS + 2):
            bot.percep.tick += 1
            policy.decide(bot, game_map=None)

        self.assertFalse(
            bot.tasks.resolved[0],
            "checkout-only hold must not confirm on icon-miss alone",
        )

    def test_restart_hold_does_not_lose_progress_signal(self):
        """Sanity for the checkout-only path: if task_progress
        advances *during* the hold, the confirmation window after
        hold-end still catches it because confirmation checks
        progress against the pre-hold snapshot.

        Post-Phase-7 this only applies to checkout-only holds —
        icon-triggered holds ignore ``task_progress`` entirely.
        """
        bot = self._bot_on_active_task()
        bot.percep.tasks[0].icon_visible = False  # checkout-only setup
        policy = CrewmatePolicy()
        # Start hold.
        policy.decide(bot, game_map=None)
        self.assertEqual(bot.tasks.pre_hold_progress, 0.0)
        self.assertFalse(bot.tasks.confirming_via_icon)

        # Halfway through the hold, task_progress advances.
        for _ in range(TASK_HOLD_TICKS // 2):
            bot.percep.tick += 1
            policy.decide(bot, game_map=None)
        bot.percep.task_progress = 0.1

        # Drive through the rest of the hold.
        for _ in range(TASK_HOLD_TICKS - TASK_HOLD_TICKS // 2):
            bot.percep.tick += 1
            policy.decide(bot, game_map=None)

        # Hold just ended → confirmation begun. Next decide checks
        # progress (allowed for checkout-only) and confirms.
        bot.percep.tick += 1
        policy.decide(bot, game_map=None)
        self.assertTrue(bot.tasks.resolved[0])


class Phase4MinorIssueTests(unittest.TestCase):
    """Phase 4 cleanups: arrow-only x/y, active tiebreak, patrol phase."""

    def test_off_screen_task_x_y_track_arrow(self):
        """4.1: when a task is off-screen, ``info.x`` / ``info.y``
        mirror ``arrow_x`` / ``arrow_y`` — readers that miss the
        ``icon_visible`` check don't see ``(0, 0)``."""
        station = TaskStation(index=0, name="t0", x=1000, y=1000, w=20, h=20)
        bot = _localized_bot_at(task_wx=100, task_wy=100)
        bot.percep.visible_task_icons = []
        cam_x = bot.percep.camera_x
        cam_y = bot.percep.camera_y
        _, proj_x, proj_y = _projected_radar_dot(station, cam_x, cam_y, 100, 100)
        bot.percep.radar_dots = [RadarDotMatch(x=proj_x, y=proj_y)]

        _populate(bot, _stub_map([station]))
        info = bot.percep.tasks[0]
        self.assertFalse(info.icon_visible)
        self.assertEqual((info.x, info.y), (info.arrow_x, info.arrow_y))
        self.assertEqual((info.x, info.y), (proj_x, proj_y))

    def test_actives_tiebreak_prefers_icon_visible(self):
        """4.2: when two tasks both qualify as ``active`` (player in
        rect + assignment evidence), prefer the icon-visible one over
        the checkout-only one."""
        # Two tasks at the same screen position so the
        # closest-to-centre tiebreaker doesn't decide it.
        bot = Bot(agent_id=0)
        bot.role = Role.CREWMATE
        bot.percep.phase = Phase.PLAYING
        bot.tasks.resolved = [False, False]
        bot.tasks.states = [TaskState.NOT_DOING, TaskState.NOT_DOING]
        bot.tasks.checkout = [True, True]
        # Index 0: checkout-only. Index 1: icon-visible.
        bot.percep.tasks = [
            TaskInfo(
                index=0, x=0, y=0,
                icon_visible=False, arrow_visible=False,
                active=True, active_rect=True,
                state=TaskState.NOT_DOING,
            ),
            TaskInfo(
                index=1, x=0, y=0,
                icon_visible=True, arrow_visible=False,
                active=True, active_rect=True,
                state=TaskState.NOT_DOING,
            ),
        ]

        chosen = base.best_actionable_task(bot)
        self.assertIsNotNone(chosen)
        self.assertEqual(
            chosen.index, 1,
            "icon-visible active must outrank checkout-only active",
        )

    def test_patrol_phases_differ_across_agent_ids(self):
        """4.4: patrol's quadrant rotation is keyed on ``agent_id`` so
        mixed-lobby modulabots don't all walk the same direction."""
        # Two bots with different agent_ids, same tick, no task
        # candidates → patrol fires for each. We compare the action
        # they emit.
        results = {}
        for aid in (0, 1, 2, 3):
            bot = Bot(agent_id=aid)
            bot.role = Role.CREWMATE
            bot.percep.phase = Phase.PLAYING
            bot.percep.tick = 0
            bot.rng_seed = 0
            # No tasks at all: best_actionable_task → None → patrol.
            bot.percep.tasks = []
            action = CrewmatePolicy().decide(bot, game_map=None)
            results[aid] = action
        # Not all four agents take the same direction (deterministic
        # rotation has 4 phases keyed on agent_id).
        self.assertGreater(
            len(set(results.values())),
            1,
            f"patrol should differ across agent_ids, got {results}",
        )


class Phase6NegativeEvidenceTests(unittest.TestCase):
    """Phase 6: icon-miss negative-evidence pruning. The pixel
    pipeline now runs a per-task negative pass that latches
    ``resolved[i] = True`` after :data:`ICON_MISS_THRESHOLD`
    consecutive frames of "clean view, no icon, no fuzzy match".

    Tests use the default blank frame + transparent sprite, so
    ``maybe_matches_sprite`` always returns ``False`` (sprite has
    zero opaque pixels). The strict-icon path also stays empty
    (``visible_task_icons`` left as []) — the only thing varying is
    whether the inspection rect is on-screen with margin.
    """

    def _bot_with_clear_view_of(self, station: TaskStation) -> Bot:
        """Place the bot's camera so the inspection rect for
        ``station`` sits comfortably inside the 128x128 viewport
        with full ``TASK_CLEAR_SCREEN_MARGIN`` slack on every
        side."""
        # Inspection rect is 16x16 centred on the icon position
        # (icon = task.x + task.w/2 - SPRITE_SIZE/2, task.y - SPRITE_SIZE - 2).
        # We want the rect at screen centre (~64, 64), with margin >= 8.
        # Solve for camera position:
        target_screen_x = 60
        target_screen_y = 60
        rect_world_x = station.x + station.w // 2 - 16 // 2
        rect_world_y = station.y - 16
        cam_x = rect_world_x - target_screen_x
        cam_y = rect_world_y - target_screen_y
        bot = Bot(agent_id=0)
        bot.role = Role.CREWMATE
        bot.percep.phase = Phase.PLAYING
        bot.percep.localized = True
        bot.percep.camera_lock = CameraLock.FRAME_MAP_LOCK
        bot.percep.camera_x = cam_x
        bot.percep.camera_y = cam_y
        bot.percep.visible_task_icons = []
        bot.percep.radar_dots = []
        return bot

    def test_clear_view_no_icon_no_maybe_resolves(self):
        station = TaskStation(index=0, name="t0", x=200, y=200, w=16, h=16)
        bot = self._bot_with_clear_view_of(station)

        for _ in range(ICON_MISS_THRESHOLD):
            bot.percep.tasks = []
            _populate(bot, _stub_map([station]))

        self.assertTrue(
            bot.tasks.resolved[0],
            "clean view + no strict + no fuzzy → resolved=True after threshold",
        )
        self.assertFalse(
            bot.tasks.checkout[0],
            "checkout latch should be cleared when we resolve as not-mine",
        )
        self.assertEqual(bot.tasks.icon_misses[0], 0, "counter resets on latch")

    def test_clipped_inspection_rect_does_not_count(self):
        """When the inspection rect is at the screen edge / clipped,
        the absence isn't trustworthy and we don't accumulate misses."""
        station = TaskStation(index=0, name="t0", x=200, y=200, w=16, h=16)
        bot = self._bot_with_clear_view_of(station)
        # Slide the camera so the inspection rect is partially
        # off-screen — set cam_x so the rect's screen-x is < margin.
        rect_world_x = station.x + station.w // 2 - 16 // 2
        bot.percep.camera_x = rect_world_x  # rect at screen-x = 0

        for _ in range(ICON_MISS_THRESHOLD * 3):
            bot.percep.tasks = []
            _populate(bot, _stub_map([station]))

        self.assertFalse(
            bot.tasks.resolved[0],
            "clipped inspection rect must not accumulate misses",
        )
        self.assertEqual(bot.tasks.icon_misses[0], 0)

    def test_icon_miss_skipped_during_hold(self):
        """The negative-evidence pass must not run while we're holding
        / confirming on the task — Phase 3's logic owns the icon
        signal there. Otherwise a long hold would itself satisfy the
        miss threshold and false-fire."""
        station = TaskStation(index=0, name="t0", x=200, y=200, w=16, h=16)
        bot = self._bot_with_clear_view_of(station)
        bot.tasks.hold_index = 0

        for _ in range(ICON_MISS_THRESHOLD * 2):
            bot.percep.tasks = []
            _populate(bot, _stub_map([station]))

        self.assertFalse(
            bot.tasks.resolved[0],
            "negative-evidence latch must not fire while hold_index points at this task",
        )
        self.assertEqual(bot.tasks.icon_misses[0], 0)

    def test_strict_icon_match_resets_counter(self):
        """A strict icon match (server is rendering it) resets the
        miss counter — even if a few prior frames missed (e.g. brief
        sprite occlusion)."""
        from modulabot.state import IconMatch

        station = TaskStation(index=0, name="t0", x=200, y=200, w=16, h=16)
        bot = self._bot_with_clear_view_of(station)

        # Half the threshold worth of misses.
        for _ in range(ICON_MISS_THRESHOLD // 2):
            bot.percep.tasks = []
            _populate(bot, _stub_map([station]))
        prior_misses = bot.tasks.icon_misses[0]
        self.assertGreater(prior_misses, 0, "precondition: should have accumulated misses")

        # Now drop in a strict match at the projected icon position.
        cam_x = bot.percep.camera_x
        cam_y = bot.percep.camera_y
        proj_icon_x = station.cx - cam_x
        proj_icon_y = station.y - cam_y
        bot.percep.visible_task_icons = [
            IconMatch(x=proj_icon_x - 6, y=proj_icon_y - 6)
        ]
        bot.percep.tasks = []
        _populate(bot, _stub_map([station]))

        self.assertEqual(bot.tasks.icon_misses[0], 0, "strict match resets counter")
        self.assertFalse(bot.tasks.resolved[0])

    def test_resolved_task_filtered_from_selection(self):
        """End-to-end: once a task has been latched as not-mine,
        ``best_actionable_task`` never returns it again."""
        station = TaskStation(index=0, name="t0", x=200, y=200, w=16, h=16)
        bot = self._bot_with_clear_view_of(station)

        # Drive to the latch.
        for _ in range(ICON_MISS_THRESHOLD):
            bot.percep.tasks = []
            _populate(bot, _stub_map([station]))
        self.assertTrue(bot.tasks.resolved[0])

        # Even with a fresh radar dot landing on the task's projected
        # edge, the resolved-not-mine latch should keep it out.
        # (In Nim this is a one-way latch; if we wanted "real icon
        # overrides" recovery we'd need extra logic.)
        bot.percep.tasks = []
        bot.percep.camera_x -= 200  # push task off-screen
        _, proj_x, proj_y = _projected_radar_dot(
            station, bot.percep.camera_x, bot.percep.camera_y, 100, 100
        )
        bot.percep.radar_dots = [RadarDotMatch(x=proj_x, y=proj_y)]
        _populate(bot, _stub_map([station]))

        chosen = base.best_actionable_task(bot)
        self.assertIsNone(
            chosen,
            "resolved-not-mine task must be filtered from candidate set",
        )


if __name__ == "__main__":
    unittest.main()
