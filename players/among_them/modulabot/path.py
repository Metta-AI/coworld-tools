"""A\\* pathfinding on the walk mask.

Port of ``among_them/players/modulabot/path.nim``. Runs over the
952×534 walk mask at one pixel per A\\* node, using Manhattan
distance as the heuristic for 4-connected unit-cost moves.

Typical use from the crewmate / imposter policies::

    from modulabot import path
    steps = path.find_path(bot.percep, game_map, goal_x, goal_y)
    if steps:
        waypoint = path.choose_path_step(steps)
        # waypoint.found is True; steer toward (waypoint.x, waypoint.y).

Path distance + goal-distance helpers let task-selection code rank
candidate task stations by real reachability, with a Manhattan
fallback for ghosts (they fly through walls so A\\* is wasted
effort).

Performance: a full-map A\\* over the skeld2 walk mask can visit
tens of thousands of nodes in the pathological case. In Python
the per-node overhead (heap push / pop, hash-free seq indexing,
bounds checks) costs ~1–2 µs, so worst-case paths land around
50–100 ms. We accept this because A\\* is only invoked when a
policy sets a new goal — usually once per ten-plus frames, not
every tick — and the average case (moving to a reachable task
across one or two rooms) completes in well under 10 ms.

The ``PathStep`` waypoint dataclass and the world-coordinate convention
match :mod:`modulabot.geometry`: goal coordinates are world pixels
in the 952×534 map rectangle.
"""

from __future__ import annotations

import heapq

from .data import GameMap, MAP_HEIGHT, MAP_WIDTH
from .geometry import heuristic as manhattan_heuristic
from .geometry import player_world_x, player_world_y
from .state import Perception, PathStep

#: Steps ahead in the A\\* path to aim at. Smaller = more reactive
#: (and more thrashy on snags); larger = smoother but more
#: overshoot-prone. Matches ``PathLookahead`` in Nim.
PATH_LOOKAHEAD = 18


def tile_width() -> int:
    """Pixel width of the path grid. Equal to :data:`~modulabot.data.MAP_WIDTH`
    because A\\* runs at one pixel per node."""
    return MAP_WIDTH


def passable(game_map: GameMap, x: int, y: int) -> bool:
    """True when world pixel ``(x, y)`` is walkable and in-bounds.

    The sim uses a 1×1 collision box for Among Them (``CollisionW
    = CollisionH = 1`` in ``sim.nim``), so this reduces to a walk-mask
    lookup with one-pixel margins on the far edges — matching the
    Nim ``passable`` proc. The margin protects the neighbour-expansion
    loop below from stepping off the end of the mask.
    """
    if x < 0 or y < 0:
        return False
    if x + 1 >= MAP_WIDTH or y + 1 >= MAP_HEIGHT:
        return False
    return bool(game_map.walk_mask[y, x])


def _map_index(x: int, y: int) -> int:
    """Flat index into a (MAP_HEIGHT, MAP_WIDTH) grid.

    Matches the Nim ``mapIndexSafe`` row-major layout. Used to key
    the A\\* parent / cost tables; callers that read the walk mask
    directly still use ``walk_mask[y, x]`` numpy indexing.
    """
    return y * MAP_WIDTH + x


def heuristic(ax: int, ay: int, bx: int, by: int) -> int:
    """Manhattan distance heuristic for A\\*.

    Admissible for 4-connected unit-cost moves (which is what we
    emit). Shared with :mod:`modulabot.geometry` — re-exported here
    because path-specific callers read it more naturally from this
    module.
    """
    return manhattan_heuristic(ax, ay, bx, by)


def _reconstruct_path(
    parents: list[int], start_index: int, goal_index: int
) -> list[PathStep]:
    """Walk the parent table from goal back to start, then reverse.

    Matches the Nim ``reconstructPath`` semantics exactly: the
    returned list excludes the start cell and includes the goal
    cell, in traversal order. An empty list means either start == goal
    or no path was found (callers distinguish via the preceding
    :func:`find_path` return value).
    """
    out: list[PathStep] = []
    step_index = goal_index
    while step_index != start_index and step_index >= 0:
        out.append(
            PathStep(
                found=True,
                x=step_index % MAP_WIDTH,
                y=step_index // MAP_WIDTH,
            )
        )
        step_index = parents[step_index]
    out.reverse()
    return out


