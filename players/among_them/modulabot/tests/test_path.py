"""Tests for :mod:`modulabot.path` — A\\* pathfinding on the walk mask.

Three layers, mirroring how the other perception-module tests are
organised:

1. **Pure helpers** — :func:`passable`, :func:`heuristic`,
   :func:`choose_path_step`. Small deterministic cases.
2. **Synthetic map tests** — build a tiny walk mask with a known
   obstacle, run :func:`find_path`, confirm the route avoids the
   wall. No dependency on the shipped skeld2 map; the map is built
   inline in each test so the geometry is obvious from reading the
   code.
3. **Real-map integration + perf guard** — run A\\* between two
   known-walkable cells on the actual game map. Asserts success and
   a loose wall-clock budget so we catch gross regressions (e.g.
   accidentally dropping the ``closed`` short-circuit).
"""

from __future__ import annotations

import time
import unittest

import numpy as np

from modulabot.data import (
    MAP_HEIGHT,
    MAP_WIDTH,
    GameMap,
    Rect,
    load_reference_data,
)
from modulabot.geometry import camera_x_for_world, camera_y_for_world
from modulabot.state import Perception, PathStep
from modulabot import path


def _make_synthetic_map(walk_mask: np.ndarray) -> GameMap:
    """Build a :class:`~modulabot.data.GameMap` with the given walk mask.

    Every field the path module doesn't read is filled with a
    placeholder — if the pathfinder ever starts consulting
    ``map_pixels`` or ``wall_mask`` this factory will need
    widening, but that's an intentional break point.
    """
    h, w = walk_mask.shape
    return GameMap(
        width=w,
        height=h,
        button=Rect(x=0, y=0, w=1, h=1),
        home=(0, 0),
        tasks=(),
        rooms=(),
        map_pixels=np.zeros((h, w), dtype=np.uint8),
        walk_mask=walk_mask.astype(bool),
        wall_mask=(~walk_mask).astype(bool),
    )


def _percep_at(x: int, y: int) -> Perception:
    """Build a minimal Perception where ``player_world_*`` reports
    the requested world coordinate."""
    p = Perception()
    p.camera_x = camera_x_for_world(x)
    p.camera_y = camera_y_for_world(y)
    p.localized = True
    return p


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


class PassableTests(unittest.TestCase):
    def test_respects_walk_mask(self):
        mask = np.ones((MAP_HEIGHT, MAP_WIDTH), dtype=bool)
        mask[100, 100] = False
        game_map = _make_synthetic_map(mask)
        self.assertTrue(path.passable(game_map, 99, 100))
        self.assertFalse(path.passable(game_map, 100, 100))

    def test_rejects_negative_coordinates(self):
        game_map = _make_synthetic_map(np.ones((MAP_HEIGHT, MAP_WIDTH), dtype=bool))
        self.assertFalse(path.passable(game_map, -1, 0))
        self.assertFalse(path.passable(game_map, 0, -1))

    def test_rejects_right_and_bottom_edges(self):
        """Nim's CollisionW margin excludes the outermost column +
        row even when the mask is all True. Ports the same rule."""
        game_map = _make_synthetic_map(np.ones((MAP_HEIGHT, MAP_WIDTH), dtype=bool))
        self.assertFalse(path.passable(game_map, MAP_WIDTH - 1, 0))
        self.assertFalse(path.passable(game_map, 0, MAP_HEIGHT - 1))
        # One pixel in from each edge should be fine.
        self.assertTrue(path.passable(game_map, MAP_WIDTH - 2, 0))
        self.assertTrue(path.passable(game_map, 0, MAP_HEIGHT - 2))


class HeuristicTests(unittest.TestCase):
    def test_manhattan(self):
        self.assertEqual(path.heuristic(0, 0, 3, 4), 7)
        self.assertEqual(path.heuristic(5, 5, 5, 5), 0)
        self.assertEqual(path.heuristic(-1, -1, 1, 1), 4)


