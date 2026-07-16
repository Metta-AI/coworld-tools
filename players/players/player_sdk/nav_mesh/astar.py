"""A* routing over the nav-mesh graph: :func:`find_path`.

Origin: extracted from Ron Dahlgren's (swgy) agent libraries
(swgy-crewrift; original module ``swgy_base.nav.astar``).

The mesh's edge weights are euclidean endpoint distances (the ``builder``
builder assigns ``math.dist``/``sqrt`` weights). ``params.diagonal_bias`` then
re-costs each edge between its Euclidean length and its **Chebyshev** span
(``max(|dx|, |dy|)``) -- the latter is the engine's true traversal *time* for the
edge, since velX/velY clamp independently so a diagonal covers both axes at once.
Cost and heuristic use the *same* blended metric, so a straight-line node-to-node
heuristic stays admissible and consistent -- plain A* (``heuristic_weight = 1.0``)
returns optimal paths under that metric (a convex blend of two metrics is itself
a metric, so the straight-line estimate never exceeds a summed-edge path by the
triangle inequality). ``heuristic_weight > 1`` is *intentionally* inadmissible
(weighted/greedy: fewer expansions, suboptimal paths).

Edges are re-costed by the *ratio* of the blended metric to their endpoint
euclidean (``weight * metric/euclid``), so a normal walk edge (``weight ==
euclid``) becomes its blended metric while an edge weighted off its span keeps
that intent. Caveat for future vent/door edges: a "teleport" edge whose
``weight`` is smaller than the euclidean gap between its endpoints would make the
heuristic over-estimate and break optimality. Keep such weights >= endpoint
distance.
"""

from __future__ import annotations

import heapq
import math
from itertools import count

from .model import NavMesh
from .params import NavParams
from .plan import NavPlan


def _metric(ax: float, ay: float, bx: float, by: float, bias: float) -> float:
    """Distance from ``a`` to ``b`` blended Euclidean->Chebyshev by ``bias``.

    ``bias=0`` -> Euclidean length; ``bias=1`` -> Chebyshev span (travel time, in
    px of the slower axis). Chebyshev <= Euclidean, so the blend lerps down from
    the length toward the time as ``bias`` rises.
    """
    dx, dy = abs(ax - bx), abs(ay - by)
    euclid = math.hypot(dx, dy)
    if bias <= 0.0:
        return euclid
    chebyshev = dx if dx > dy else dy
    return euclid + (chebyshev - euclid) * bias


def _resolve(mesh: NavMesh, point: int | tuple[int, int]) -> int | None:
    """Coerce a node id or ``(x, y)`` coordinate to a node id."""
    if isinstance(point, tuple):
        return mesh.nearest_node(point[0], point[1])
    return point


def find_path(
    mesh: NavMesh,
    start: int | tuple[int, int],
    goal: int | tuple[int, int],
    params: NavParams = NavParams(),
) -> NavPlan | None:
    """Shortest route from ``start`` to ``goal`` across ``mesh``, or ``None``.

    ``start``/``goal`` may be node ids or map-pixel ``(x, y)`` coordinates; a
    coordinate snaps to the nearest node. Edge cost is the edge weight plus
    ``params.avoid_penalty`` for any edge tagged in ``params.avoid_tags`` (or the
    edge is skipped entirely when ``params.allow_avoided`` is False). Returns
    ``None`` if either endpoint can't be resolved or the goal is unreachable.
    """
    start_id = _resolve(mesh, start)
    goal_id = _resolve(mesh, goal)
    if start_id is None or goal_id is None:
        return None

    if start_id == goal_id:
        node = mesh.node(goal_id)
        return NavPlan(nodes=(goal_id,), waypoints=((node.x, node.y),), cost=0.0, goal=goal_id)

    goal_node = mesh.node(goal_id)
    gx, gy = goal_node.x, goal_node.y
    hw = params.heuristic_weight
    bias = params.diagonal_bias

    def heuristic(node_id: int) -> float:
        n = mesh.node(node_id)
        return _metric(n.x, n.y, gx, gy, bias) * hw

    counter = count()  # tiebreak so node ids are never compared under equal f
    open_heap: list[tuple[float, int, int]] = [(heuristic(start_id), next(counter), start_id)]
    g_score: dict[int, float] = {start_id: 0.0}
    came_from: dict[int, int] = {}
    closed: set[int] = set()

    while open_heap:
        _f, _c, current = heapq.heappop(open_heap)
        if current == goal_id:
            return _reconstruct(mesh, came_from, goal_id, g_score[goal_id])
        if current in closed:
            continue
        closed.add(current)

        cur = mesh.node(current)
        for nbr, weight, tags in mesh.neighbors(current):
            if nbr in closed:
                continue
            # Re-cost the edge by the time/length ratio of the blended metric:
            # a normal walk edge (weight == endpoint euclidean) becomes its
            # travel-time metric, while an edge whose weight is deliberately set
            # off its span (a cheap vent shortcut, or a teleport surcharge) keeps
            # that intent, just scaled by the same diagonal discount.
            n = mesh.node(nbr)
            euclid = math.hypot(cur.x - n.x, cur.y - n.y)
            ratio = _metric(cur.x, cur.y, n.x, n.y, bias) / euclid if euclid > 0.0 else 1.0
            step = weight * ratio
            if tags & params.avoid_tags:
                if not params.allow_avoided:
                    continue
                step += params.avoid_penalty
            tentative = g_score[current] + step
            if tentative < g_score.get(nbr, math.inf):
                came_from[nbr] = current
                g_score[nbr] = tentative
                heapq.heappush(open_heap, (tentative + heuristic(nbr), next(counter), nbr))

    return None


def _reconstruct(mesh: NavMesh, came_from: dict[int, int], goal_id: int, cost: float) -> NavPlan:
    ids = [goal_id]
    while ids[-1] in came_from:
        ids.append(came_from[ids[-1]])
    ids.reverse()
    waypoints = tuple((mesh.node(i).x, mesh.node(i).y) for i in ids)
    return NavPlan(nodes=tuple(ids), waypoints=waypoints, cost=cost, goal=goal_id)