def find_path(
    percep: Perception,
    game_map: GameMap,
    goal_x: int,
    goal_y: int,
) -> list[PathStep]:
    """Full A\\* path from the player's world position to ``(goal_x, goal_y)``.

    Returns ``[]`` (empty list) when either endpoint is impassable
    or no path exists; otherwise returns the sequence of
    :class:`~modulabot.state.PathStep` waypoints, one per pixel,
    from the first step *after* start through the goal cell
    inclusive.

    Reads only the ``Perception`` (for the current camera → world
    conversion) and the :class:`~modulabot.data.GameMap`'s walk mask.
    Does not mutate either — callers cache the result in
    ``bot.goal.path`` themselves.
    """
    start_x = player_world_x(percep)
    start_y = player_world_y(percep)
    if not passable(game_map, start_x, start_y):
        return []
    if not passable(game_map, goal_x, goal_y):
        return []

    area = MAP_WIDTH * MAP_HEIGHT
    start_index = _map_index(start_x, start_y)
    goal_index = _map_index(goal_x, goal_y)
    if start_index == goal_index:
        return []

    # Flat-list state. ``-2`` means "never visited"; start cell's
    # parent is set to ``-1`` so :func:`_reconstruct_path` knows
    # when it's reached the root.
    parents = [-2] * area
    costs = [1 << 30] * area
    closed = [False] * area

    parents[start_index] = -1
    costs[start_index] = 0

    # Heap entries: (priority, tiebreak_index, node_index). Python's
    # heapq is a min-heap and breaks ties on the *whole* tuple, so we
    # include the node index explicitly — matches the Nim < comparator
    # that falls back on ``index`` when priorities tie.
    open_set: list[tuple[int, int, int]] = []
    heapq.heappush(
        open_set,
        (heuristic(start_x, start_y, goal_x, goal_y), start_index, start_index),
    )

    walk_mask = game_map.walk_mask
    while open_set:
        _priority, _tiebreak, current = heapq.heappop(open_set)
        if closed[current]:
            continue
        if current == goal_index:
            return _reconstruct_path(parents, start_index, goal_index)
        closed[current] = True
        cx = current % MAP_WIDTH
        cy = current // MAP_WIDTH
        current_cost = costs[current]
        # 4-connected neighbours. Unit-cost so each neighbour has
        # ``new_cost = current_cost + 1``.
        for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
            nx = cx + dx
            ny = cy + dy
            # Inlined passability check: hot path, avoid the function
            # dispatch overhead.
            if nx < 0 or ny < 0 or nx + 1 >= MAP_WIDTH or ny + 1 >= MAP_HEIGHT:
                continue
            if not walk_mask[ny, nx]:
                continue
            next_index = ny * MAP_WIDTH + nx
            if closed[next_index]:
                continue
            new_cost = current_cost + 1
            if new_cost >= costs[next_index]:
                continue
            costs[next_index] = new_cost
            parents[next_index] = current
            heapq.heappush(
                open_set,
                (new_cost + heuristic(nx, ny, goal_x, goal_y), next_index, next_index),
            )

    return []


def path_distance(
    percep: Perception,
    game_map: GameMap,
    goal_x: int,
    goal_y: int,
) -> int:
    """Real A\\* path length, or ``1 << 30`` (our "unreachable"
    sentinel) when no path exists.

    Used by task selection to rank candidate stations by true
    reachability rather than Manhattan distance — tasks on the
    wrong side of a wall aren't equidistant to tasks with a
    straight corridor. Returns 0 when we're already standing on the
    goal.
    """
    if player_world_x(percep) == goal_x and player_world_y(percep) == goal_y:
        return 0
    path = find_path(percep, game_map, goal_x, goal_y)
    if not path:
        return 1 << 30
    return len(path)


def goal_distance(
    percep: Perception,
    game_map: GameMap,
    is_ghost: bool,
    goal_x: int,
    goal_y: int,
) -> int:
    """Distance metric for goal comparison.

    Ghosts fly through walls, so Manhattan distance is exact for
    them; real A\\* would just pay the cost with no accuracy benefit.
    Living crewmates / imposters get :func:`path_distance`.
    """
    if is_ghost:
        return heuristic(
            player_world_x(percep), player_world_y(percep), goal_x, goal_y
        )
    return path_distance(percep, game_map, goal_x, goal_y)


# ---------------------------------------------------------------------------
# Lookahead waypoint
# ---------------------------------------------------------------------------


def choose_path_step(path: list[PathStep]) -> PathStep:
    """Return a short-lookahead waypoint from ``path``.

    Picks the ``min(len(path)-1, PATH_LOOKAHEAD)``-th step so close
    paths still produce a meaningful target (the Nim version does
    the same). An empty path returns an unfound default
    :class:`PathStep` — callers should treat that as "idle".
    """
    if not path:
        return PathStep()
    index = min(len(path) - 1, PATH_LOOKAHEAD)
    return path[index]


__all__ = [
    "PATH_LOOKAHEAD",
    "tile_width",
    "passable",
    "heuristic",
    "find_path",
    "path_distance",
    "goal_distance",
    "choose_path_step",
]