class ChoosePathStepTests(unittest.TestCase):
    def test_empty_path_returns_unfound_step(self):
        step = path.choose_path_step([])
        self.assertFalse(step.found)

    def test_short_path_returns_last_step(self):
        p = [
            PathStep(found=True, x=1, y=1),
            PathStep(found=True, x=2, y=2),
        ]
        step = path.choose_path_step(p)
        self.assertEqual((step.x, step.y), (2, 2))

    def test_long_path_returns_lookahead_step(self):
        p = [PathStep(found=True, x=i, y=0) for i in range(40)]
        step = path.choose_path_step(p)
        # PATH_LOOKAHEAD = 18, so index 18 is x=18.
        self.assertEqual(step.x, path.PATH_LOOKAHEAD)


# ---------------------------------------------------------------------------
# Synthetic map A*
# ---------------------------------------------------------------------------


class SyntheticMapAStarTests(unittest.TestCase):
    """A\\* on hand-built walk masks.

    Each test fabricates a walk mask with a known obstacle and
    asserts the returned path either (a) matches the Manhattan
    length when unobstructed, (b) is strictly longer when a wall
    forces a detour, or (c) is empty when unreachable. These are
    invariants that would survive any reasonable A\\* reimplementation
    — they guard the contract, not a specific route.
    """

    def _map_with_walls(self, walls: list[tuple[int, int]]) -> GameMap:
        mask = np.ones((MAP_HEIGHT, MAP_WIDTH), dtype=bool)
        for x, y in walls:
            mask[y, x] = False
        return _make_synthetic_map(mask)

    def test_straight_line_matches_manhattan(self):
        game_map = self._map_with_walls([])
        steps = path.find_path(_percep_at(100, 100), game_map, 110, 100)
        self.assertEqual(len(steps), 10)
        # Goal is the last waypoint.
        self.assertEqual((steps[-1].x, steps[-1].y), (110, 100))
        self.assertTrue(all(s.found for s in steps))

    def test_start_equals_goal_returns_empty_path(self):
        """By convention: no waypoint to go to. Callers treat the
        empty list as "idle" not "unreachable"."""
        game_map = self._map_with_walls([])
        self.assertEqual(path.find_path(_percep_at(50, 50), game_map, 50, 50), [])

    def test_wall_forces_detour(self):
        # Vertical wall between start and goal.
        walls = [(105, y) for y in range(95, 106)]
        game_map = self._map_with_walls(walls)
        steps = path.find_path(_percep_at(100, 100), game_map, 110, 100)
        # Must be strictly longer than the 10-pixel Manhattan line.
        self.assertGreater(len(steps), 10)
        # Still terminates at the goal.
        self.assertEqual((steps[-1].x, steps[-1].y), (110, 100))
        # And does not pass through any wall cell.
        wall_set = set(walls)
        for s in steps:
            self.assertNotIn((s.x, s.y), wall_set)

    def test_unreachable_goal_returns_empty(self):
        # Ring of walls around the goal with no gap.
        walls = []
        for x in range(198, 203):
            for y in range(198, 203):
                if (x, y) != (200, 200):
                    walls.append((x, y))
        game_map = self._map_with_walls(walls)
        self.assertEqual(path.find_path(_percep_at(100, 100), game_map, 200, 200), [])

    def test_impassable_start_or_goal_returns_empty(self):
        walls = [(110, 100)]  # goal is a wall
        game_map = self._map_with_walls(walls)
        self.assertEqual(path.find_path(_percep_at(100, 100), game_map, 110, 100), [])


