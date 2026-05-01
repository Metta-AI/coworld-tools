"""Integration tests for the pathfinding → policy wiring.

These tests exercise :func:`modulabot.policies.base.navigate_to_world_goal`
— the new bit that routes every policy's movement through
:mod:`modulabot.path` A\\* when a world position + locked camera are
available. They're the regression net for "did we actually wire
the pathfinder in, or does every policy still emit screen-space
greedy moves?"

Four layers:

1. :func:`set_world_goal` / :func:`clear_goal` mutate the goal
   sub-record correctly and invalidate the path cache on goal
   change.
2. :func:`navigate_to_world_goal` recomputes A\\* at the expected
   cadence (replan interval + move threshold + goal change), and
   caches between calls.
3. End-to-end: crewmate policy with a wall between start and the
   first task picks a direction that routes *around* the wall.
4. Graceful fallback: no ``game_map`` / not localized degrades to
   direct world-delta steering without crashing.
"""

from __future__ import annotations

import unittest

import numpy as np

from modulabot import actions
from modulabot.data import (
    MAP_HEIGHT,
    MAP_WIDTH,
    GameMap,
    Rect,
    TaskStation,
    load_reference_data,
)
from modulabot.geometry import camera_x_for_world, camera_y_for_world
from modulabot.policies import CrewmatePolicy
from modulabot.policies.base import (
    best_actionable_task,
    clear_goal,
    navigate_to_world_goal,
    set_world_goal,
    world_pos_from_screen,
)
from modulabot.state import (
    Bot,
    Perception,
    Phase,
    PlayerSighting,
    Role,
    TaskInfo,
    TaskState,
)
from modulabot.tuning import (
    PATH_REPLAN_INTERVAL,
    PATH_REPLAN_MOVE_THRESHOLD,
    TASK_COMMIT_TICKS,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _synthetic_map(walls: list[tuple[int, int]] | None = None) -> GameMap:
    """Build a GameMap with a fully-walkable mask minus any `walls`.

    One dummy task at (200, 200) so crewmate goal-setting code can
    project through ``game_map.tasks[index]`` without crashing.
    """
    mask = np.ones((MAP_HEIGHT, MAP_WIDTH), dtype=bool)
    for x, y in walls or ():
        mask[y, x] = False
    return GameMap(
        width=MAP_WIDTH,
        height=MAP_HEIGHT,
        button=Rect(x=0, y=0, w=1, h=1),
        home=(0, 0),
        tasks=(TaskStation(index=0, name="dummy", x=195, y=195, w=10, h=10),),
        rooms=(),
        map_pixels=np.zeros((MAP_HEIGHT, MAP_WIDTH), dtype=np.uint8),
        walk_mask=mask,
        wall_mask=(~mask).astype(bool),
    )


def _bot_at(world_x: int, world_y: int, *, localized: bool = True) -> Bot:
    """Build a bot whose perception puts the player at (world_x, world_y)."""
    bot = Bot(agent_id=0, role=Role.CREWMATE)
    bot.percep.phase = Phase.PLAYING
    bot.percep.localized = localized
    if localized:
        bot.percep.camera_x = camera_x_for_world(world_x)
        bot.percep.camera_y = camera_y_for_world(world_y)
    return bot


# ---------------------------------------------------------------------------
# Goal helpers
# ---------------------------------------------------------------------------


class SetWorldGoalTests(unittest.TestCase):
    def test_sets_world_and_screen_fields(self):
        bot = _bot_at(100, 100)
        set_world_goal(bot, 200, 150, name="task_3", index=3)
        g = bot.goal
        self.assertTrue(g.has_world)
        self.assertTrue(g.has)
        self.assertEqual((g.world_x, g.world_y), (200, 150))
        self.assertEqual((g.x, g.y), (200, 150))  # screen defaults to world
        self.assertEqual(g.name, "task_3")
        self.assertEqual(g.index, 3)

    def test_explicit_screen_coords_preserved(self):
        bot = _bot_at(100, 100)
        set_world_goal(bot, 200, 150, screen_x=50, screen_y=60)
        self.assertEqual((bot.goal.x, bot.goal.y), (50, 60))

    def test_changing_world_goal_invalidates_cache(self):
        """A goal change must drop the cached A\\* path so the next
        ``navigate_to_world_goal`` replans from scratch. Tests
        :data:`~modulabot.tuning.PATH_REPLAN_INTERVAL` doesn't
        accidentally protect stale paths."""
        bot = _bot_at(100, 100)
        set_world_goal(bot, 200, 200)
        bot.goal.path = [object()]  # pretend we had a plan
        bot.goal.has_path_step = True
        bot.goal.path_plan_tick = 0
        set_world_goal(bot, 300, 300)  # different goal
        self.assertEqual(bot.goal.path, [])
        self.assertFalse(bot.goal.has_path_step)
        self.assertEqual(bot.goal.path_plan_tick, -1)

    def test_same_world_goal_preserves_cache(self):
        """Re-setting the same goal doesn't drop the plan —
        otherwise every policy tick would wipe the cache and
        re-plan regardless of ``PATH_REPLAN_INTERVAL``."""
        bot = _bot_at(100, 100)
        set_world_goal(bot, 200, 200)
        sentinel_path = [object()]
        bot.goal.path = sentinel_path
        bot.goal.has_path_step = True
        bot.goal.path_plan_tick = 5
        set_world_goal(bot, 200, 200)
        # Same list object is preserved — the check is identity, not
        # equality, so a future optimisation that allocates a new
        # empty list on no-op set_world_goal breaks this test loudly.
        self.assertIs(bot.goal.path, sentinel_path)
        self.assertTrue(bot.goal.has_path_step)
        self.assertEqual(bot.goal.path_plan_tick, 5)


class ClearGoalTests(unittest.TestCase):
    def test_clears_everything(self):
        bot = _bot_at(100, 100)
        set_world_goal(bot, 200, 200)
        bot.goal.path = [object()]
        bot.goal.has_path_step = True
        clear_goal(bot)
        g = bot.goal
        self.assertFalse(g.has)
        self.assertFalse(g.has_world)
        self.assertFalse(g.has_path_step)
        self.assertEqual(g.path, [])


class WorldPosFromScreenTests(unittest.TestCase):
    def test_projects_via_camera(self):
        percep = Perception()
        percep.camera_x = 500
        percep.camera_y = 100
        percep.localized = True
        self.assertEqual(world_pos_from_screen(percep, 30, 40), (530, 140))

    def test_unlocalized_returns_sentinel(self):
        percep = Perception()
        percep.localized = False
        self.assertEqual(world_pos_from_screen(percep, 30, 40), (-1, -1))


# ---------------------------------------------------------------------------
# navigate_to_world_goal
# ---------------------------------------------------------------------------


class NavigateToWorldGoalTests(unittest.TestCase):
    def test_no_goal_returns_noop(self):
        bot = _bot_at(100, 100)
        self.assertEqual(navigate_to_world_goal(bot, _synthetic_map()), actions.NOOP)

    def test_caches_first_plan(self):
        """Two back-to-back calls with the same goal + stationary
        bot should only recompute A\\* once — the second call
        reuses the cached path until ``PATH_REPLAN_INTERVAL`` ticks
        elapse or we move past the threshold.
        """
        bot = _bot_at(100, 100)
        game_map = _synthetic_map()
        set_world_goal(bot, 150, 100)
        bot.percep.tick = 0
        navigate_to_world_goal(bot, game_map)
        first_plan_tick = bot.goal.path_plan_tick
        first_path_obj = bot.goal.path
        # Advance tick by 1 (below replan interval) — no replan.
        bot.percep.tick = 1
        navigate_to_world_goal(bot, game_map)
        self.assertEqual(bot.goal.path_plan_tick, first_plan_tick)
        self.assertIs(bot.goal.path, first_path_obj)

    def test_replans_after_interval(self):
        bot = _bot_at(100, 100)
        game_map = _synthetic_map()
        set_world_goal(bot, 150, 100)
        bot.percep.tick = 0
        navigate_to_world_goal(bot, game_map)
        first_path_obj = bot.goal.path
        bot.percep.tick = PATH_REPLAN_INTERVAL  # elapsed == interval → replan
        navigate_to_world_goal(bot, game_map)
        self.assertIsNot(bot.goal.path, first_path_obj)
        self.assertEqual(bot.goal.path_plan_tick, PATH_REPLAN_INTERVAL)

    def test_replans_after_moving_threshold(self):
        """Moving > PATH_REPLAN_MOVE_THRESHOLD from the plan anchor
        forces a replan even inside the interval. Guards against
        teleports / rubber-band jumps after interstitials."""
        bot = _bot_at(100, 100)
        game_map = _synthetic_map()
        set_world_goal(bot, 400, 100)
        bot.percep.tick = 0
        navigate_to_world_goal(bot, game_map)
        # Teleport the camera; tick unchanged.
        bot.percep.camera_x = camera_x_for_world(100 + PATH_REPLAN_MOVE_THRESHOLD + 5)
        bot.percep.tick = 1
        first_anchor = (bot.goal.path_plan_self_x, bot.goal.path_plan_self_y)
        navigate_to_world_goal(bot, game_map)
        new_anchor = (bot.goal.path_plan_self_x, bot.goal.path_plan_self_y)
        self.assertNotEqual(first_anchor, new_anchor)

    def test_pathfinds_around_wall(self):
        """A\\* must compute a wall-free path, not a straight shot.

        The first emitted action may still be ``DOWN`` (the path
        goes south until it's safe to sidestep east around a
        10-wide wall), so the assertion is on the path contents —
        no waypoint overlaps a wall — rather than on which direction
        the first frame emits.
        """
        walls = [(x, 100) for x in range(95, 106)]
        wall_set = set(walls)
        game_map = _synthetic_map(walls)
        bot = _bot_at(100, 90)
        set_world_goal(bot, 100, 110)
        bot.percep.tick = 0
        navigate_to_world_goal(bot, game_map)
        self.assertTrue(bot.goal.has_path_step)
        self.assertGreater(
            len(bot.goal.path),
            abs(100 - 110),
            "path should be longer than Manhattan distance (forced to detour)",
        )
        for step in bot.goal.path:
            self.assertNotIn(
                (step.x, step.y),
                wall_set,
                f"path waypoint {(step.x, step.y)} overlaps a wall",
            )
        # End of path is the goal.
        last = bot.goal.path[-1]
        self.assertEqual((last.x, last.y), (100, 110))

    def test_unreachable_goal_falls_back_to_direct(self):
        """A goal enclosed by walls is unreachable — the navigator
        should keep producing an actionable direction (aimed at the
        goal in straight-line) rather than freezing on NOOP. That
        lets the jiggle handle wall-banging and retry later."""
        # Box the goal in at (150, 150) with walls on all 4 sides.
        walls = [(150 + dx, 150 + dy) for dx in (-1, 0, 1) for dy in (-1, 0, 1) if (dx, dy) != (0, 0)]
        # Actually easier: make (150, 150) itself a wall (impassable goal).
        walls = [(150, 150)]
        game_map = _synthetic_map(walls)
        bot = _bot_at(100, 100)
        set_world_goal(bot, 150, 150)
        bot.percep.tick = 0
        action = navigate_to_world_goal(bot, game_map)
        # Goal is SE so direct steering picks RIGHT or DOWN (dx=50, dy=50).
        self.assertIn(action, (actions.RIGHT, actions.DOWN))
        self.assertFalse(bot.goal.has_path_step)  # no valid path

    def test_degrades_when_not_localized(self):
        """Un-localized bot with a world goal falls back to
        screen-centre-to-world-delta steering — same API as before
        the wiring, so legacy state-obs callers keep working."""
        bot = _bot_at(100, 100, localized=False)
        set_world_goal(bot, 100, 200)
        # Without localization, "world" coords in
        # ``_greedy_world_delta`` are relative to the screen centre.
        # Goal at y=200 vs CENTER_Y=64 means a downward delta.
        action = navigate_to_world_goal(bot, _synthetic_map())
        self.assertEqual(action, actions.DOWN)

    def test_degrades_when_no_game_map(self):
        """Same — passing None for game_map falls through to greedy,
        which is what the state-obs policy tests rely on."""
        bot = _bot_at(100, 100)
        set_world_goal(bot, 200, 100)
        self.assertEqual(navigate_to_world_goal(bot, None), actions.RIGHT)


# ---------------------------------------------------------------------------
# End-to-end: crewmate policy routes around a wall
# ---------------------------------------------------------------------------


class CrewmatePathingTests(unittest.TestCase):
    """The headline test: a crewmate with a visible off-screen task
    on the other side of a wall chooses a lateral direction, not
    straight into the wall.

    Before the wiring, the policy would compute
    ``move_toward(task.arrow_x, task.arrow_y)`` where
    ``arrow_*`` was a screen-edge pixel in the direction of the
    task — so the bot walked straight at the wall. After the
    wiring, the policy runs A\\* and emits a waypoint direction
    that sidesteps.
    """

    def test_navigates_around_wall_to_task(self):
        # Wall between player and task.
        walls = [(x, 100) for x in range(95, 106)]
        # Build a GameMap with the wall + a single task at (100, 110).
        mask = np.ones((MAP_HEIGHT, MAP_WIDTH), dtype=bool)
        for x, y in walls:
            mask[y, x] = False
        game_map = GameMap(
            width=MAP_WIDTH,
            height=MAP_HEIGHT,
            button=Rect(x=0, y=0, w=1, h=1),
            home=(0, 0),
            tasks=(TaskStation(index=0, name="across", x=95, y=105, w=10, h=10),),
            rooms=(),
            map_pixels=np.zeros((MAP_HEIGHT, MAP_WIDTH), dtype=np.uint8),
            walk_mask=mask,
            wall_mask=(~mask).astype(bool),
        )

        bot = _bot_at(100, 90)
        # Prime Tasks sub-record (the policy resets it lazily).
        bot.tasks.resolved = [False]
        bot.tasks.states = [TaskState.MANDATORY]
        # Feed the policy a TaskInfo that points at the task station:
        # ``icon_visible=True`` so the picker fires; screen coords are
        # the projected task cx/cy - camera for continuity with the
        # state-obs harness.
        from modulabot.geometry import (
            PLAYER_SCREEN_X,
            PLAYER_SCREEN_Y,
            player_world_x,
            player_world_y,
        )
        cam_x, cam_y = bot.percep.camera_x, bot.percep.camera_y
        task_info = TaskInfo(
            index=0,
            x=game_map.tasks[0].cx - cam_x,
            y=game_map.tasks[0].cy - cam_y,
            icon_visible=True,
            active=False,
            state=TaskState.MANDATORY,
        )
        bot.percep.tasks = [task_info]
        bot.percep.players = [
            PlayerSighting(
                slot=-1,
                x=PLAYER_SCREEN_X,
                y=PLAYER_SCREEN_Y,
                color=bot.identity.self_color,
                alive=True,
                is_self=True,
            )
        ]

        policy = CrewmatePolicy()
        action = policy.decide(bot, game_map)

        # The goal must be the task's world position, and the cached
        # path should have content.
        self.assertEqual(
            (bot.goal.world_x, bot.goal.world_y),
            (game_map.tasks[0].cx, game_map.tasks[0].cy),
        )
        self.assertTrue(bot.goal.has_path_step)
        self.assertGreater(len(bot.goal.path), 0)

        # Path integrity: no waypoint overlaps the wall row. The
        # first emitted action may be DOWN (A\* legitimately takes
        # us south until we clear the wall's end, then east, then
        # south again); it's the *path* that proves we're not just
        # walking into the wall on a greedy move.
        wall_set = set(walls)
        for step in bot.goal.path:
            self.assertNotIn(
                (step.x, step.y),
                wall_set,
                f"crewmate path waypoint {(step.x, step.y)} overlaps a wall",
            )
        # And we emitted a directional action rather than NOOP.
        self.assertIn(
            action,
            (
                actions.UP,
                actions.DOWN,
                actions.LEFT,
                actions.RIGHT,
                actions.UP_A,
                actions.DOWN_A,
                actions.LEFT_A,
                actions.RIGHT_A,
            ),
        )


# ---------------------------------------------------------------------------
# Real map wiring: instantiate a Localizer + real map and confirm A*
# actually runs end-to-end with the shipped data.
# ---------------------------------------------------------------------------


class RealMapWiringTests(unittest.TestCase):
    """Sanity-check on the shipped skeld2 map data — confirms nothing
    in the wiring forgot a data conversion between world coords,
    camera offsets, and the walk mask orientation."""

    @classmethod
    def setUpClass(cls):
        cls.data = load_reference_data()

    def test_crewmate_produces_path_on_real_map(self):
        # Pick a walkable start.
        walkable = np.argwhere(self.data.map.walk_mask)
        sy, sx = (int(v) for v in walkable[len(walkable) // 3])
        gy, gx = (int(v) for v in walkable[(2 * len(walkable)) // 3])

        bot = _bot_at(sx, sy)
        bot.tasks.resolved = [False] * len(self.data.map.tasks)
        bot.tasks.states = [TaskState.MANDATORY] * len(self.data.map.tasks)

        # Goal = first reachable task.
        task0 = self.data.map.tasks[0]
        cam_x, cam_y = bot.percep.camera_x, bot.percep.camera_y
        bot.percep.tasks = [
            TaskInfo(
                index=0,
                x=task0.cx - cam_x,
                y=task0.cy - cam_y,
                icon_visible=True,
                active=False,
                state=TaskState.MANDATORY,
            )
        ]
        bot.percep.players = [
            PlayerSighting(
                slot=-1,
                x=64,
                y=64,
                color=bot.identity.self_color,
                alive=True,
                is_self=True,
            )
        ]

        policy = CrewmatePolicy()
        action = policy.decide(bot, self.data.map)

        # The action should be directional (the task is far away on
        # the real map; we won't be arriving inside one tick).
        self.assertIn(
            action,
            (
                actions.UP,
                actions.DOWN,
                actions.LEFT,
                actions.RIGHT,
                actions.UP_A,
                actions.DOWN_A,
                actions.LEFT_A,
                actions.RIGHT_A,
            ),
            f"expected a directional action, got {action}",
        )
        # And a path was computed.
        self.assertTrue(bot.goal.has_path_step)
        self.assertGreater(len(bot.goal.path), 0)


# ---------------------------------------------------------------------------
# Task-selection hysteresis: ``best_actionable_task`` must not flip its pick
# between frames when perception flickers. Before this regression net the
# crewmate's chosen target oscillated ~20+ times over a 500-tick capture,
# invalidating the A\* path every flip and leaving the bot standing still
# indecisively. See ``best_actionable_task`` docstring for the fix.
# ---------------------------------------------------------------------------


def _make_task_info(
    index: int,
    *,
    icon_visible: bool = False,
    arrow_visible: bool = False,
    active: bool = False,
    x: int = 0,
    y: int = 0,
    arrow_x: int = 0,
    arrow_y: int = 0,
    state: TaskState = TaskState.MANDATORY,
) -> TaskInfo:
    return TaskInfo(
        index=index,
        x=x,
        y=y,
        arrow_x=arrow_x,
        arrow_y=arrow_y,
        icon_visible=icon_visible,
        arrow_visible=arrow_visible,
        active=active,
        state=state,
    )


def _prime_task_lists(bot: Bot, count: int) -> None:
    """Lazy-init mirrors what ``_populate_tasks_from_camera`` does."""
    bot.tasks.resolved = [False] * count
    bot.tasks.states = [TaskState.MANDATORY] * count


class BestActionableTaskHysteresisTests(unittest.TestCase):
    def test_commits_to_first_pick(self):
        bot = _bot_at(100, 100)
        _prime_task_lists(bot, 3)
        bot.percep.tick = 10
        # Two arrow-visible tasks; task 1's arrow sits closer to the
        # screen centre (CENTER_X/Y = 64) so ``_pick_best`` picks it.
        # What we're really asserting: the pick is stable and records
        # chosen_index/chosen_since_tick for the next tick.
        bot.percep.tasks = [
            _make_task_info(0, arrow_visible=True, arrow_x=10, arrow_y=10),
            _make_task_info(1, arrow_visible=True, arrow_x=60, arrow_y=60),
        ]
        first = best_actionable_task(bot)
        self.assertEqual(first.index, 1)
        self.assertEqual(bot.tasks.chosen_index, 1)
        self.assertEqual(bot.tasks.chosen_since_tick, 10)

    def test_sticks_within_commit_window(self):
        """A sprite-match flicker that drops our committed task from
        ``icons`` into ``arrows`` (or even removes it altogether in the
        candidate tie for closest) must not flip the selection inside
        the commit window. This is the direct regression for the
        "crewmate jitters in place" bug."""
        bot = _bot_at(100, 100)
        _prime_task_lists(bot, 3)
        bot.percep.tick = 0
        # Tick 0: commit to task 1.
        bot.percep.tasks = [
            _make_task_info(0, arrow_visible=True, arrow_x=120, arrow_y=120),
            _make_task_info(1, icon_visible=True, x=64, y=64),
        ]
        first = best_actionable_task(bot)
        self.assertEqual(first.index, 1)

        # Tick 1: sprite-match flicker — task 1's icon disappears, and
        # a closer icon on task 0 appears. Naive ``min`` would switch.
        # Hysteresis says stick with 1 until commit window elapses.
        bot.percep.tick = 1
        bot.percep.tasks = [
            _make_task_info(0, icon_visible=True, x=32, y=32),
            _make_task_info(1, arrow_visible=True, arrow_x=127, arrow_y=64),
        ]
        second = best_actionable_task(bot)
        self.assertEqual(second.index, 1, "committed target must stick under flicker")

    def test_releases_after_commit_window(self):
        """Once the commit window elapses, an arrow→icon upgrade is
        allowed (a better target actually became visible; switching
        is worthwhile now)."""
        bot = _bot_at(100, 100)
        _prime_task_lists(bot, 3)
        bot.percep.tick = 0
        bot.percep.tasks = [
            _make_task_info(0, arrow_visible=True, arrow_x=120, arrow_y=120),
            _make_task_info(1, arrow_visible=True, arrow_x=10, arrow_y=10),
        ]
        first = best_actionable_task(bot)
        self.assertEqual(first.index, 1)

        # Fast-forward past the commit window; now task 0 has an icon.
        bot.percep.tick = TASK_COMMIT_TICKS + 1
        bot.percep.tasks = [
            _make_task_info(0, icon_visible=True, x=32, y=32),
            _make_task_info(1, arrow_visible=True, arrow_x=10, arrow_y=10),
        ]
        second = best_actionable_task(bot)
        self.assertEqual(second.index, 0, "arrow→icon upgrade after commit expiry")

    def test_active_task_always_wins(self):
        """An ``active`` task (player standing on its rect) should win
        immediately even mid-commit — pressing A is free, don't waste it."""
        bot = _bot_at(100, 100)
        _prime_task_lists(bot, 3)
        bot.percep.tick = 5
        bot.percep.tasks = [
            _make_task_info(0, icon_visible=True, x=32, y=32),
        ]
        best_actionable_task(bot)  # commit to 0
        self.assertEqual(bot.tasks.chosen_index, 0)

        # Next tick: we've walked onto task 2's rect. Should win
        # immediately despite being mid-commit to task 0.
        bot.percep.tick = 6
        bot.percep.tasks = [
            _make_task_info(0, icon_visible=True, x=32, y=32),
            _make_task_info(2, active=True, x=64, y=64),
        ]
        chosen = best_actionable_task(bot)
        self.assertEqual(chosen.index, 2)

    def test_commit_clears_when_task_resolved(self):
        """When the committed task vanishes from candidates (resolved
        off-policy, or map changed), the commit must drop so a fresh
        pick happens next tick."""
        bot = _bot_at(100, 100)
        _prime_task_lists(bot, 3)
        bot.percep.tick = 0
        bot.percep.tasks = [
            _make_task_info(1, icon_visible=True, x=64, y=64),
        ]
        best_actionable_task(bot)
        self.assertEqual(bot.tasks.chosen_index, 1)

        # Resolve task 1 externally. ``_keep`` now filters it out.
        bot.tasks.resolved[1] = True
        bot.percep.tick = 1
        bot.percep.tasks = [
            _make_task_info(1, icon_visible=True, x=64, y=64),
            _make_task_info(0, arrow_visible=True, arrow_x=10, arrow_y=10),
        ]
        chosen = best_actionable_task(bot)
        self.assertEqual(chosen.index, 0)
        self.assertEqual(bot.tasks.chosen_since_tick, 1)


if __name__ == "__main__":
    unittest.main()