class PathDistanceAndGoalDistanceTests(unittest.TestCase):
    def test_path_distance_zero_on_goal(self):
        game_map = _make_synthetic_map(np.ones((MAP_HEIGHT, MAP_WIDTH), dtype=bool))
        self.assertEqual(path.path_distance(_percep_at(50, 50), game_map, 50, 50), 0)

    def test_path_distance_matches_length(self):
        game_map = _make_synthetic_map(np.ones((MAP_HEIGHT, MAP_WIDTH), dtype=bool))
        self.assertEqual(path.path_distance(_percep_at(100, 100), game_map, 110, 100), 10)

    def test_path_distance_unreachable_returns_sentinel(self):
        """Unreachable path returns a value large enough to always
        lose in a min-comparison against any real length. Exact value
        matters less than "it's an order of magnitude beyond any real
        map traversal"."""
        mask = np.ones((MAP_HEIGHT, MAP_WIDTH), dtype=bool)
        for x in range(0, MAP_WIDTH):
            mask[50, x] = False  # horizontal wall across the whole map
        game_map = _make_synthetic_map(mask)
        d = path.path_distance(_percep_at(100, 10), game_map, 100, 100)
        self.assertGreater(d, MAP_WIDTH * MAP_HEIGHT)

    def test_goal_distance_ghost_uses_manhattan(self):
        """Ghosts fly through walls; their distance ignores the
        walk mask entirely."""
        walls = [(105, y) for y in range(95, 106)]  # would force a detour for non-ghosts
        mask = np.ones((MAP_HEIGHT, MAP_WIDTH), dtype=bool)
        for x, y in walls:
            mask[y, x] = False
        game_map = _make_synthetic_map(mask)
        ghost_dist = path.goal_distance(_percep_at(100, 100), game_map, True, 110, 100)
        self.assertEqual(ghost_dist, 10)  # pure Manhattan

    def test_goal_distance_alive_uses_path_length(self):
        mask = np.ones((MAP_HEIGHT, MAP_WIDTH), dtype=bool)
        game_map = _make_synthetic_map(mask)
        self.assertEqual(
            path.goal_distance(_percep_at(100, 100), game_map, False, 110, 100),
            10,
        )


# ---------------------------------------------------------------------------
# Real-map integration + perf
# ---------------------------------------------------------------------------


class RealMapAStarTests(unittest.TestCase):
    """Run A\\* on the shipped skeld2 walk mask.

    Loads the real game map (952×534, ~253k walkable cells) and
    finds paths between known-walkable points. Asserts success +
    a loose wall-clock budget. The budget is generous because a
    full cross-map path can exercise ~100k nodes; the goal is to
    catch regressions, not defend a specific number.
    """

    @classmethod
    def setUpClass(cls):
        cls.data = load_reference_data()
        walkable = np.argwhere(cls.data.map.walk_mask)
        # Pick two well-separated walkable points deterministically.
        cls.start_y, cls.start_x = (int(v) for v in walkable[len(walkable) // 4])
        cls.goal_y, cls.goal_x = (int(v) for v in walkable[(3 * len(walkable)) // 4])

    def test_real_map_reachable(self):
        percep = _percep_at(self.start_x, self.start_y)
        steps = path.find_path(percep, self.data.map, self.goal_x, self.goal_y)
        self.assertGreater(len(steps), 0, "expected a reachable path on the real map")
        # The final waypoint is the goal cell.
        self.assertEqual((steps[-1].x, steps[-1].y), (self.goal_x, self.goal_y))
        # Every waypoint is walkable.
        for s in steps:
            self.assertTrue(
                self.data.map.walk_mask[s.y, s.x],
                f"waypoint ({s.x},{s.y}) is not on the walk mask",
            )

    def test_real_map_reaches_first_task(self):
        """End-to-end: from a walkable start, A\\* reaches the first
        task station from ``map.json``. This is the common case the
        crewmate policy will drive."""
        percep = _percep_at(self.start_x, self.start_y)
        task = self.data.map.tasks[0]
        steps = path.find_path(percep, self.data.map, task.cx, task.cy)
        self.assertGreater(len(steps), 0)

    def test_real_map_path_budget(self):
        """Wall-clock guard: a typical task path from a stationary
        bot should finish in well under 150 ms in Python. Generous
        because A\\* worst cases on this map can touch ~100k nodes
        across a ~1000-step path."""
        percep = _percep_at(self.start_x, self.start_y)
        task = self.data.map.tasks[0]
        t0 = time.perf_counter()
        steps = path.find_path(percep, self.data.map, task.cx, task.cy)
        elapsed_ms = (time.perf_counter() - t0) * 1000
        self.assertGreater(len(steps), 0)
        self.assertLess(
            elapsed_ms,
            150.0,
            f"find_path regressed to {elapsed_ms:.1f} ms for a {len(steps)}-step path",
        )


if __name__ == "__main__":
    unittest.main()
